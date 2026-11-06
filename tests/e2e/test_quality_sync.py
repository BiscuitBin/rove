"""End to end: conversion quality and rovo verify (T17).

Two committed fixture sites are served on 127.0.0.1 by `serve_site`: `quality`, synced
under the generic profile (a page of islands, a page linking into it, a lossy page, a page
with no main, which the fallback extractor takes), and `devsite`, synced under the devsite
profile (a page of tab groups and a callout around DevSite chrome). `rovo init` and `rovo
verify` run through CliRunner; each sync runs `rovo._commands.sync` in process over the
real HttpxFetcher on a FixedClock, which never sleeps. robots.txt declares no Crawl-delay
and no sitemap, and there is no llms.txt. A page path strips the scope prefix /guide/, so
<base>guide/x.html is pages/<host>/x.md. Not `test_verify.py` or `test_convert.py`, which
the unit suite names.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from conftest import SiteServer
from test_init_sync import load, page_root, split_page
from typer.testing import CliRunner

from fakes import FixedClock
from rovo import _commands
from rovo._convert.profiles import CONFIG as CONVERT
from rovo._crawl.fetch import HttpxFetcher
from rovo._exit import ExitCode
from rovo.cli import app

USAGE = 2
QUALITY = 4
TOLERANCE = 1e-9
FENCE_OPENING = re.compile(r"^`{3,}(?P<info>\S[^\n]*)$", re.MULTILINE)
DEVSITE_CHROME = (
    "Example developers header",
    "Left navigation start",
    "Example developers footer",
)
UNTOUCHED = (".rovo/manifest.json", ".rovo/frontier.json", ".rovo/runs.json", "crawl-report.json")


def initialised(base: str, out: Path, *profile: str) -> Path:
    """`rovo init <base>guide/start.html <out> [--profile NAME]` through CliRunner."""
    arguments = ["init", f"{base}guide/start.html", str(out)]
    if profile:
        arguments += ["--profile", *profile]
    result = CliRunner().invoke(app, arguments, prog_name="rovo")
    assert result.exit_code == 0, result.output
    return out


def synced(out: Path, overrides: Sequence[str] = ()) -> ExitCode:
    """Rovo sync in process over the real HttpxFetcher, on a FixedClock."""
    with HttpxFetcher() as fetcher:
        return _commands.sync(out, fetcher=fetcher, clock=FixedClock(), overrides=tuple(overrides))


def page(out: Path, base: str, name: str) -> tuple[dict[str, object], str]:
    """A page file's frontmatter, each value decoded from its JSON, and its body."""
    raw, body = split_page((out / f"{page_root(base)}{name}.md").read_text(encoding="utf-8"))
    return {key: json.loads(value) for key, value in raw.items()}, body


def flags_of(row: dict[str, object]) -> list[object]:
    """A page file's quality_flags, or a report row's flags."""
    flags = row.get("quality_flags", row.get("flags"))
    assert isinstance(flags, list)
    return flags


def in_order(text: str, parts: Sequence[str]) -> bool:
    """Every part occurs in `text`, each after the one before."""
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def quality_site(serve_site: SiteServer, tmp_path: Path) -> tuple[str, Path]:
    """The quality site served, initialised and synced once; the sync exits 0."""
    base = serve_site("quality")
    out = initialised(base, tmp_path / "out")
    assert synced(out) is ExitCode.ok
    return base, out


