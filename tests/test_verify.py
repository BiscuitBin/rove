"""mirror.allium's verify obligations: VerifyPages and verification_failures (T17).

Each obligation test is named after the id `just plan-spec mirror` emits, dots and hyphens
as underscores, and its docstring quotes the obligation. The mirror is synced from the
indexes fixture site over a FakeFetcher on a FixedClock: four pages, every link resolved,
every page high confidence, so a fresh mirror has no finding. Each guarantee case then
changes one thing on disk and reads the findings (mirror.allium VerifyPages' guidance):
every path is mirror-relative, the findings are sorted by path, reason and detail, and a
verify pass writes nothing and makes no request. No e2e module is named test_verify.py.
"""

import dataclasses
import json
from pathlib import Path

from fakes import FakeFetcher, FixedClock, fixture_site
from rovo import _commands
from rovo._exit import ExitCode
from rovo._mirror.finalise import request_pass
from rovo._mirror.model import (
    Mirror,
    Operator,
    PassKind,
    PassStatus,
    VerificationFailure,
    VerificationFinished,
    VerificationReason,
)
from rovo._mirror.state import load_mirror
from rovo._mirror.verify import verification_failures, verify_pages, verify_pass
from spec_values import spec_enum

SITE = "http://docs.example"
SEED = f"{SITE}/guide/start.html"
PAGES = "pages/docs.example/"
START = f"{PAGES}start.md"
B = f"{PAGES}b.md"
REF = f"{PAGES}api/ref.md"
INDEX_MD = "index.md"


def synced_mirror(out_dir: Path) -> tuple[Path, FakeFetcher]:
    """Rovo init and sync of the indexes fixture site; the fetcher it ran over."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    fetcher = FakeFetcher(fixture_site("indexes", f"{SITE}/"))
    assert (
        _commands.sync(
            out_dir, fetcher=fetcher, clock=FixedClock(), tier_installed=lambda _: False
        )
        is ExitCode.ok
    )
    return out_dir, fetcher


def mirror_of(out_dir: Path) -> Mirror:
    """The mirror as the manifest on disk says."""
    return load_mirror(out_dir)


def findings(out_dir: Path) -> list[VerificationFailure]:
    """verification_failures over the mirror on disk."""
    return verification_failures(mirror_of(out_dir))


def reasons_at(found: list[VerificationFailure], path: str) -> set[VerificationReason]:
    """The reasons reported for one path."""
    return {failure.reason for failure in found if failure.path == path}


def split(path: Path) -> tuple[str, str]:
    """A page file's frontmatter block, its fences included, and its body."""
    text = path.read_text(encoding="utf-8")
    head, separator, body = text[len("---\n") :].partition("\n---\n")
    assert separator
    return f"---\n{head}\n---\n", body


def edit_body(out_dir: Path, path: str, old: str, new: str) -> None:
    """Replace `old` by `new` in one page file's body, its frontmatter untouched."""
    head, body = split(out_dir / path)
    assert old in body, (old, body)
    (out_dir / path).write_text(head + body.replace(old, new, 1), encoding="utf-8")


def snapshot(out_dir: Path) -> dict[str, bytes]:
    """Every file under the directory, by relative path."""
    return {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(out_dir.rglob("*"))
        if path.is_file()
    }


# --- The obligations ----------------------------------------------------------------------


def test_value_equality_VerificationFailure() -> None:
    """Verify value type VerificationFailure has structural equality."""
    failure = VerificationFailure(path=B, reason=VerificationReason.missing_file, detail="")
    again = VerificationFailure(path=B, reason=VerificationReason.missing_file, detail="")
    assert failure == again
    assert hash(failure) == hash(again)
    assert failure != dataclasses.replace(failure, path=START)
    assert failure != dataclasses.replace(failure, reason=VerificationReason.digest_mismatch)
    assert failure != dataclasses.replace(failure, detail="headings")


