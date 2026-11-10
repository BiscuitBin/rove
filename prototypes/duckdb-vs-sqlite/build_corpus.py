# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "html-to-markdown==3.21.2",
#   "warcio==1.8.2",
# ]
# ///
"""PROTOTYPE, throwaway: build the page corpus for the DuckDB against SQLite comparison.

Reads pages from the sources `--sources` names, converts each HTML page to Markdown with
a throwaway converter in a process pool, and writes one JSON line per page to
`ai_tmp/duckdb-vs-sqlite/corpus.jsonl` in the schema every store shares. Rerunning wipes
the corpus file first. The sources are selected by name and bounded by `--limit` (pages
per source) or, without it, by each source's own cap.

Downloads land under `ai_tmp/duckdb-vs-sqlite/downloads/`. The Sphinx archives and the
GH Archive hours are fetched whole; the Wikipedia tarball and the Common Crawl WARC are
streamed and the bytes read are kept, so a rerun reads the cache and reaches no network.
A rerun with a larger cap than the cached stream covers stops where the cache ends.
"""

from __future__ import annotations

import argparse
import functools
import gzip
import hashlib
import io
import itertools
import json
import re
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, TypedDict

from warcio.archiveiterator import ArchiveIterator

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "ai_tmp" / "duckdb-vs-sqlite"
CORPUS = SCRATCH / "corpus.jsonl"
DOWNLOADS = SCRATCH / "downloads"

RUST_DOCS = Path.home() / ".rustup/toolchains/stable-aarch64-apple-darwin/share/doc/rust/html"
RUST_URL = "https://doc.rust-lang.org/stable/"

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
WORKER_CHUNK = 16
BATCH = 512


class Page(TypedDict):
    """One page in the shared schema; the HTML is None for Markdown-only sources."""

    identity: str
    source_url: str
    regime: str
    title: str
    raw_digest: str | None
    content_digest: str
    fetched_at: str
    html: str | None
    markdown: str
    html_bytes: int
    markdown_bytes: int


class RawPage(TypedDict):
    """A fetched page before conversion."""

    identity: str
    source_url: str
    regime: str
    html: str | None
    markdown: str | None
    title: str | None


def title_of(html: str) -> str:
    """The text of the first title element, or an empty string."""
    match = TITLE_RE.search(html)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def convert_html(html: str) -> str:
    """Throwaway HTML to Markdown conversion; the converter is not a product decision."""
    from html_to_markdown import convert  # noqa: PLC0415  imported in the worker only

    return str(convert(html).content)


def finish(raw: RawPage, fetched_at: str) -> tuple[Page, float] | None:
    """Convert one raw page and fill in the digests and sizes; the conversion seconds too.

    None when the converter rejects the page (binary data behind an HTML content type).
    """
    html = raw["html"]
    started = time.perf_counter()
    try:
        markdown = raw["markdown"] if raw["markdown"] is not None else convert_html(html or "")
    except Exception as error:  # noqa: BLE001  the converter's errors are its own; the page is dropped
        print(f"skipped {raw['identity']}: {error}", file=sys.stderr)
        return None
    seconds = time.perf_counter() - started
    html_bytes = len(html.encode()) if html is not None else 0
    markdown_bytes = len(markdown.encode())
    page = Page(
        identity=raw["identity"],
        source_url=raw["source_url"],
        regime=raw["regime"],
        title=raw["title"] if raw["title"] is not None else title_of(html or ""),
        raw_digest=hashlib.sha256(html.encode()).hexdigest() if html is not None else None,
        content_digest=hashlib.sha256(markdown.encode()).hexdigest(),
        fetched_at=fetched_at,
        html=html,
        markdown=markdown,
        html_bytes=html_bytes,
        markdown_bytes=markdown_bytes,
    )
    return page, seconds


def stride_sample(items: list[Path], limit: int | None) -> list[Path]:
    """Every n-th item of a sorted list, so a small sample spans the whole tree."""
    if limit is None or limit >= len(items):
        return items
    stride = len(items) / limit
    return [items[int(i * stride)] for i in range(limit)]


