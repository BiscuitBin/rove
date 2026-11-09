# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "duckdb==2.0.0",
#   "fastavro==1.13.1",
#   "zstandard==0.25.0",
# ]
# ///
"""PROTOTYPE, throwaway: insert throughput of eight store variants, from empty and populated.

Two insert modes (`single`: one transaction per row, the crawler's pattern; `batch`: 256
rows per transaction), two row mixes (`mixed`: a stride sample over the whole corpus;
`commoncrawl`: every Common Crawl page, into a base drawn from the other regimes) and two
scenarios (`empty`: 0 -> N rows; `populated`: 50,000 -> 50,000 + N). Every measurement
runs in a fresh child process (this script with `--child`) that prints one JSON line with
its own peak RSS, the wall time of the insert loop, the wall time of the compaction, and
the store's allocated bytes before the inserts, after them (WAL and journal included) and
after `VACUUM` or `CHECKPOINT`. The populated base is built once per (variant, mix) by the
`batch` inserter and cloned per run with `cp -Rc` (APFS clonefile, macOS only), so each
run starts from the same bytes. The row samples are streamed from JSON-lines files the
parent writes once under `ai_tmp/duckdb-vs-sqlite/results/`.

The eighth variant, `avro-zstd`, appends to one Avro container file through fastavro
(zstd level 3): `single` opens the file, appends one record and fsyncs, per row, as the
files store fsyncs its manifest; `batch` does the same per BATCH rows. `--variants`
restricts the run and `--suffix` names the results file.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import fastavro
import zstandard
from bench_formats import AVRO_PARSED
from load_stores import (
    COLUMNS,
    CORPUS,
    DUCKDB_TYPES,
    META_COLUMNS,
    RESULTS,
    SCRATCH,
    ZSTD_LEVEL,
    sqlite_schema,
    tree_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

VARIANTS = [
    "files",
    "sqlite-raw",
    "sqlite-raw-wal",
    "sqlite-zstd",
    "sqlite-zstd-wal",
    "duckdb-default",
    "duckdb-zstd",
    "avro-zstd",
]
MODES = ["single", "batch"]
MIXES = ["mixed", "commoncrawl"]
SCENARIOS = ["empty", "populated"]
BATCH = 256
POPULATE = 50_000
INSERT = 10_000
INSERTS_DIR = SCRATCH / "inserts"
COLUMN_LIST = ", ".join(COLUMNS)
PLACEHOLDERS = ", ".join("?" * len(COLUMNS))
INSERT_SQL = f"INSERT INTO pages ({COLUMN_LIST}) VALUES ({PLACEHOLDERS})"  # noqa: S608  fixed column names
BODY_COLUMNS = {"html", "markdown"}
CC_MARKER = b'"regime": "commoncrawl"'


def stream(source: Path) -> Iterator[dict[str, Any]]:
    """Stream a JSON-lines sample one row at a time; the file is never loaded whole."""
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def batches(source: Path) -> Iterator[list[dict[str, Any]]]:
    """Group a streamed sample into lists of at most BATCH rows."""
    batch: list[dict[str, Any]] = []
    for page in stream(source):
        batch.append(page)
        if len(batch) >= BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


def store_bytes(target: Path) -> int:
    """Allocated bytes of a store directory, WAL, shm and journal files included."""
    return tree_bytes(target)[1]


def leftovers(target: Path) -> list[str]:
    """Names of WAL, shm or journal files still present after the store was closed."""
    suffixes = (".wal", "-wal", "-shm", "-journal")
    return sorted(p.name for p in target.iterdir() if p.name.endswith(suffixes))


# -------------------------------------------------------------- children ---


class Inserter:
    """One store variant opened on `target`, inserting rows from a sample file."""

    def __init__(self, variant: str, target: Path) -> None:
        """Remember the variant and where it lives; `open` creates or opens it."""
        self.variant = variant
        self.target = target
        self.zstd = "zstd" in variant
        self.compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL) if self.zstd else None
        self.info: dict[str, Any] = {}

    def values(self, page: dict[str, Any]) -> list[Any]:
        """The row in column order, bodies compressed for the zstd variants."""
        out = []
        for column in COLUMNS:
            value = page[column]
            if column in BODY_COLUMNS and self.compressor is not None and value is not None:
                value = self.compressor.compress(value.encode())
            out.append(value)
        return out

    def open(self) -> None:
        """Create or open the store; outside the timed region."""
        raise NotImplementedError

    def count(self) -> int:
        """Rows the store holds."""
        raise NotImplementedError

    def insert_single(self, source: Path) -> None:
        """One transaction per row."""
        raise NotImplementedError

    def insert_batch(self, source: Path) -> None:
        """One transaction per BATCH rows."""
        raise NotImplementedError

    def compact(self) -> None:
        """VACUUM or CHECKPOINT, then close."""
        raise NotImplementedError


class FilesInserter(Inserter):
    """One HTML and one Markdown file per page under `<regime>/<sample>-<n>/`, a manifest.

    `single` fsyncs the manifest after each row's line; the body files themselves are
    written to a `.part` name and renamed, not fsynced. `batch` fsyncs the manifest once
    per BATCH rows. There is no compaction.
    """

    def open(self) -> None:
        """Create the directory and the manifest if they do not exist."""
        self.target.mkdir(parents=True, exist_ok=True)
        self.manifest = self.target / "manifest.jsonl"
        self.manifest.touch()

    def count(self) -> int:
        """Manifest lines."""
        with self.manifest.open("rb") as handle:
            return sum(1 for _ in handle)

    def write_page(self, page: dict[str, Any], directory: Path) -> str:
        """Write the two bodies atomically and return the manifest line."""
        stem = directory / page["content_digest"][:16]
        for suffix, body in ((".html", page["html"]), (".md", page["markdown"])):
            if body is None:
                continue
            partial = stem.with_suffix(suffix + ".part")
            partial.write_text(body, encoding="utf-8")
            partial.rename(stem.with_suffix(suffix))
        meta = {c: page[c] for c in META_COLUMNS}
        meta["path"] = stem.relative_to(self.target).as_posix()
        return json.dumps(meta, ensure_ascii=False) + "\n"

    def directory(self, source: Path, n: int) -> Path:
        """The per-thousand directory a page lands in, namespaced by the sample file."""
        return self.target / f"{source.stem}-{n // 1000:04d}"

    def insert_single(self, source: Path) -> None:
        """Write the bodies, append the manifest line, flush and fsync, per row."""
        with self.manifest.open("a", encoding="utf-8") as out:
            for n, page in enumerate(stream(source)):
                directory = self.directory(source, n)
                directory.mkdir(exist_ok=True)
                out.write(self.write_page(page, directory))
                out.flush()
                os.fsync(out.fileno())

    def insert_batch(self, source: Path) -> None:
        """Write the bodies of BATCH rows, then their manifest lines, one flush and fsync."""
        n = 0
        with self.manifest.open("a", encoding="utf-8") as out:
            for batch in batches(source):
                lines = []
                for page in batch:
                    directory = self.directory(source, n)
                    directory.mkdir(exist_ok=True)
                    lines.append(self.write_page(page, directory))
                    n += 1
                out.write("".join(lines))
                out.flush()
                os.fsync(out.fileno())

    def compact(self) -> None:
        """Nothing to compact."""


class SqliteInserter(Inserter):
    """SQLite with TEXT or per-row zstd BLOB bodies; rollback journal or WAL."""

    def open(self) -> None:
        """Create the table on a new file; apply the WAL pragmas; read the modes back."""
        self.target.mkdir(parents=True, exist_ok=True)
        path = self.target / "pages.sqlite"
        fresh = not path.exists()
        self.connection = sqlite3.connect(path)
        wal = self.variant.endswith("-wal")
        if fresh:
            self.connection.execute(sqlite_schema("BLOB" if self.zstd else "TEXT"))
            self.connection.commit()
            if wal:
                self.connection.execute("PRAGMA journal_mode=WAL")
        if wal:
            self.connection.execute("PRAGMA synchronous=NORMAL")
        (journal,) = self.connection.execute("PRAGMA journal_mode").fetchone()
        (synchronous,) = self.connection.execute("PRAGMA synchronous").fetchone()
        self.info = {"journal_mode": journal, "synchronous": synchronous}

    def count(self) -> int:
        """Rows in the table."""
        (n,) = self.connection.execute("SELECT count(*) FROM pages").fetchone()
        return int(n)

    def insert_single(self, source: Path) -> None:
        """One implicit transaction per row, committed by the context manager."""
        for page in stream(source):
            with self.connection:
                self.connection.execute(INSERT_SQL, self.values(page))

    def insert_batch(self, source: Path) -> None:
        """One executemany per BATCH rows, one commit each."""
        for batch in batches(source):
            with self.connection:
                self.connection.executemany(INSERT_SQL, [self.values(p) for p in batch])

    def compact(self) -> None:
        """VACUUM, then close, which checkpoints and removes a WAL."""
        self.connection.execute("VACUUM")
        self.connection.close()


class DuckdbInserter(Inserter):
    """DuckDB VARCHAR bodies, default compression or ZSTD forced on the two bodies."""

    def open(self) -> None:
        """Create the table on a new file, as load_stores.py does."""
        self.target.mkdir(parents=True, exist_ok=True)
        path = self.target / "pages.duckdb"
        fresh = not path.exists()
        self.connection = duckdb.connect(str(path))
        if fresh:
            columns = []
            for name, kind in DUCKDB_TYPES.items():
                forced = " USING COMPRESSION ZSTD" if self.zstd and name in BODY_COLUMNS else ""
                key = " PRIMARY KEY" if name == "identity" else ""
                columns.append(f"{name} {kind}{forced}{key}")
            self.connection.execute(f"CREATE TABLE pages ({', '.join(columns)})")
        threads = self.connection.execute("SELECT current_setting('threads')").fetchone()
        self.info = {"threads": threads[0] if threads else None}

    def count(self) -> int:
        """Rows in the table."""
        row = self.connection.execute("SELECT count(*) FROM pages").fetchone()
        return int(row[0]) if row else 0

    def insert_single(self, source: Path) -> None:
        """BEGIN, one INSERT, COMMIT, per row."""
        for page in stream(source):
            self.connection.execute("BEGIN TRANSACTION")
            self.connection.execute(INSERT_SQL, self.values(page))
            self.connection.execute("COMMIT")

    def insert_batch(self, source: Path) -> None:
        """BEGIN, one executemany of BATCH rows, COMMIT."""
        for batch in batches(source):
            self.connection.execute("BEGIN TRANSACTION")
            self.connection.executemany(INSERT_SQL, [self.values(p) for p in batch])
            self.connection.execute("COMMIT")

    def compact(self) -> None:
        """CHECKPOINT, then close."""
        self.connection.execute("CHECKPOINT")
        self.connection.close()


class AvroInserter(Inserter):
    """One Avro container file appended to through fastavro, zstd level 3, fsync per write.

    Records are the page dicts themselves: the bodies stay strings and the codec
    compresses each block, so the per-row compressor of the base class is not used.
    There is no compaction.
    """

    def __init__(self, variant: str, target: Path) -> None:
        """Remember the variant and the file; no per-row compressor."""
        super().__init__(variant, target)
        self.compressor = None
        self.path = target / "pages.avro"

    def open(self) -> None:
        """Create the directory; the first write creates the file."""
        self.target.mkdir(parents=True, exist_ok=True)
        self.info = {"codec": "zstandard", "level": ZSTD_LEVEL}

    def count(self) -> int:
        """Records summed over the block headers; 0 before the first write."""
        if not self.path.exists():
            return 0
        with self.path.open("rb") as source:
            return sum(block.num_records for block in fastavro.block_reader(source))

    def write(self, pages: list[dict[str, Any]]) -> None:
        """Open, append the pages as one or more blocks, flush and fsync, close."""
        mode = "a+b" if self.path.exists() else "wb"
        with self.path.open(mode) as out:
            fastavro.writer(
                out, AVRO_PARSED, pages, codec="zstandard", codec_compression_level=ZSTD_LEVEL
            )
            out.flush()
            os.fsync(out.fileno())

    def insert_single(self, source: Path) -> None:
        """One append and fsync per row."""
        for page in stream(source):
            self.write([page])

    def insert_batch(self, source: Path) -> None:
        """One append and fsync per BATCH rows."""
        for batch in batches(source):
            self.write(batch)

    def compact(self) -> None:
        """Nothing to compact."""
        self.info["compaction"] = "none"


def inserter(variant: str, target: Path) -> Inserter:
    """The inserter class for a variant name."""
    if variant == "files":
        return FilesInserter(variant, target)
    if variant.startswith("avro"):
        return AvroInserter(variant, target)
    if variant.startswith("sqlite"):
        return SqliteInserter(variant, target)
    return DuckdbInserter(variant, target)


def sample_totals(source: Path) -> tuple[int, int]:
    """Rows and raw body bytes (HTML plus Markdown) of a sample file."""
    rows = raw = 0
    for page in stream(source):
        rows += 1
        raw += page["html_bytes"] + page["markdown_bytes"]
    return rows, raw


def child(variant: str, mode: str, source: Path, target: Path) -> None:
    """Insert one sample into one store and print the measurement as a JSON line."""
    size_before = store_bytes(target) if target.exists() else 0
    store = inserter(variant, target)
    store.open()
    rows_before = store.count()
    started = time.perf_counter()
    if mode == "single":
        store.insert_single(source)
    else:
        store.insert_batch(source)
    wall_insert = time.perf_counter() - started
    rows_after = store.count()
    size_after_inserts = store_bytes(target)
    started = time.perf_counter()
    store.compact()
    wall_compact = time.perf_counter() - started
    if left := leftovers(target):
        msg = f"{variant}: files left after compaction: {left}"
        raise RuntimeError(msg)
    rows, raw_bytes = sample_totals(source)
    if rows_after != rows_before + rows:
        msg = f"{variant}: {rows_before} + {rows} rows inserted but the store holds {rows_after}"
        raise RuntimeError(msg)
    report = {
        "variant": variant,
        "mode": mode,
        "rows": rows,
        "raw_bytes": raw_bytes,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "wall_insert": wall_insert,
        "wall_compact": wall_compact,
        "rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,  # bytes on macOS
        "size_before": size_before,
        "size_after_inserts": size_after_inserts,
        "size_after_compaction": store_bytes(target),
        **store.info,
    }
    print(json.dumps(report))


# ---------------------------------------------------------------- parent ---


def spread(index: int, total: int, wanted: int) -> bool:
    """Whether row `index` of `total` is one of `wanted` rows spread evenly over them."""
    return (index + 1) * wanted // total > index * wanted // total


def sample_files(populate: int, insert: int) -> dict[str, Path]:
    """The four sample files for these sizes."""
    return {
        "populate-mixed": RESULTS / f"populate-mixed-{populate}.jsonl",
        "insert-mixed": RESULTS / f"insert-mixed-{insert}.jsonl",
        "populate-nocc": RESULTS / f"populate-nocc-{populate}.jsonl",
        "insert-cc": RESULTS / f"insert-cc-{insert}.jsonl",
    }


def corpus_totals() -> tuple[int, int]:
    """Rows in the corpus, and how many of them are Common Crawl pages."""
    total = cc = 0
    with CORPUS.open("rb") as handle:
        for line in handle:
            total += 1
            cc += is_commoncrawl(line)
    return total, cc


def is_commoncrawl(line: bytes | str) -> bool:
    """Whether a corpus line is a Common Crawl page (substring prefilter, then parsed)."""
    marker = CC_MARKER if isinstance(line, bytes) else CC_MARKER.decode()
    return marker in line and json.loads(line)["regime"] == "commoncrawl"


class Picker:
    """Decides, one corpus line at a time, which sample files the line belongs to.

    The mixed pair takes `populate + insert` rows spread evenly over the corpus, and
    every sixth-or-so of those (spread evenly again) is an insert row, so the two are
    disjoint. The nocc base takes `populate` rows spread evenly over the non-Common-Crawl
    rows; the cc insert takes the first `insert` Common Crawl rows (all of them, at the
    default sizes).
    """

    def __init__(self, total: int, cc: int, populate: int, insert: int) -> None:
        """Remember the sizes; every counter starts at zero."""
        self.total, self.others = total, total - cc
        self.populate, self.insert = populate, insert
        self.index = self.picked = self.nocc = self.cc = 0

    def pick(self, line: str) -> list[str]:
        """The sample keys this corpus line goes to."""
        chosen = []
        wanted = self.populate + self.insert
        if spread(self.index, self.total, wanted):
            tail = spread(self.picked, wanted, self.insert)
            chosen.append("insert-mixed" if tail else "populate-mixed")
            self.picked += 1
        self.index += 1
        if is_commoncrawl(line):
            if self.cc < self.insert:
                chosen.append("insert-cc")
                self.cc += 1
        else:
            if spread(self.nocc, self.others, self.populate):
                chosen.append("populate-nocc")
            self.nocc += 1
        return chosen


def prepare(populate: int, insert: int) -> dict[str, Path]:
    """Write the four row samples from the corpus in one pass; skipped when they exist."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    files = sample_files(populate, insert)
    if all(p.exists() for p in files.values()):
        return files
    total, cc = corpus_totals()
    if total < populate + insert or total - cc < populate:
        sys.exit(f"corpus has {total} rows ({cc} commoncrawl), too few for {populate} + {insert}")
    picker = Picker(total, cc, populate, insert)
    counts = dict.fromkeys(files, 0)
    partials = {k: p.with_suffix(".part") for k, p in files.items()}
    handles = {k: p.open("w", encoding="utf-8") for k, p in partials.items()}
    with CORPUS.open(encoding="utf-8") as corpus:
        for line in corpus:
            for key in picker.pick(line):
                handles[key].write(line if line.endswith("\n") else line + "\n")
                counts[key] += 1
    for handle in handles.values():
        handle.close()
    for key, partial in partials.items():
        partial.replace(files[key])
    print(f"prepared samples: {counts}", file=sys.stderr)
    return files