def test_entity_fields_VerificationFailure(tmp_path: Path) -> None:
    """Verify all declared fields on VerificationFailure are present with correct types.

    A page whose heading is no longer a heading drifts on the headings gate: the finding
    names the page by its mirror-relative path and the gate as its detail.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    edit_body(out_dir, START, "# Getting started\n", "Getting started\n")
    drift = [
        failure
        for failure in findings(out_dir)
        if failure.reason is VerificationReason.quality_drift
    ]
    (failure,) = drift
    assert isinstance(failure, VerificationFailure)
    assert isinstance(failure.path, str)
    assert failure.path == START
    assert isinstance(failure.reason, VerificationReason)
    assert isinstance(failure.detail, str)
    assert failure.detail == "headings"


def test_enum_comparable_VerificationReason(tmp_path: Path) -> None:
    """Verify fields typed with enum VerificationReason are comparable.

    The seven reasons are the specification's; the reasons two findings carry compare
    by value, equal for one reason and unequal across reasons.
    """
    assert {reason.value for reason in VerificationReason} == set(
        spec_enum("mirror", "VerificationReason")
    )
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / PAGES / "stray.md").write_text("# Stray\n", encoding="utf-8")
    (out_dir / PAGES / "other.md").write_text("# Other\n", encoding="utf-8")
    (out_dir / INDEX_MD).write_text(
        (out_dir / INDEX_MD).read_text(encoding="utf-8") + "A line of my own.\n",
        encoding="utf-8",
    )
    found = findings(out_dir)
    unmanaged = [f for f in found if f.reason is VerificationReason.unmanaged_file]
    stale = [f for f in found if f.reason is VerificationReason.index_stale]
    assert len(unmanaged) == len(("stray.md", "other.md"))
    assert unmanaged[0].reason == unmanaged[1].reason
    assert stale[0].reason != unmanaged[0].reason
    assert stale[0].reason == VerificationReason.index_stale


def test_rule_success_VerifyPages(tmp_path: Path) -> None:
    """Verify rule VerifyPages succeeds when all preconditions are met.

    A pending verify pass records verification_failures as its failures, completes, and
    raises VerificationFinished with the same failures: none on a fresh mirror, the
    drift on one changed on disk.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    operator = Operator()
    mirror = mirror_of(out_dir)
    pass_ = request_pass(operator, mirror, PassKind.verify, None)
    assert pass_.run_id is None
    finished = verify_pages(pass_)
    assert isinstance(finished, VerificationFinished)
    assert finished.failures == ()
    assert finished.pass_ is pass_
    assert finished.mirror is mirror
    assert finished.operator == operator
    assert pass_.status is PassStatus.completed
    assert pass_.failures == []

    (out_dir / B).unlink()
    drifted = mirror_of(out_dir)
    expected = verification_failures(drifted)
    assert (B, VerificationReason.missing_file) in {
        (failure.path, failure.reason) for failure in expected
    }
    second = request_pass(operator, drifted, PassKind.verify, None)
    found = verify_pages(second)
    assert found is not None
    assert list(found.failures) == expected
    assert second.failures == expected
    assert second.status is PassStatus.completed
    via_pass = verify_pass(operator, mirror_of(out_dir))
    assert via_pass is not None
    assert list(via_pass.failures) == expected
    assert via_pass.pass_.kind is PassKind.verify


def test_rule_failure_VerifyPages_1(tmp_path: Path) -> None:
    """Verify rule VerifyPages is rejected when requires clause fails.

    requires: pass.status = pending: a completed verify pass raises nothing and keeps
    its failures.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / B).unlink()
    pass_ = request_pass(Operator(), mirror_of(out_dir), PassKind.verify, None)
    pass_.status = PassStatus.completed
    assert verify_pages(pass_) is None
    assert pass_.failures == []
    assert pass_.status is PassStatus.completed


def test_rule_failure_VerifyPages_2(tmp_path: Path) -> None:
    """Verify rule VerifyPages is rejected when requires clause fails.

    requires: pass.kind = verify: a pending finalise pass and a pending index pass raise
    nothing and stay pending.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / B).unlink()
    mirror = mirror_of(out_dir)
    for kind, run_id in ((PassKind.finalise, 1), (PassKind.index, None)):
        pass_ = request_pass(Operator(), mirror, kind, run_id)
        assert verify_pages(pass_) is None
        assert pass_.status is PassStatus.pending
        assert pass_.failures == []


