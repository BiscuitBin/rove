"""End to end: an owner run's redirected answer is judged by the host that answered (T20).

crawl.allium at fc9ad9f (FetchAttempt.answering_host_name, RetireHostOnLongRetryAfter):
the owned host's seed redirects to an allowed but unselected host, which answers 429
with a Retry-After past the cap. That host, under the standard policy, is retired; the
owned host is not. The two hosts are two names for the loopback interface: the owned
site is served as 127.0.0.1, the other as localhost, so they are distinct host names
(a port alone never makes one). The other host's start URL is a page its robots.txt
disallows, so every sync knows its origin and the baseline reads only its robots.txt.
Owner testing has no command-line spelling (rovo.allium open question 1138): rovo init
runs through CliRunner, the syncs and save_ownership in process over the real
HttpxFetcher on a SteppingTimer, which never sleeps. Not `test_answering_host.py`, which
the unit suite already names.
"""

import json
from pathlib import Path

from conftest import Answer, SiteServer
from test_init_sync import load
from typer.testing import CliRunner

from fakes import SteppingTimer
from rovo import _commands
from rovo._crawl.fetch import Fetcher, HttpxFetcher
from rovo._crawl.model import CONFIG, OwnerTestOptions, PolitenessControl
from rovo._exit import ExitCode
from rovo._mirror.model import Tier
from rovo.cli import app

SEED_PATH = "/guide/start.html"
PRIVATE_PATH = "/guide/private.html"
ROBOTS_PATH = "/robots.txt"
LOOPBACK = "127.0.0.1"
OTHER_NAME = "localhost"
BASELINE = 1
PAST_CAP = int(CONFIG.retry_after_cap.total_seconds()) + 1
TOO_MANY = 429
MOVED_PERMANENTLY = 301
OTHER_ROBOTS = f"User-agent: *\nDisallow: {PRIVATE_PATH}\n"


def never_installed(tier: Tier) -> bool:
    """No engine beyond http is installed."""
    del tier
    return False


def sync(out: Path, fetcher: Fetcher, **options: object) -> ExitCode:
    """One rovo sync in process over `fetcher`, on a SteppingTimer."""
    return _commands.sync(
        out,
        fetcher=fetcher,
        clock=SteppingTimer(),
        tier_installed=never_installed,
        **options,  # type: ignore[arg-type]  # The sync's options, by name.
    )


def set_key(out: Path, key: str, value: object) -> None:
    """Set rovo.toml's one `key = ...` line to `value`, before the baseline is taken."""
    path = out / "rovo.toml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(f"{key} = ")]
    assert len(matches) == 1, key
    lines[matches[0]] = f"{key} = {json.dumps(value)}\n"
    path.write_text("".join(lines), encoding="utf-8")


def test_a_redirected_retry_after_past_the_cap_retires_the_host_that_answered(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """Owned 127.0.0.1 redirects to unselected localhost, which answers 429 past the cap.

    The baseline (robots.txt disallows both start URLs) leaves them unresolved and asks
    the other host for its robots.txt and discovery files, never a page. The owner run,
    robots disabled on 127.0.0.1 alone, follows up its seed only and follows the seed's
    redirect: localhost's robots.txt allows the target under the standard policy, its
    page answers 429 with a Retry-After past retry_after_cap, once, and localhost is
    retired (its breaker tripped, the Retry-After counted on it), while 127.0.0.1 keeps
    a watching breaker and the page's tier. The sync exits blocked.
    """
    other = serve_site(
        "one-page",
        always={
            ROBOTS_PATH: Answer(200, {}, OTHER_ROBOTS),
            SEED_PATH: Answer(TOO_MANY, {"Retry-After": str(PAST_CAP)}),
        },
    )
    other_base = other.replace(LOOPBACK, OTHER_NAME)
    base = serve_site(
        "robots-disallow",
        always={
            SEED_PATH: Answer(MOVED_PERMANENTLY, {"Location": f"{other_base}guide/start.html"})
        },
    )
    out = tmp_path / "out"
    seed = f"{base}guide/start.html"
    result = CliRunner().invoke(app, ["init", seed, str(out)])
    assert result.exit_code == 0, result.output
    set_key(out, "allowed_hosts", [LOOPBACK, OTHER_NAME])
    set_key(out, "start_urls", [seed, f"{other_base}guide/private.html"])
    with HttpxFetcher() as fetcher:
        assert sync(out, fetcher) is ExitCode.ok
    assert SEED_PATH not in serve_site.paths(base)
    assert ROBOTS_PATH in serve_site.paths(other)
    assert not {SEED_PATH, PRIVATE_PATH} & set(serve_site.paths(other))
    assert _commands.save_ownership(out, [LOOPBACK]) is ExitCode.ok
    options = OwnerTestOptions(
        preceding_run_id=BASELINE,
        hosts=frozenset({LOOPBACK}),
        disabled_controls=frozenset({PolitenessControl.robots}),
    )
    with HttpxFetcher() as fetcher:
        code = sync(out, fetcher, owner_test=options)
    assert code is ExitCode.blocked
    assert serve_site.paths(base).count(SEED_PATH) == 1
    assert serve_site.paths(other).count(SEED_PATH) == 1
    assert PRIVATE_PATH not in serve_site.paths(other)
    data = load(out / "crawl-report.json")
    assert data["mode"] == "owner_testing"
    rows = data["per_host"]
    assert isinstance(rows, list)
    by_host = {row["host"]: row for row in rows}
    assert by_host[OTHER_NAME]["breaker_tripped"] is True
    assert by_host[OTHER_NAME]["retry_after_honored"] == 1
    assert by_host[OTHER_NAME]["robots_ignored"] is False
    assert by_host[LOOPBACK]["breaker_tripped"] is False
    assert by_host[LOOPBACK]["retry_after_honored"] == 0
    assert by_host[LOOPBACK]["robots_ignored"] is True
    assert by_host[LOOPBACK]["tiers_used"] == ["http"]