def rust_pages(limit: int | None) -> Iterator[RawPage]:
    """The Rust documentation installed under rustup: local, no download."""
    files = sorted(p for p in RUST_DOCS.rglob("*.html") if p.is_file())
    for path in stride_sample(files, limit):
        relative = path.relative_to(RUST_DOCS).as_posix()
        try:
            html = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield RawPage(
            identity=RUST_URL + relative,
            source_url=RUST_URL + relative,
            regime="rust",
            html=html,
            markdown=None,
            title=None,
        )


# (archive URL, the base URL its pages were published under, the top directory to strip)
SPHINX_ARCHIVES = [
    (
        "https://docs.python.org/3.12/archives/python-3.12-docs-html.zip",
        "https://docs.python.org/3.12/",
        "python-3.12-docs-html/",
    ),
    (
        "https://docs.python.org/3.13/archives/python-3.13-docs-html.zip",
        "https://docs.python.org/3.13/",
        "python-3.13-docs-html/",
    ),
    (
        "https://docs.python.org/3.14/archives/python-3.14-docs-html.zip",
        "https://docs.python.org/3.14/",
        "python-3.14-docs-html/",
    ),
    ("https://numpy.org/doc/2.2/numpy-html.zip", "https://numpy.org/doc/2.2/", ""),
    (
        "https://pandas.pydata.org/pandas-docs/version/2.2.3/pandas.zip",
        "https://pandas.pydata.org/pandas-docs/version/2.2.3/",
        "",
    ),
    (
        "https://docs.djangoproject.com/m/docs/django-docs-5.1-en.zip",
        "https://docs.djangoproject.com/en/5.1/",
        "",
    ),
    (
        "https://www.sqlite.org/2025/sqlite-doc-3490100.zip",
        "https://www.sqlite.org/",
        "sqlite-doc-3490100/",
    ),
]
WIKIPEDIA_RUN = "20250320"
WIKIPEDIA_URL = (
    "https://dumps.wikimedia.org/other/enterprise_html/runs/"
    f"{WIKIPEDIA_RUN}/simplewiki-NS0-{WIKIPEDIA_RUN}-ENTERPRISE-HTML.json.tar.gz"
)
COMMONCRAWL_URL = (
    "https://data.commoncrawl.org/crawl-data/CC-MAIN-2026-43/segments/1791170053823.21/warc/"
    "CC-MAIN-20261005105623-20261005135623-00000.warc.gz"
)
# Ten hours: the five first planned held 10.9k bodies, short of the 20k the corpus wants.
GHARCHIVE_HOURS = [f"https://data.gharchive.org/2026-10-01-{hour}.json.gz" for hour in range(10)]
MAX_PAGE_BYTES = 8 * 2**20  # a fetched page larger than this is an outlier, not a document
# dumps.wikimedia.org answers 403 to urllib's default agent; a named client is accepted.
USER_AGENT = "rovo-prototype-benchmark/0 (+https://github.com/BiscuitBin/rove)"


