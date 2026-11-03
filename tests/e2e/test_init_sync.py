"""End to end: rovo init then rovo sync against a fixture site served on 127.0.0.1.

The path runs the installed `rovo` script beside this interpreter, out of process; the
robots and guard scenarios run in process through CliRunner. Neither reaches the network:
every site is a directory under tests/fixtures/sites served by `serve_site`.
"""

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from typer.testing import CliRunner

from rovo.cli import app

USAGE = 2
TIMEOUT = 120
ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# Keys every page file carries (mirror.allium PageFileProvenance).
REQUIRED_KEYS = {
    "source_url",
    "title",
    "content_digest",
    "quality_score",
    "low_confidence",
    "quality_flags",
    "tier",
    "method",
    "profile",
    "keywords",
}
# A URL that is never contacted: init makes no request.
UNUSED_URL = "http://127.0.0.1:9/guide/start.html"


def rovo(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the installed rovo script with `args`, without a shell."""
    script = shutil.which("rovo", path=str(Path(sys.executable).parent))
    assert script is not None, f"no rovo console script beside {sys.executable}"
    return subprocess.run(
        [script, *args], capture_output=True, text=True, check=False, timeout=TIMEOUT
    )


def split_page(text: str) -> tuple[dict[str, str], str]:
    """A page file's frontmatter lines, key to raw value, and its body."""
    assert text.startswith("---\n")
    head, separator, body = text[len("---\n") :].partition("\n---\n")
    assert separator
    lines = head.splitlines()
    keys = [line.split(":", 1)[0] for line in lines]
    assert keys == sorted(keys), keys
    return {
        key: line.split(":", 1)[1].strip() for key, line in zip(keys, lines, strict=True)
    }, body


def page_root(base: str) -> str:
    """pages/<host segment>/ for the fixture server: 127.0.0.1 and its port as _<port>.

    mirror.allium, MovePage guidance at fed9ed8: the host segment appends a non-default
    port as "_<port>", since ":" is illegal on Windows.
    """
    parts = urlsplit(base)
    assert parts.hostname == "127.0.0.1"
    assert parts.port is not None
    return f"pages/127.0.0.1_{parts.port}/"


def markdown_files(out: Path) -> list[str]:
    """Every Markdown file in the mirror, mirror-relative."""
    return sorted(path.relative_to(out).as_posix() for path in out.rglob("*.md"))


def load(path: Path) -> dict[str, object]:
    """A JSON object from a file."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_init_then_sync_mirrors_the_seed_page(
    serve_site: Callable[[str], str], tmp_path: Path
) -> None:
    """The installed rovo inits a mirror and syncs the seed page into pages/<host>/start.md."""
    base = serve_site("one-page")
    seed = f"{base}guide/start.html"
    out = tmp_path / "out"

    init = rovo("init", seed, str(out))
    assert init.returncode == 0, init.stderr
    assert (out / "rovo.toml").is_file()
    assert (out / ".rovo" / "manifest.json").is_file()
    assert markdown_files(out) == []

    sync = rovo("sync", str(out))
    assert sync.returncode == 0, sync.stderr
    start_path = f"{page_root(base)}start.md"
    # The page lies in its host's namespace, never beside the managed root files.
    assert markdown_files(out) == [start_path]
    text = (out / start_path).read_text(encoding="utf-8")
    frontmatter, body = split_page(text)
    assert set(frontmatter) >= REQUIRED_KEYS
    assert json.loads(frontmatter["source_url"]) == seed
    assert json.loads(frontmatter["title"]) == "Getting started"
    assert frontmatter["low_confidence"] == "false"
    assert json.loads(frontmatter["tier"]) == "http"
    assert json.loads(frontmatter["method"]) == "profile"
    assert json.loads(frontmatter["profile"]) == "generic"
    assert not any(ISO_TIMESTAMP.search(line) for line in text.splitlines())
    # Positive control: the same matcher finds the fetch times the manifest keeps.
    assert ISO_TIMESTAMP.search((out / ".rovo" / "manifest.json").read_text(encoding="utf-8"))
    body_lines = body.splitlines()
    assert [line for line in body_lines if line.startswith("# ")] == ["# Getting started"]
    assert any(line.startswith("## Install the product") for line in body_lines)

    report = load(out / "crawl-report.json")
    assert report["report_status"] == "finished"
    assert report["exit_code"] == "ok"
    assert report["run_id"] == 1
    assert report["kind"] == "initial"
    assert report["fetched"] == 1
    assert report["converted"] == 1
    assert report["changes"] == [
        {"kind": "added", "url": seed, "path": start_path, "moved_from": None}
    ]


def test_robots_disallow_skips_the_seed(serve_site: Callable[[str], str], tmp_path: Path) -> None:
    """A robots.txt disallowing /guide/: the sync exits 0, writes no page, skips the row."""
    base = serve_site("robots-disallow")
    seed = f"{base}guide/start.html"
    out = tmp_path / "out"
    runner = CliRunner()

    assert runner.invoke(app, ["init", seed, str(out)]).exit_code == 0
    result = runner.invoke(app, ["sync", str(out)])
    assert result.exit_code == 0, result.output
    assert list(out.rglob("*.md")) == []
    frontier = load(out / ".rovo" / "frontier.json")
    entries = frontier["entries"]
    assert isinstance(entries, list)
    assert [(row["identity"], row["status"]) for row in entries] == [(seed, "skipped_robots")]
    report = load(out / "crawl-report.json")
    assert report["fetched"] == 0
    assert report["converted"] == 0


def test_sync_without_a_mirror_is_refused(tmp_path: Path) -> None:
    """Rovo sync on a directory with no manifest exits 2 and writes no report."""
    result = CliRunner().invoke(app, ["sync", str(tmp_path)])
    assert result.exit_code == USAGE
    assert "No such command" not in result.output  # refused by sync, not by the parser
    assert not (tmp_path / "crawl-report.json").exists()


def test_init_over_a_mirror_is_refused(tmp_path: Path) -> None:
    """Rovo init over an existing mirror exits 2 and leaves rovo.toml byte-identical."""
    out = tmp_path / "out"
    runner = CliRunner()
    assert runner.invoke(app, ["init", UNUSED_URL, str(out)]).exit_code == 0
    before = (out / "rovo.toml").read_bytes()
    assert runner.invoke(app, ["init", UNUSED_URL, str(out)]).exit_code == USAGE
    assert (out / "rovo.toml").read_bytes() == before


def test_an_unparsable_manifest_is_never_overwritten(tmp_path: Path) -> None:
    """Over invalid manifest JSON, init and sync both exit 2 and change nothing."""
    out = tmp_path / "out"
    runner = CliRunner()
    assert runner.invoke(app, ["init", UNUSED_URL, str(out)]).exit_code == 0
    manifest = out / ".rovo" / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    toml_before = (out / "rovo.toml").read_bytes()

    assert runner.invoke(app, ["init", UNUSED_URL, str(out)]).exit_code == USAGE
    assert (out / "rovo.toml").read_bytes() == toml_before
    assert manifest.read_text(encoding="utf-8") == "{not json"

    assert runner.invoke(app, ["sync", str(out)]).exit_code == USAGE
    assert not (out / "crawl-report.json").exists()
