"""PROTOTYPE command line: `scrapyproto vm up|status|down|destroy`, `crawl`, `load`, `runs` and `sql`."""

import json
import secrets
import time
from pathlib import Path
from typing import Annotated, Any, NoReturn

import duckdb
import typer
from smol import Machine, SmolError

from scrapyproto import crawl as c, machine as m, state, store

app = typer.Typer(name="scrapyproto", no_args_is_help=True, add_completion=False)
vm = typer.Typer(no_args_is_help=True)
app.add_typer(vm, name="vm", help="Drive the Scrapy microVM across invocations.")

StateDir = Annotated[Path | None, typer.Option("--state-dir", help="Where state.json lives.")]
Db = Annotated[Path, typer.Option("--db", help="The DuckDB store.")]
FeedsDir = Annotated[Path, typer.Option("--feeds-dir", help="Where pulled feeds and run manifests live.")]

NOT_OURS = (
    f"{m.MACHINE_NAME} exists but no state file here records this machine (another checkout's?); "
    "nothing touched; `scrapyproto vm destroy` deletes it"
)


@app.callback()
def main() -> None:
    """PROTOTYPE: Scrapy in a smol microVM, pages in DuckDB. Throwaway."""


def _one_line(reason: object) -> str:
    return " ".join(str(reason).split())


def _finish(state_dir: Path | None, *, failing: bool = False) -> None:
    """Print the state block, read afresh by name; an error in any field is a failed command."""
    try:
        block = m.state_block(m.open_existing(), state_dir=state_dir)
    except SmolError as exc:
        block = m.state_block(None, _one_line(exc), state_dir)
    fields = [line.split(":", 1)[-1].strip() for line in block.splitlines()]
    errors = [field for field in fields if field.startswith("error:")]
    if errors and not failing:
        typer.echo(_one_line(errors[0]), err=True)
    typer.echo("---- state ----")
    typer.echo(block)
    if errors or failing:
        raise typer.Exit(1)


def _fail(reason: object, state_dir: Path | None) -> NoReturn:
    """Report a failed vm command: the reason, the state block as far as it is known, exit 1."""
    typer.echo(f"error: {_one_line(reason)}", err=True)
    _finish(state_dir, failing=True)
    raise typer.Exit(1)


def _open_or_fail(state_dir: Path | None) -> Machine | None:
    """The named machine without starting it, or None; a failure still ends with the state block."""
    try:
        return m.open_existing()
    except SmolError as exc:
        _fail(f"cannot open machine: {exc}", state_dir)


def _create(state_dir: Path | None) -> None:
    """First create: boot, claim the name in the state file, install Scrapy. Reaches the network."""
    typer.echo(f"creating {m.MACHINE_NAME} from {m.IMAGE} (image pull and pip install: network)")
    t0 = time.monotonic()
    generation = secrets.token_hex(16)
    mach = m.create(generation)
    # Only after create returns: a create that failed or lost the name claims nothing.
    saved: dict[str, Any] = {
        "machine": m.MACHINE_NAME,
        "generation": generation,
        "image": m.IMAGE,
        "scrapy": m.SCRAPY_VERSION,
        "rung": None,
    }
    state.save(saved, state_dir)
    typer.echo(f"[time] create to {mach.state()}: {time.monotonic() - t0:.2f}s")
    t0 = time.monotonic()
    m.install_scrapy(mach)
    typer.echo(f"[time] pip install: {time.monotonic() - t0:.2f}s")
    _require_pin(mach)
    state.save({**saved, "rung": "1: python:3.12 plus pip install"}, state_dir)


def _reconnect(state_dir: Path | None, was: str) -> None:
    """Start or reattach, then check Scrapy with `exec`. Never installs: that is first create only."""
    typer.echo(f"{m.MACHINE_NAME} exists ({was}); connecting")
    t0 = time.monotonic()
    mach = m.connect_existing(state_dir)
    now = mach.state()
    typer.echo(f"[time] {was} to {now}: {time.monotonic() - t0:.2f}s")
    if now != "running":
        msg = f"{m.MACHINE_NAME} is {now} after connect, not running"
        raise RuntimeError(msg)
    t0 = time.monotonic()
    _require_pin(mach)
    typer.echo(f"[time] scrapy check, no pip run: {time.monotonic() - t0:.2f}s")


