"""Collected pages live under pages/<host>/ (mirror.allium and rovo.allium, at 1be7354).

mirror.allium's layout (Vocabulary, 49 to 58) puts collected pages under pages/, one
directory per host, beside the managed root files. MovePage's guidance (646 to 671):
assign_path gives "pages/", the host segment, "/" and a relative path; the host segment
is the identity's host lower-cased, a trailing "." dropped, every character outside
[a-z0-9.-] replaced with "-", the device-name rewrite applied, and a non-default port
appended as "_<port>" (con:8080 gives con-_8080; [::1]:8080, read in its bracketed form
as written, gives ---1-_8080). Two hosts that sanitise alike share a host segment, and
the collision step keeps their paths apart. The scope root is pages/<host>/index.md, and
a last segment the dropped .html, .htm or .aspx suffix leaves empty is named index as
for a directory URL (662 to 665). The identity comment (112 to 117) drops a
host's trailing ".", so example.com. and example.com are one identity. The template is
fixed at "pages/{host}/{path}" and is not a configuration key (mirror.allium 480 to 485;
rovo.allium 65 to 69): a layer that sets path_template, or max_path_chars, names an
unknown key.
"""

from pathlib import Path

import pytest

from rovo import _commands
from rovo._config import resolve_config
from rovo._mirror import model
from rovo._mirror.state import load_mirror
from rovo._mirror.urls import assign_path, digest, normalise_url
from rovo._report import ExitCode
from test_mirror import ROOT, SEED, SITE, assert_avoids_managed_names, new_mirror, scope, stored
from test_unplaceable_candidate import load, page_files, sync_seeds


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (SEED, f"{ROOT}start.md"),
        (f"{SITE}/guide/", f"{ROOT}index.md"),
        (f"{SITE}/guide/api/", f"{ROOT}api/index.md"),
        (f"{SITE}/other/page.aspx", f"{ROOT}other/page.md"),
        ("http://Docs.Example/guide/x.html", f"{ROOT}x.md"),
        ("http://docs.example./guide/x.html", f"{ROOT}x.md"),
        ("http://docs.example:8080/guide/x.html", "pages/docs.example_8080/x.md"),
        ("https://docs.example:443/guide/x.html", f"{ROOT}x.md"),
        ("http://127.0.0.1:8123/guide/start.html", "pages/127.0.0.1_8123/start.md"),
        ("http://my_host.example/guide/x.html", "pages/my-host.example/x.md"),
        ("http://con/guide/x.html", "pages/con-/x.md"),
        ("http://CON:8080/guide/x.html", "pages/con-_8080/x.md"),
        ("http://nul.example/guide/x.html", "pages/nul-.example/x.md"),
        ("http://lpt1.example./guide/x.html", "pages/lpt1-.example/x.md"),
    ],
)
def test_assign_path_puts_a_page_under_its_host_segment(
    tmp_path: Path, identity: str, expected: str
) -> None:
    """assign_path gives "pages/", the host segment, "/" and a relative path."""
    path = assign_path(new_mirror(tmp_path), identity)
    assert path == expected
    root = expected[: expected.index("/", len("pages/")) + 1]
    assert_avoids_managed_names(path, root)


def test_ipv6_host_segment_reads_the_bracketed_form(tmp_path: Path) -> None:
    """[::1]:8080 gives the host segment ---1-_8080 (mirror.allium 56 and 653 to 654).

    The maintainer's decision at 1be7354: the rule reads an IPv6 host in its bracketed
    form as written, so each of "[", ":", ":" and "]" becomes "-", then "_8080" follows.
    """
    path = assign_path(new_mirror(tmp_path), "http://[::1]:8080/guide/x.html")
    assert path == "pages/---1-_8080/x.md"
    assert_avoids_managed_names(path, "pages/---1-_8080/")