def open_url(url: str) -> IO[bytes]:
    """The response body of a GET with the named client agent."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310  fixed https URL
    return urllib.request.urlopen(request)  # type: ignore[no-any-return]  # noqa: S310  fixed https URL


def download(url: str) -> Path:
    """Fetch a whole file into the download cache once."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS / url.rsplit("/", 1)[1]
    if not target.exists():
        print(f"downloading {url}", file=sys.stderr)
        partial = target.with_suffix(target.suffix + ".part")
        with open_url(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.rename(target)
    return target


class TeeStream(io.RawIOBase):
    """A read-only stream over an HTTP response that keeps every byte read in a cache file."""

    def __init__(self, response: IO[bytes], cache: IO[bytes]) -> None:
        """Wrap the response; the cache file is written as the response is read."""
        super().__init__()
        self.response = response
        self.cache = cache

    def readable(self) -> bool:
        """Reads only."""
        return True

    def readinto(self, buffer: Any) -> int:  # noqa: ANN401  the buffer protocol has no narrower type
        """Read into the buffer and copy the same bytes to the cache."""
        data = self.response.read(len(buffer))
        buffer[: len(data)] = data
        self.cache.write(data)
        return len(data)

    def close(self) -> None:
        """Close both ends."""
        self.cache.close()
        self.response.close()
        super().close()


class StreamCache:
    """A partial download kept beside a sidecar that says how many pages it yielded.

    A rerun asking for no more pages than the sidecar records reads the cache and reaches
    no network; a larger cap streams the source again from the start.
    """

    def __init__(self, url: str) -> None:
        """Name the cache files after the URL's last path segment."""
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        self.url = url
        self.cache = DOWNLOADS / (url.rsplit("/", 1)[1] + ".partial")
        self.sidecar = self.cache.with_suffix(".partial.json")

    def covers(self, cap: int | None) -> bool:
        """Whether the cached bytes are known to hold at least `cap` pages."""
        if not self.cache.exists() or not self.sidecar.exists():
            return False
        recorded = json.loads(self.sidecar.read_text())
        return bool(recorded["complete"]) or (cap is not None and recorded["pages"] >= cap)

    def open(self, cap: int | None) -> IO[bytes]:
        """The cached stream when it covers the cap, else the live response, teed."""
        if self.covers(cap):
            print(f"reading cached partial stream {self.cache.name}", file=sys.stderr)
            return self.cache.open("rb")
        print(f"streaming {self.url}", file=sys.stderr)
        self.sidecar.unlink(missing_ok=True)
        response = open_url(self.url)
        return io.BufferedReader(TeeStream(response, self.cache.open("wb")))  # type: ignore[arg-type]  RawIOBase

    def record(self, pages: int, *, complete: bool) -> None:
        """Write the sidecar once the producer has stopped."""
        if not self.sidecar.exists():
            self.sidecar.write_text(json.dumps({"pages": pages, "complete": complete}))


def decode_body(body: bytes, content_type: str) -> str:
    """Decode with the header's charset when it names one, else UTF-8, never failing."""
    match = re.search(r"charset=\"?([\w.-]+)", content_type, re.IGNORECASE)
    for encoding in ([match.group(1)] if match else []) + ["utf-8"]:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def sphinx_pages(limit: int | None) -> Iterator[RawPage]:
    """Seven Sphinx-built documentation archives, each read in full from its zip."""
    produced = 0
    for url, base, top in SPHINX_ARCHIVES:
        with zipfile.ZipFile(download(url)) as archive:
            for name in sorted(archive.namelist()):
                if not name.endswith(".html") or not name.startswith(top) or "/_sources/" in name:
                    continue
                if limit is not None and produced >= limit:
                    return
                html = archive.read(name).decode("utf-8", errors="replace")
                identity = base + name.removeprefix(top)
                produced += 1
                yield RawPage(
                    identity=identity,
                    source_url=identity,
                    regime="sphinx",
                    html=html,
                    markdown=None,
                    title=None,
                )


def wikipedia_pages(limit: int | None) -> Iterator[RawPage]:
    """Article HTML from the Wikimedia Enterprise dump, streamed until the cap."""
    produced = 0
    cache = StreamCache(WIKIPEDIA_URL)
    try:
        with cache.open(limit) as raw, tarfile.open(fileobj=raw, mode="r|gz") as tar:
            for member in tar:
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                for line in handle:
                    if limit is not None and produced >= limit:
                        cache.record(produced, complete=False)
                        return
                    article = json.loads(line)
                    html = article.get("article_body", {}).get("html")
                    if not html or len(html) > MAX_PAGE_BYTES:
                        continue
                    produced += 1
                    yield RawPage(
                        identity=article["url"],
                        source_url=article["url"],
                        regime="wikipedia",
                        html=html,
                        markdown=None,
                        title=article.get("name"),
                    )
    except (EOFError, tarfile.ReadError, gzip.BadGzipFile) as error:
        print(f"wikipedia: cached stream ended early ({error})", file=sys.stderr)
    cache.record(produced, complete=True)


def commoncrawl_pages(limit: int | None) -> Iterator[RawPage]:
    """HTML responses from one Common Crawl WARC, streamed until the cap."""
    produced = 0
    cache = StreamCache(COMMONCRAWL_URL)
    try:
        with cache.open(limit) as raw:
            for record in ArchiveIterator(raw):
                if limit is not None and produced >= limit:
                    cache.record(produced, complete=False)
                    return
                if record.rec_type != "response" or record.http_headers is None:
                    continue
                content_type = record.http_headers.get_header("Content-Type") or ""
                if record.http_headers.get_statuscode() != "200" or "html" not in content_type:
                    continue
                body = record.content_stream().read()
                if not body or len(body) > MAX_PAGE_BYTES or b"<" not in body[:2048]:
                    continue
                url = record.rec_headers.get_header("WARC-Target-URI")
                produced += 1
                yield RawPage(
                    identity=url,
                    source_url=url,
                    regime="commoncrawl",
                    html=decode_body(body, content_type),
                    markdown=None,
                    title=None,
                )
    except (EOFError, gzip.BadGzipFile) as error:
        print(f"commoncrawl: cached stream ended early ({error})", file=sys.stderr)
    cache.record(produced, complete=True)


def github_pages(limit: int | None) -> Iterator[RawPage]:
    """Issue and comment bodies from GH Archive: Markdown only, no HTML."""
    produced = 0
    for url in GHARCHIVE_HOURS:
        with gzip.open(download(url), "rt", encoding="utf-8") as hour:
            for line in hour:
                if limit is not None and produced >= limit:
                    return
                event = json.loads(line)
                payload = event.get("payload", {})
                if event.get("type") == "IssuesEvent" and payload.get("action") == "opened":
                    item = payload["issue"]
                    title = item.get("title")
                elif (
                    event.get("type") == "IssueCommentEvent" and payload.get("action") == "created"
                ):
                    item = payload["comment"]
                    title = payload.get("issue", {}).get("title")
                else:
                    continue
                body = item.get("body")
                if not body:
                    continue
                produced += 1
                yield RawPage(
                    identity=item["html_url"],
                    source_url=item["html_url"],
                    regime="github",
                    html=None,
                    markdown=body,
                    title=title,
                )


# Each source, with the cap a build without --limit uses (None reads the whole source).
SOURCES: dict[str, tuple[Callable[[int | None], Iterator[RawPage]], int | None]] = {
    "rust": (rust_pages, None),
    "sphinx": (sphinx_pages, None),
    "wikipedia": (wikipedia_pages, 30_000),
    "commoncrawl": (commoncrawl_pages, 10_000),
    "github": (github_pages, 20_000),
}


def build(sources: list[str], limit: int | None, workers: int) -> None:
    """Stream every selected source through the pool and write the corpus."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    CORPUS.unlink(missing_ok=True)
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    seen: set[str] = set()
    converted = 0
    convert_seconds = 0.0
    wall_seconds = 0.0
    finish_at = functools.partial(finish, fetched_at=fetched_at)
    with CORPUS.open("w", encoding="utf-8") as out, ProcessPoolExecutor(workers) as pool:
        for name in sources:
            producer, cap = SOURCES[name]
            raw_pages: Iterable[RawPage] = producer(limit if limit is not None else cap)
            started = time.perf_counter()
            # Batches bound the raw HTML held in memory: map submits its whole input at once.
            for batch in itertools.batched(raw_pages, BATCH, strict=False):
                for finished in pool.map(finish_at, batch, chunksize=WORKER_CHUNK):
                    if finished is None:
                        continue
                    page, seconds = finished
                    # GH Archive repeats the odd event across hours; identity is the key.
                    if page["identity"] in seen:
                        continue
                    seen.add(page["identity"])
                    out.write(json.dumps(page, ensure_ascii=False) + "\n")
                    counts[name] = counts.get(name, 0) + 1
                    if page["html"] is not None:
                        converted += 1
                        convert_seconds += seconds
            wall_seconds += time.perf_counter() - started
            print(f"{name}: {counts.get(name, 0)} pages", file=sys.stderr)
    size = CORPUS.stat().st_size
    print(f"corpus: {sum(counts.values())} pages, {size / 2**20:.1f} MiB at {CORPUS}")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    if converted:
        print(
            f"conversion: {converted} pages, {convert_seconds:.1f} worker-seconds"
            f" ({converted / convert_seconds:.0f} pages/s per worker);"
            f" {wall_seconds:.1f} s wall including source I/O with {workers} workers"
            f" ({converted / wall_seconds:.0f} pages/s)"
        )


def main() -> None:
    """Parse the arguments and build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="rust", help="comma-separated: " + ",".join(SOURCES))
    parser.add_argument(
        "--limit", type=int, default=None, help="pages per source (else each source's cap)"
    )
    parser.add_argument("--workers", type=int, default=8, help="conversion processes")
    args = parser.parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        parser.error(f"unknown sources: {', '.join(unknown)}")
    build(sources, args.limit, args.workers)


if __name__ == "__main__":
    main()