# --- verification_failures: each reason alone (VerifyPages' guidance) ----------------------


def test_a_fresh_mirror_has_no_finding(tmp_path: Path) -> None:
    """A mirror as the sync left it verifies clean."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    assert findings(out_dir) == []


def test_a_missing_page_file_is_missing_file(tmp_path: Path) -> None:
    """A written page whose file is gone is missing_file; links to it become broken."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / B).unlink()
    found = findings(out_dir)
    assert reasons_at(found, B) == {VerificationReason.missing_file}
    others = {failure.reason for failure in found if failure.path != B}
    assert others <= {VerificationReason.broken_link}
    assert VerificationReason.broken_link in reasons_at(found, START)


def test_an_unknown_markdown_file_is_unmanaged_file(tmp_path: Path) -> None:
    """A Markdown file under pages/ the manifest does not know, or under _indexes/."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / PAGES / "stray.md").write_text("# Stray\n", encoding="utf-8")
    assert [(failure.path, failure.reason) for failure in findings(out_dir)] == [
        (f"{PAGES}stray.md", VerificationReason.unmanaged_file)
    ]
    (out_dir / PAGES / "stray.md").unlink()
    (out_dir / "_indexes").mkdir()
    (out_dir / "_indexes" / "extra.md").write_text("# Extra\n", encoding="utf-8")
    found = findings(out_dir)
    assert [(failure.path, failure.reason) for failure in found] == [
        ("_indexes/extra.md", VerificationReason.unmanaged_file)
    ]


def test_the_operators_files_at_the_root_are_never_reported(tmp_path: Path) -> None:
    """Anything at the root that is not a managed file (.git/, a README) is the operator's."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / ".git").mkdir()
    (out_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (out_dir / "README.md").write_text("# My mirror\n", encoding="utf-8")
    (out_dir / "notes.txt").write_text("notes\n", encoding="utf-8")
    assert findings(out_dir) == []


def test_a_page_file_without_its_frontmatter_is_invalid_page_file(tmp_path: Path) -> None:
    """No frontmatter, a frontmatter that does not parse, or a required key missing."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    path = out_dir / B
    original = path.read_text(encoding="utf-8")
    head, body = split(path)
    title_line = next(line for line in head.splitlines() if line.startswith("title:"))
    cases = {
        "no frontmatter": body,
        "unparsable": original.replace(title_line, "title: {not json", 1),
        "missing key": original.replace(f"{title_line}\n", "", 1),
    }
    for name, text in cases.items():
        path.write_text(text, encoding="utf-8")
        found = findings(out_dir)
        assert VerificationReason.invalid_page_file in reasons_at(found, B), name
        assert VerificationReason.missing_file not in reasons_at(found, B), name
    path.write_text(original, encoding="utf-8")
    assert findings(out_dir) == []


def test_a_changed_body_is_digest_mismatch(tmp_path: Path) -> None:
    """A body whose digest differs from the frontmatter's and the manifest's.

    An added sentence changes no construct and keeps every expected word, so the digest
    is the only finding; a frontmatter digest that differs is one too.
    """
    out_dir, _ = synced_mirror(tmp_path / "out")
    head, body = split(out_dir / B)
    (out_dir / B).write_text(head + body + "\nA sentence of my own.\n", encoding="utf-8")
    found = findings(out_dir)
    assert [(failure.path, failure.reason) for failure in found] == [
        (B, VerificationReason.digest_mismatch)
    ]

    (out_dir / B).write_text(head + body, encoding="utf-8")
    assert findings(out_dir) == []
    digest_line = next(line for line in head.splitlines() if line.startswith("content_digest:"))
    zeros = 'content_digest: "' + "0" * 64 + '"'
    (out_dir / B).write_text(head.replace(digest_line, zeros) + body, encoding="utf-8")
    found = findings(out_dir)
    assert [(failure.path, failure.reason) for failure in found] == [
        (B, VerificationReason.digest_mismatch)
    ]


def test_a_gate_failing_on_the_current_body_is_quality_drift(tmp_path: Path) -> None:
    """A gate failing against the stored expected counts that did not fail when measured."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    edit_body(out_dir, START, "# Getting started\n", "Getting started\n")
    found = findings(out_dir)
    drift = [
        (failure.path, failure.detail)
        for failure in found
        if failure.reason is VerificationReason.quality_drift
    ]
    assert drift == [(START, "headings")]
    assert reasons_at(found, START) == {
        VerificationReason.digest_mismatch,
        VerificationReason.quality_drift,
    }


def test_a_link_that_reaches_nothing_is_broken_link(tmp_path: Path) -> None:
    """A relative link that reaches no file, leaves the mirror, or names a lost fragment."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    head, body = split(out_dir / START)
    assert "](b.md)" in body
    for target in ("missing.md", "../../../outside.md", "b.md#nowhere"):
        (out_dir / START).write_text(head + body.replace("](b.md)", f"]({target})"), "utf-8")
        found = findings(out_dir)
        broken = [
            failure.detail
            for failure in found
            if failure.reason is VerificationReason.broken_link and failure.path == START
        ]
        assert len(broken) == 1, (target, found)
        assert target in broken[0]
        assert reasons_at(found, START) == {
            VerificationReason.digest_mismatch,
            VerificationReason.broken_link,
        }


def test_a_link_in_a_generated_index_is_checked(tmp_path: Path) -> None:
    """A generated index's link to a page whose file is gone is a broken_link of the index."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / REF).unlink()
    found = findings(out_dir)
    assert VerificationReason.broken_link in reasons_at(found, INDEX_MD)


def test_an_edited_index_is_index_stale(tmp_path: Path) -> None:
    """An index file whose text differs from what BuildIndexes would write."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    index = out_dir / INDEX_MD
    index.write_text(index.read_text(encoding="utf-8") + "A line of my own.\n", encoding="utf-8")
    assert [(failure.path, failure.reason) for failure in findings(out_dir)] == [
        (INDEX_MD, VerificationReason.index_stale)
    ]


def test_findings_are_sorted_by_path_reason_and_detail(tmp_path: Path) -> None:
    """Several findings come back in order of path, then reason, then detail."""
    out_dir, _ = synced_mirror(tmp_path / "out")
    (out_dir / REF).unlink()
    edit_body(out_dir, START, "# Getting started\n", "Getting started\n")
    (out_dir / PAGES / "stray.md").write_text("# Stray\n", encoding="utf-8")
    found = findings(out_dir)
    assert len(found) > len(("missing", "drift", "stray"))
    order = [(failure.path, failure.reason.value, failure.detail) for failure in found]
    assert order == sorted(order)


def test_verify_writes_nothing_and_requests_nothing(tmp_path: Path) -> None:
    """Verify is offline: the manifest, the state files, the report and the pages stay."""
    out_dir, fetcher = synced_mirror(tmp_path / "out")
    (out_dir / B).unlink()
    edit_body(out_dir, START, "# Getting started\n", "Getting started\n")
    before = snapshot(out_dir)
    requests = list(fetcher.requests)
    assert verification_failures(mirror_of(out_dir))
    assert verify_pass(Operator(), mirror_of(out_dir)) is not None
    assert _commands.verify(out_dir) is ExitCode.quality
    assert snapshot(out_dir) == before
    assert list(fetcher.requests) == requests
    manifest = json.loads((out_dir / ".rovo" / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