def run_child(variant: str, mode: str, source: Path, target: Path) -> dict[str, Any]:
    """Spawn one child and parse its JSON line."""
    completed = subprocess.run(
        [sys.executable, __file__, "--child", variant, mode, str(source), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def clone(base: Path, target: Path) -> None:
    """APFS clone of the base store, so each run starts from the same bytes."""
    shutil.rmtree(target, ignore_errors=True)
    subprocess.run(["cp", "-Rc", str(base), str(target)], check=True)


def measure(variant: str, mix: str, files: dict[str, Path]) -> list[dict[str, Any]]:
    """Build the base for (variant, mix) once, then run the four (mode, scenario) cells."""
    populate = files["populate-mixed" if mix == "mixed" else "populate-nocc"]
    source = files["insert-mixed" if mix == "mixed" else "insert-cc"]
    base = INSERTS_DIR / f"base-{variant}-{mix}-PROTOTYPE-wipe-me"
    target = INSERTS_DIR / f"run-{variant}-{mix}-PROTOTYPE-wipe-me"
    shutil.rmtree(base, ignore_errors=True)
    started = time.perf_counter()
    built = run_child(variant, "batch", populate, base)
    took = time.perf_counter() - started
    print(
        f"built base {variant} {mix}: {built['rows_after']} rows,"
        f" {built['size_after_compaction'] / 2**20:.0f} MiB, {took:.0f} s",
        file=sys.stderr,
    )
    results = []
    for mode in MODES:
        for scenario in SCENARIOS:
            if scenario == "populated":
                clone(base, target)
            else:
                shutil.rmtree(target, ignore_errors=True)
            found = run_child(variant, mode, source, target)
            shutil.rmtree(target, ignore_errors=True)
            record = {"variant": variant, "mode": mode, "mix": mix, "scenario": scenario, **found}
            record["rows_per_s"] = found["rows"] / found["wall_insert"]
            record["raw_mib_per_s"] = found["raw_bytes"] / 2**20 / found["wall_insert"]
            results.append(record)
            print(
                f"{variant} {mode} {mix} {scenario}: {record['rows_per_s']:.0f} rows/s,"
                f" {found['wall_insert']:.1f} s insert, {found['wall_compact']:.1f} s compact,"
                f" {found['rss_bytes'] / 2**20:.0f} MiB",
                file=sys.stderr,
            )
    shutil.rmtree(base, ignore_errors=True)
    return results


def print_table(results: list[dict[str, Any]]) -> None:
    """One Markdown table, one row per measurement."""
    print("\nInsert throughput, one run per cell, a fresh process for each\n")
    print(
        "| variant | mode | mix | scenario | rows | rows/s | raw MiB/s | insert s | compact s"
        " | peak RSS MiB | MiB before > after inserts > after compaction |"
    )
    print("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for r in results:
        keys = ("size_before", "size_after_inserts", "size_after_compaction")
        sizes = " > ".join(f"{r[k] / 2**20:.1f}" for k in keys)
        print(
            f"| {r['variant']} | {r['mode']} | {r['mix']} | {r['scenario']} | {r['rows']}"
            f" | {r['rows_per_s']:.0f} | {r['raw_mib_per_s']:.1f} | {r['wall_insert']:.2f}"
            f" | {r['wall_compact']:.2f} | {r['rss_bytes'] / 2**20:.0f} | {sizes} |"
        )


def main() -> None:
    """Parent: prepare the samples, measure every cell, print the table, save the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs=4, metavar=("VARIANT", "MODE", "SOURCE", "TARGET"))
    parser.add_argument("--populate", type=int, default=POPULATE, help="rows in the base")
    parser.add_argument("--insert", type=int, default=INSERT, help="rows inserted per run")
    parser.add_argument("--variants", help="comma-separated subset of the variants to run")
    parser.add_argument("--suffix", help="name the results file inserts-SUFFIX.json")
    args = parser.parse_args()
    if args.child:
        variant, mode, source, target = args.child
        child(variant, mode, Path(source), Path(target))
        return
    if not CORPUS.exists():
        sys.exit(f"no corpus at {CORPUS}; run build_corpus.py first")
    variants = args.variants.split(",") if args.variants else VARIANTS
    if unknown := set(variants) - set(VARIANTS):
        sys.exit(f"unknown variants {sorted(unknown)}; choose from {VARIANTS}")
    files = prepare(args.populate, args.insert)
    INSERTS_DIR.mkdir(parents=True, exist_ok=True)
    results = [r for variant in variants for mix in MIXES for r in measure(variant, mix, files)]
    print_table(results)
    sizes = (args.populate, args.insert)
    suffix = "" if sizes == (POPULATE, INSERT) else f"-{args.populate}-{args.insert}"
    suffix = f"-{args.suffix}" if args.suffix else suffix
    out = RESULTS / f"inserts{suffix}.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