def _require_pin(mach: Machine) -> None:
    """The guest must report the pin: a lost installation fails here rather than being repaired."""
    try:
        version = m.scrapy_version(mach)
    except RuntimeError as exc:
        msg = f"scrapy check failed: {exc}; `vm up` installs on first create only, so `vm destroy` then `vm up`"
        raise RuntimeError(msg) from exc
    if version != m.SCRAPY_VERSION:
        msg = f"guest has scrapy {version}, the pin is {m.SCRAPY_VERSION}"
        raise RuntimeError(msg)


@vm.command("up")
def vm_up(state_dir: StateDir = None) -> None:
    """Create the machine, or reconnect to it; idempotent, never deletes."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    if mach is not None and not m.owned(saved):
        # The registry is host-global but the state file is per checkout: report, never delete.
        _fail(NOT_OURS, state_dir)
    try:
        if mach is None:
            _create(state_dir)
        else:
            _reconnect(state_dir, mach.state())
    except (SmolError, RuntimeError, OSError) as exc:
        _fail(exc, state_dir)
    _finish(state_dir)


@vm.command("status")
def vm_status(state_dir: StateDir = None) -> None:
    """Reopen the machine by name, without starting it, and print the state."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    try:
        if mach is not None:
            mach.state()
    except SmolError as exc:
        _fail(exc, state_dir)
    if mach is not None and not m.owned(saved):
        typer.echo(NOT_OURS)
    _finish(state_dir)


@vm.command("down")
def vm_down(state_dir: StateDir = None) -> None:
    """Stop the machine; its disk stays. A stop kills whatever is running in the guest."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    if mach is not None and not m.owned(saved):
        # A stop kills whatever runs in the guest, maybe another checkout's: report, never stop.
        _fail(NOT_OURS, state_dir)
    try:
        if mach is None:
            typer.echo("no machine to stop")
        elif mach.state() == "stopped":
            typer.echo("already stopped")
        else:
            t0 = time.monotonic()
            mach.stop()
            typer.echo(f"[time] stop: {time.monotonic() - t0:.2f}s")
    except SmolError as exc:
        _fail(exc, state_dir)
    _finish(state_dir)


@vm.command("install-duckdb")
def vm_install_duckdb(state_dir: StateDir = None) -> None:
    """Ticket 05: pip-install the host's DuckDB pin in the guest (network), for `crawl --store per-item`."""
    mach = _running_or_fail(state_dir)
    try:
        before = m.duckdb_version(mach)
        typer.echo(f"guest duckdb before: {before or 'none'}")
        if before != m.DUCKDB_VERSION:
            t0 = time.monotonic()
            typer.echo(m.install_duckdb(mach))
            typer.echo(f"[time] pip install duckdb=={m.DUCKDB_VERSION}: {time.monotonic() - t0:.2f}s")
        after = m.duckdb_version(mach)
        typer.echo(f"guest duckdb after: {after or 'none'}")
    except (SmolError, RuntimeError) as exc:
        _fail(exc, state_dir)
    # Outside the try: typer.Exit is a RuntimeError, so a _fail inside it would report twice.
    if after != m.DUCKDB_VERSION:
        _fail(f"guest duckdb is {after}, the pin is {m.DUCKDB_VERSION}", state_dir)
    _finish(state_dir)


@vm.command("destroy")
def vm_destroy(state_dir: StateDir = None) -> None:
    """Delete the machine and its disk, and remove the state file; works with no state file."""
    mach = _open_or_fail(state_dir)
    try:
        if mach is None:
            typer.echo("no machine to delete")
        else:
            mach.delete()
            typer.echo("deleted")
        state.clear(state_dir)
        typer.echo(f"state file removed: {state.path(state_dir)}")
        typer.echo(f"registry: {[s.name for s in Machine.list(m.LOCAL)]}")
    except (SmolError, OSError) as exc:
        _fail(exc, state_dir)
    _finish(state_dir)


# ---- ticket 03: crawl, load, runs, sql ------------------------------------------------------------

OK_REASONS = {"finished", "closespider_itemcount", "closespider_pagecount"}
STAT_PREFIXES = (
    "proto/", "httpcache/", "robotstxt/", "offsite/", "retry/", "downloader/request_count",
    "downloader/response_count", "downloader/response_status_count", "downloader/exception_count",
    "item_scraped_count", "response_received_count", "finish_reason", "elapsed_time_seconds", "log_count/ERROR",
    "memusage/",
)
LOG_TAIL = 30