def test_a_page_with_uncarryable_constructs_syncs_with_islands(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """Each construct Markdown cannot carry reaches the page as an island; nothing stops.

    Until T17 the non-heading id stopped the sync at UncarryableBecomesIsland.
    """
    base, out = quality_site(serve_site, tmp_path)
    frontmatter, body = page(out, base, "islands")

    tables = re.findall(r"<table.*?</table>", body, flags=re.DOTALL)
    assert len(tables) == len(("spanning", "header-less"))
    for table in tables:
        assert "\n\n" not in table
    assert 'rowspan="2"' in tables[0]
    for dropped in ("onclick", "style="):
        assert dropped not in body, dropped
    assert "<dl" in body
    assert "<math" in body
    assert re.search(
        r"<details[^>]*>.*?\n\n- first option\n- second option\n\n.*?</details>", body, re.DOTALL
    )
    assert '<a id="note"></a>' in body
    assert "```python" in body
    assert "html_table_kept" in flags_of(frontmatter)
    assert "fidelity_loss" not in flags_of(frontmatter)
    assert frontmatter["low_confidence"] is False

    _, linked = page(out, base, "linked")
    assert "](islands.md#note)" in linked
    assert load(out / "crawl-report.json")["broken_links"] == []


def test_a_lossy_page_is_flagged_and_reported(serve_site: SiteServer, tmp_path: Path) -> None:
    """A failed gate and a declared reduction are flagged, scored and tallied."""
    base, out = quality_site(serve_site, tmp_path)
    frontmatter, body = page(out, base, "gates")
    flags = flags_of(frontmatter)
    assert "code_lang_rate" in flags
    assert "interactive_omitted" in flags
    assert frontmatter["low_confidence"] is True
    score = frontmatter["quality_score"]
    assert isinstance(score, float)
    assert abs(score - (1 - CONVERT.weight_code_lang_rate)) < TOLERANCE
    (note,) = [line for line in body.splitlines() if "https://example.invalid/demo" in line]
    assert "<iframe" not in note

    summary = load(out / "crawl-report.json")["quality_summary"]
    assert isinstance(summary, dict)
    assert {"gate": "code_lang_rate", "pages": 1} in summary["gate_failures"]


def test_fail_on_low_quality_exits_4_for_a_touched_low_confidence_page(
    serve_site: SiteServer, tmp_path: Path
) -> None:
    """A page the fallback extractor took is low confidence; fail_on_low_quality exits 4.

    Re-propagated by the T17 follow-up (spec 022eca4): plain.html has no main, so the
    fallback extractor (trafilatura) takes it before the whole body; extractor_fallback is
    an incomplete flag as whole_body_extracted was.
    """
    base, out = quality_site(serve_site, tmp_path)
    plain = f"{page_root(base)}plain.md"

    def plain_row() -> dict[str, object]:
        rows = load(out / "crawl-report.json")["low_confidence_pages"]
        assert isinstance(rows, list)
        (row,) = [row for row in rows if row["path"] == plain]
        assert isinstance(row, dict)
        return row

    first = plain_row()
    assert "extractor_fallback" in flags_of(first)
    assert "whole_body_extracted" not in flags_of(first)
    assert first["touched_this_run"] is True
    assert load(out / "crawl-report.json")["exit_code"] == "ok"

    assert synced(out, ["quality.fail_on_low_quality=true"]) is ExitCode.quality
    assert ExitCode.quality.number == QUALITY
    assert load(out / "crawl-report.json")["exit_code"] == "quality"
    second = plain_row()
    assert "extractor_fallback" in flags_of(second)
    assert second["touched_this_run"] is True


def test_a_devsite_page_emits_every_tab_panel(serve_site: SiteServer, tmp_path: Path) -> None:
    """Under devsite: the article body without its chrome, every tab panel, a GFM alert."""
    base = serve_site("devsite")
    out = initialised(base, tmp_path / "out", "devsite")
    assert synced(out) is ExitCode.ok
    frontmatter, body = page(out, base, "tabs")

    languages = [match["info"].split()[0] for match in FENCE_OPENING.finditer(body)]
    assert languages == ["python", "java", "shell"]
    assert in_order(
        body,
        (
            "pip install example-client",
            'implementation "com.example:client:1.0"',
            "curl -O https://example.invalid/client.tar.gz",
            "### Linux",
            "On Linux, write the settings file",
            "### Windows",
            "On Windows, write the settings file",
            "> [!NOTE]",
        ),
    )
    assert "reads the settings file once" in body
    for chrome in DEVSITE_CHROME:
        assert chrome not in body, chrome
    assert frontmatter["method"] == "profile"
    assert frontmatter["profile"] == "devsite"
    assert frontmatter["breadcrumbs"] == ["Guides", "Tabs"]
    assert "tabs_expanded" not in flags_of(frontmatter)


def verify(out: Path) -> tuple[int, list[str], str]:
    """`rovo verify <out>` through CliRunner: its exit code, stdout lines and stderr."""
    result = CliRunner().invoke(app, ["verify", str(out)], prog_name="rovo")
    return result.exit_code, result.stdout.splitlines(), result.stderr


def test_rovo_verify_reports_drift_offline(serve_site: SiteServer, tmp_path: Path) -> None:
    """Rovo verify finds every kind of drift on disk without a request or a write.

    A fresh mirror has no finding: it exits 0, and its standard output holds only the
    gate tallies (gates.md failed code_lang_rate when it was measured).
    """
    base, out = quality_site(serve_site, tmp_path)
    root = page_root(base)
    requests = len(serve_site.paths(base))
    state = {name: (out / name).read_bytes() for name in UNTOUCHED}

    code, lines, error = verify(out)
    assert code == 0, (lines, error)
    assert lines == ["code_lang_rate 1"]

    islands = out / f"{root}islands.md"
    text = islands.read_text(encoding="utf-8")
    fence = re.search(r"```python\n.*?```\n", text, flags=re.DOTALL)
    assert fence is not None
    islands.write_text(text.replace(fence[0], "", 1), encoding="utf-8")
    (out / f"{root}gates.md").unlink()
    (out / f"{root}stray.md").write_text("# Stray\n", encoding="utf-8")
    start = out / f"{root}start.md"
    start_text = start.read_text(encoding="utf-8")
    assert "](linked.md)" in start_text
    start.write_text(start_text.replace("](linked.md)", "](missing.md)", 1), encoding="utf-8")
    index = out / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "A line of my own.\n", encoding="utf-8")
    (out / "README.md").write_text("# My mirror\n", encoding="utf-8")

    code, lines, error = verify(out)
    assert code == QUALITY, (lines, error)
    findings = {tuple(line.split(" ")[:2]) for line in lines}
    expected = {
        ("digest_mismatch", f"{root}islands.md"),
        ("quality_drift", f"{root}islands.md"),
        ("missing_file", f"{root}gates.md"),
        ("unmanaged_file", f"{root}stray.md"),
        ("digest_mismatch", f"{root}start.md"),
        ("broken_link", f"{root}start.md"),
        ("index_stale", "index.md"),
    }
    assert expected <= findings, sorted(findings)
    assert not any("README.md" in line for line in lines)
    assert len(serve_site.paths(base)) == requests
    assert {name: (out / name).read_bytes() for name in UNTOUCHED} == state

    empty = tmp_path / "empty"
    empty.mkdir()
    code, lines, error = verify(empty)
    assert code == USAGE
    assert lines == []
    assert error.startswith("rovo: verify: ")