@pytest.mark.parametrize(
    ("prefix", "url_path", "expected"),
    [
        ("/", "/guide/.html", f"{ROOT}guide/index.md"),
        ("/", "/.html", f"{ROOT}index.md"),
        ("/", "/guide/.HTM", f"{ROOT}guide/index.md"),
        ("/", "/guide/sub/.aspx", f"{ROOT}guide/sub/index.md"),
        ("/guide/", "/guide/.html", f"{ROOT}index.md"),
        ("/guide/", "/guide/api/.Html", f"{ROOT}api/index.md"),
    ],
)
def test_a_last_segment_left_empty_by_the_dropped_suffix_is_named_index(
    tmp_path: Path, prefix: str, url_path: str, expected: str
) -> None:
    """A bare .html, .htm or .aspx last segment is named index (mirror.allium 662 to 665).

    The maintainer's decision at 1be7354: under the prefix "/", /guide/.html gives
    pages/<host>/guide/index.md and /.html gives pages/<host>/index.md, as for a
    directory URL; the suffix is dropped ignoring case.
    """
    mirror = new_mirror(tmp_path, path_prefixes=(prefix,), root_url=f"{SITE}{prefix}")
    path = assign_path(mirror, f"{SITE}{url_path}")
    assert path == expected
    assert_avoids_managed_names(path, ROOT)


def test_sync_publishes_a_bare_suffix_seed_as_an_index_page(tmp_path: Path) -> None:
    """A sync over a seed /guide/.html stores it at pages/docs.example/index.md.

    The run ends, writes crawl-report.json and exits ok; no other file is made for it.
    """
    bare = f"{SITE}/guide/.html"
    out_dir = tmp_path / "out"
    assert sync_seeds(out_dir, [SEED, bare]) is ExitCode.ok
    paths = {page.identity: page.path for page in load_mirror(out_dir).pages}
    assert paths == {SEED: f"{ROOT}start.md", bare: f"{ROOT}index.md"}
    assert page_files(out_dir) == sorted(paths.values())
    report = load(out_dir / "crawl-report.json")
    assert report["exit_code"] == "ok"
    assert report["failed_urls"] == []


def test_hosts_that_sanitise_alike_share_a_segment_and_collide_apart(tmp_path: Path) -> None:
    """Two hosts that sanitise alike share a host segment; the collision step keeps them apart."""
    mirror = new_mirror(tmp_path)
    holder = stored(mirror, requested=f"{SITE}/guide/holder.html")
    holder.path = "pages/my-host.example/x.md"
    identity = "http://my_host.example/guide/x.html"
    suffix = digest(identity)[: model.CONFIG.collision_hash_chars]
    assert assign_path(mirror, identity) == f"pages/my-host.example/x-{suffix}.md"


def test_stored_seed_page_lies_in_its_host_namespace(tmp_path: Path) -> None:
    """StoreNewPage gives the seed pages/<host>/start.md, never a path beside the root files."""
    mirror = new_mirror(tmp_path)
    page = stored(mirror)
    assert page.path == f"{ROOT}start.md"
    assert_avoids_managed_names(page.path, ROOT)


def test_trailing_dot_host_is_the_same_identity() -> None:
    """A host's trailing "." is dropped: example.com. and example.com are one identity."""
    plain = "http://docs.example/guide/start.html"
    assert normalise_url("http://docs.example./guide/start.html", ()) == plain
    assert normalise_url("HTTP://Docs.Example.:80/guide/start.html", ()) == plain
    assert (
        normalise_url("http://docs.example.:8080/guide/", ()) == "http://docs.example:8080/guide/"
    )
    fixture = scope()
    assert fixture.identity_of("http://docs.example./guide/start.html") == SEED
    assert fixture.host_allowed("http://docs.example./guide/start.html")
    assert fixture.is_seed("http://docs.example./guide/start.html")


@pytest.mark.parametrize(
    ("key", "value"),
    [("path_template", '"{version}/{path}"'), ("max_path_chars", "128")],
)
def test_layout_parameters_are_not_rovo_toml_keys(tmp_path: Path, key: str, value: str) -> None:
    """path_template and max_path_chars are not keys: a layer setting one names an unknown key."""
    out_dir = tmp_path / "out"
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    config = out_dir / "rovo.toml"
    assert key not in config.read_text(encoding="utf-8")
    assert resolve_config(out_dir).valid  # positive control: the starter file is valid
    for section in ("scope", "conversion"):
        text = config.read_text(encoding="utf-8")
        header = f"[{section}]\n"
        assert header in text
        config.write_text(text.replace(header, f"{header}{key} = {value}\n", 1), encoding="utf-8")
        settings = resolve_config(out_dir)
        assert settings.valid is False, section
        assert any(f"{section}.{key}" in problem for problem in settings.problems), (
            settings.problems
        )
        config.write_text(text, encoding="utf-8")