def _running_or_fail(state_dir: Path | None) -> Machine:
    """Attach only to this checkout's machine, already running; otherwise exit 1 before any request."""
    saved = state.load(state_dir)
    mach = _open_or_fail(state_dir)
    if mach is None:
        _fail(f"no machine {m.MACHINE_NAME}; run `scrapyproto vm up` first. Nothing was requested.", state_dir)
    if not m.owned(saved):
        _fail(NOT_OURS, state_dir)
    try:
        now = mach.state()
    except SmolError as exc:
        _fail(exc, state_dir)
    if now != "running":
        _fail(f"{m.MACHINE_NAME} is {now}; run `scrapyproto vm up` first. Nothing was requested.", state_dir)
    try:
        # Running and owned: this attaches without a boot (a stop landing in between is the README's limit).
        return m.connect_existing(state_dir)
    except (SmolError, RuntimeError) as exc:
        _fail(exc, state_dir)


def _count(stats: dict[str, object], key: str) -> int:
    """A per-item store counter from the guest's stats, or -1 when it is absent or not an int."""
    value = stats.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _print_stats(stats: dict[str, object]) -> None:
    typer.echo("---- scrapy stats (selected) ----")
    for key in sorted(stats):
        if key.startswith(STAT_PREFIXES):
            typer.echo(f"{key}: {stats[key]}")


def _host_paths(feeds_dir: Path, run_id: str) -> dict[str, Path]:
    return {kind: feeds_dir / f"{run_id}.{kind}" for kind in ("jsonl", "run.json", "stats.json", "log")}


@app.command("crawl")
def crawl_cmd(  # noqa: PLR0913, PLR0917  the ticket's flags
    start_url: Annotated[list[str], typer.Option("--start-url", help="A seed URL; repeatable.")],
    max_pages: Annotated[int, typer.Option("--max-pages", help="Pages to fetch at most, enforced by the spider.")],
    allowed_host: Annotated[
        list[str] | None, typer.Option("--allowed-host", help="Exact host to stay on; default the seeds' hosts."),
    ] = None,
    path_prefix: Annotated[
        list[str] | None,
        typer.Option("--path-prefix", help="In scope only when the path starts with one; repeatable. "
            "Default: the first seed's directory."),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option("--include", help="Glob, or regex when prefixed re:; when any is given a URL must match "
            "one; repeatable."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", help="Glob, or regex when prefixed re:; a match keeps the URL out; repeatable."),
    ] = None,
    max_depth: Annotated[int, typer.Option("--max-depth", help="Links beyond this depth are not followed.")] = (
        c.MAX_DEPTH
    ),
    keep_query_param: Annotated[
        list[str] | None,
        typer.Option("--keep-query-param", help="A query parameter kept in the page identity; repeatable. "
            "Every other one is dropped before scope and dedup."),
    ] = None,
    delay: Annotated[
        float, typer.Option("--delay", help="Seconds between downloads; the default is the floor."),
    ] = c.DOWNLOAD_DELAY_S,
    concurrency: Annotated[int, typer.Option("--concurrency", help="Requests at once.")] = c.CONCURRENCY,
    user_agent: Annotated[str, typer.Option("--user-agent", help="The User-Agent header.")] = c.USER_AGENT,
    replay: Annotated[
        bool, typer.Option("--replay", help="Serve from the guest's HTTP cache; drop anything not in it."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the resolved scope and settings, and exit; no machine call."),
    ] = False,
    render: Annotated[
        bool, typer.Option("--render", help="Print what would run in the guest, and exit; no machine call."),
    ] = False,
    store_kind: Annotated[
        str, typer.Option("--store", help="bulk: load the feed on the host after the run. per-item: the item "
            "pipeline writes each page into a DuckDB file on the guest, pulled back afterwards."),
    ] = "bulk",
    state_dir: StateDir = None,
    db: Db = store.DEFAULT_DB,
    feeds_dir: FeedsDir = store.FEEDS_DIR,
) -> None:
    """Crawl from the seeds inside the guest, pull the feed, bulk-load it into DuckDB, print the summary.
    With --store per-item, the spider writes DuckDB itself and the host pulls that file back instead."""
    try:
        p = c.plan(
            c.new_run_id(), start_url, allowed_host or [], max_pages, replay=replay,
            path_prefixes=path_prefix, include=include, exclude=exclude, max_depth=max_depth,
            keep_query_params=keep_query_param, delay=delay, concurrency=concurrency, user_agent=user_agent,
            store=store_kind,
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if dry_run:
        typer.echo(c.dry_run(p))
        return
    if render:
        typer.echo(c.render(p))
        return
    mach = _running_or_fail(state_dir)
    typer.echo(f"[crawl] run {p.run_id}: {p.start_urls}, hosts {p.allowed_hosts}, max {p.max_pages} pages"
        + (", replay from the guest cache" if p.replay else "") + f", store {p.store}")
    if p.store == "per-item":
        try:
            found = m.duckdb_version(mach)
        except (SmolError, RuntimeError) as exc:
            _fail(exc, state_dir)
        # Outside the try: typer.Exit is a RuntimeError, so a _fail inside it would report twice.
        if found != m.DUCKDB_VERSION:
            _fail(f"the guest has duckdb {found}, the pin is {m.DUCKDB_VERSION}; run "
                "`scrapyproto vm install-duckdb` (network). Nothing was requested.", state_dir)
    try:
        c.prepare(mach, p)
        typer.echo(f"[crawl] lock: {c.acquire(mach, p)}")
        try:
            pid = c.launch(mach, p)
        except BaseException:
            c.release(mach, p)
            raise
        typer.echo(f"[crawl] started in the guest with background=True (pid {pid}); log {p.run_dir}/crawl.log")
        t_launched = time.monotonic()
        outcome = c.watch(mach, p, typer.echo)
        t_done = time.monotonic()
        outcome = c.collect(mach, p, outcome)
        if outcome.exit_code is None:
            # The wrapper died before its own release; free the lock only if it still names this run.
            c.release(mach, p)
    except SmolError as exc:
        _fail(f"lost the machine during run {p.run_id} (stopped by another process?): {exc}", state_dir)
    except RuntimeError as exc:
        _fail(exc, state_dir)
    close_reason = str(outcome.stats.get("proto/close_reason", "unknown"))
    wall = (
        outcome.finished_epoch - outcome.started_epoch
        if outcome.started_epoch is not None and outcome.finished_epoch is not None
        else None
    )
    manifest = {
        "run_id": p.run_id,
        "start_urls": p.start_urls,
        "scope": p.scope(),
        "started_epoch": outcome.started_epoch,
        "finished_epoch": outcome.finished_epoch,
        "wall_seconds": wall,
        "exit_code": outcome.exit_code,
        "close_reason": close_reason,
        "outcome": outcome.why,
        "guest_run_dir": p.run_dir,
    }
    paths = _host_paths(feeds_dir, p.run_id)
    # The manifest lands first: a feed on the host always has one, so `scrapyproto load` can recover it.
    store.write_atomic(paths["run.json"], json.dumps(manifest, indent=1).encode())
    if outcome.feed is not None:
        store.write_atomic(paths["jsonl"], outcome.feed)
    store.write_atomic(paths["stats.json"], json.dumps(outcome.stats, indent=1, sort_keys=True).encode())
    store.write_atomic(paths["log"], outcome.log)
    typer.echo(f"[crawl] {outcome.why}; close reason {close_reason}; wall "
        + (f"{wall:.1f}s" if wall is not None else "unknown"))
    typer.echo(f"[crawl] pulled to {feeds_dir}: feed " + ("yes" if outcome.feed is not None else "NONE")
        + ", stats, log, run manifest")
    _print_stats(outcome.stats)
    per_item = p.store == "per-item"
    st = outcome.stats
    # Every page the spider emitted is a row inserted or an intentional duplicate, and no insert failed.
    lost = per_item and (
        _count(st, "proto/store/insert_failed") != 0
        or _count(st, "proto/pages")
        != _count(st, "proto/store/rows_inserted") + _count(st, "proto/store/duplicates_ignored")
        or _count(st, "proto/store/rows") != _count(st, "proto/store/rows_inserted")
    )
    unstored = (st.get("proto/store/closed") != 1 or lost) if per_item else outcome.feed is None
    if outcome.exit_code != 0 or close_reason not in OK_REASONS or unstored:
        tail = outcome.log.decode("utf-8", "replace").splitlines()[-LOG_TAIL:]
        typer.echo(f"---- last {len(tail)} lines of crawl.log ----")
        typer.echo("\n".join(tail))
        if per_item:
            if lost:
                hint = (
                    f"the per-item store lost pages (insert_failed {_count(st, 'proto/store/insert_failed')}, "
                    f"pages {_count(st, 'proto/pages')}, inserted {_count(st, 'proto/store/rows_inserted')}, "
                    f"duplicates {_count(st, 'proto/store/duplicates_ignored')}); {p.guest_db} not pulled"
                )
            else:
                hint = f"the per-item store was not closed (stats proto/store/closed absent); {p.guest_db} not pulled"
        else:
            hint = f"`scrapyproto load {p.run_id}` loads it" if outcome.feed is not None else "there is no feed"
        _fail(f"the spider did not finish cleanly ({outcome.why}, {close_reason}); not loaded, {hint}", state_dir)
    if per_item:
        pulled = db.parent / f"{p.run_id}-per-item.duckdb"
        try:
            data, listing = c.pull_store(mach, p)
            typer.echo(f"[pull] guest run directory before the pull (no {c.GUEST_DB_FILE}.wal):")
            typer.echo(listing.rstrip())
            store.write_atomic(pulled, data)
            typer.echo(f"[pull] {p.guest_db} -> {pulled}: {len(data)} bytes, the guest's size")
            pages = store.record_per_item(db, manifest, pulled)
        except SmolError as exc:
            _fail(f"lost the machine pulling {p.guest_db}: {exc}", state_dir)
        except (RuntimeError, store.FeedError, duckdb.Error, OSError) as exc:
            _fail(f"per-item store not recorded: {exc}", state_dir)
        typer.echo(f"[record] runs row for {p.run_id} (store per-item, {pages} pages) in {db}")
        summary = store.summary(db, p.run_id, pulled)
    else:
        try:
            pages, check = store.load(db, manifest, paths["jsonl"])
        except (store.FeedError, duckdb.Error, OSError) as exc:
            _fail(f"load failed, nothing written to the store: {exc}", state_dir)
        _print_load(check, pages)
        summary = store.summary(db, p.run_id)
    typer.echo("---- summary (read back from DuckDB) ----")
    typer.echo(summary)
    t_summary = time.monotonic()
    typer.echo(f"[time] host: launch to done marker seen {t_done - t_launched:.2f}s (polled every "
        f"{c.POLL_EVERY_S:.0f}s); done marker seen to summary printed {t_summary - t_done:.2f}s")
    _finish(state_dir)


def _print_load(check: store.FeedCheck, pages: int) -> None:
    typer.echo(f"[load] feed lines {check.lines}, unique URLs {check.unique_urls}, loaded {pages}")
    if check.duplicate_urls:
        typer.echo(f"[load] {len(check.duplicate_urls)} duplicate URL lines dropped (earliest fetch kept): "
            + ", ".join(check.duplicate_urls[:5]))


@app.command("load")
def load_cmd(run_id: str, db: Db = store.DEFAULT_DB, feeds_dir: FeedsDir = store.FEEDS_DIR) -> None:
    """Bulk-load a pulled feed and its run manifest; for a crawl whose load did not happen."""
    paths = _host_paths(feeds_dir, run_id)
    try:
        manifest = json.loads(paths["run.json"].read_text())
        pages, check = store.load(db, manifest, paths["jsonl"])
    except (store.FeedError, duckdb.Error, OSError, ValueError, KeyError) as exc:
        typer.echo(f"error: load failed, nothing written to the store: {_one_line(exc)}", err=True)
        raise typer.Exit(1) from exc
    _print_load(check, pages)
    typer.echo("---- summary (read back from DuckDB) ----")
    typer.echo(store.summary(db, run_id))


@app.command("runs")
def runs_cmd(db: Db = store.DEFAULT_DB) -> None:
    """List the runs table."""
    try:
        typer.echo(store.runs(db))
    except (duckdb.Error, OSError) as exc:
        typer.echo(f"error: {_one_line(exc)}", err=True)
        raise typer.Exit(1) from exc


@app.command("sql")
def sql_cmd(query: str, db: Db = store.DEFAULT_DB) -> None:
    """Print a query's result; the store is opened read-only."""
    try:
        typer.echo(store.sql(db, query))
    except (duckdb.Error, OSError) as exc:
        typer.echo(f"error: {_one_line(exc)}", err=True)
        raise typer.Exit(1) from exc
