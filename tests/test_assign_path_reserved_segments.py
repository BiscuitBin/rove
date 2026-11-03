"""assign_path's segment rewrites inside pages/<host>/ (mirror.allium MovePage, at fed9ed8).

The guidance (mirror.allium 674 to 697): each rewrite reads one sanitised segment alone
and they apply together. A trailing run of "." becomes "-"; a leading "." becomes "-"
(.git/ gives -git/, .rovo/ gives -rovo/); a directory segment equal, ignoring case, to a
managed root file name has its last "." replaced with "-" (llms.txt/guide gives
llms-txt/guide.md); a directory segment ending in .md, ignoring case, has its final "."
replaced with "-"; a segment whose part before its first "." is a device name, ignoring
case, has "-" appended to that part (con gives con-, con.txt gives con-.txt, NUL.json/x
gives NUL-.json/x.md). "No segment equal to _removed is rewritten any more": the archive
is _removed/ at the mirror's root, a sibling of pages/. The relative path (646 to 667)
drops empty segments and a trailing .html, .htm or .aspx ignoring case, and appends ".md"
unless the last segment already ends in ".md" exactly, in lower case.
"""

from pathlib import Path

import pytest

from rovo._mirror import model
from rovo._mirror.urls import assign_path, digest
from test_mirror import ROOT, SITE, assert_avoids_managed_names, new_mirror, stored


def assigned(tmp_path: Path, relative: str) -> str:
    """The path assign_path gives the identity SITE/guide/<relative> in an empty mirror."""
    path = assign_path(new_mirror(tmp_path), f"{SITE}/guide/{relative}")
    assert path is not None, relative
    assert_avoids_managed_names(path, ROOT)
    return path.removeprefix(ROOT)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (".git/config.html", "-git/config.md"),
        (".rovo/page.html", "-rovo/page.md"),
        (".Rovo/page.html", "-Rovo/page.md"),
        (".rovoish/page.html", "-rovoish/page.md"),
        ("notes/.rovo.html", "notes/-rovo.md"),
        ("trailing./page.html", "trailing-/page.md"),
        ("x../page.html", "x--/page.md"),
        (".../page.html", "---/page.md"),
        ("page.", "page-.md"),
    ],
)
def test_leading_and_trailing_dots_become_dashes(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """A trailing run of "." becomes "-" and a leading "." becomes "-", so no page is hidden."""
    assert assigned(tmp_path, relative) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("_removed/page.html", "_removed/page.md"),
        ("_REMOVED/page.html", "_REMOVED/page.md"),
        ("_Removed/", "_Removed/index.md"),
        ("_removed.html", "_removed.md"),
        ("_indexes/page.html", "_indexes/page.md"),
        ("-removed/page.html", "-removed/page.md"),
    ],
)
def test_removed_and_indexes_segments_are_not_rewritten(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """No segment equal to _removed is rewritten any more: no page path can reach the root's _removed/."""  # noqa: E501  The guidance, quoted.
    assert assigned(tmp_path, relative) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("llms.txt/guide.html", "llms-txt/guide.md"),
        ("LLMS.TXT/guide.html", "LLMS-TXT/guide.md"),
        ("index.jsonl/page.html", "index-jsonl/page.md"),
        ("links.jsonl/page.html", "links-jsonl/page.md"),
        ("crawl-report.json/page.html", "crawl-report-json/page.md"),
        ("Rovo.TOML/page.html", "Rovo-TOML/page.md"),
        ("llms.txt", "llms.txt.md"),
        ("rovo.toml", "rovo.toml.md"),
    ],
)
def test_directory_named_like_a_managed_root_file_has_its_last_dot_replaced(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """A directory segment equal, ignoring case, to a managed root file name has its last "." replaced with "-"; a last segment is a page name and keeps it."""  # noqa: E501  The guidance, quoted.
    assert assigned(tmp_path, relative) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("a.md/x.html", "a-md/x.md"),
        ("A.MD/x.html", "A-MD/x.md"),
        ("v1.2.md/x.html", "v1.2-md/x.md"),
        (".md/x.html", "-md/x.md"),
    ],
)
def test_directory_ending_in_md_has_its_final_dot_replaced(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """A directory segment ending in .md (ignoring case) has its final "." replaced with "-", since a page file is never also a directory."""  # noqa: E501  The guidance, quoted.
    assert assigned(tmp_path, relative) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("con.html", "con-.md"),
        ("con.txt", "con-.txt.md"),
        ("NUL.json/x.html", "NUL-.json/x.md"),
        ("Aux/page.html", "Aux-/page.md"),
        ("com1/lpt9.html", "com1-/lpt9-.md"),
        ("prn.tar.gz", "prn-.tar.gz.md"),
        ("console.html", "console.md"),
        ("lpt10.html", "lpt10.md"),
        ("com0/x.html", "com0/x.md"),
    ],
)
def test_device_name_stem_gains_a_dash(tmp_path: Path, relative: str, expected: str) -> None:
    """A segment whose part before its first "." is a device name, ignoring case, has "-" appended to that part."""  # noqa: E501  The guidance, quoted.
    assert assigned(tmp_path, relative) == expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("README.md", "README.md"),
        ("README.MD", "README.MD.md"),
        ("README.Md", "README.Md.md"),
        ("page.HTML", "page.md"),
        ("page.Htm", "page.md"),
        ("page.ASPX", "page.md"),
        ("data.json", "data.json.md"),
        ("a//b.html", "a/b.md"),
        ("a b/c.htm", "a-b/c.md"),
    ],
)
def test_md_appended_unless_the_last_segment_ends_in_lower_case_md(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """Empty segments are dropped, .html/.htm/.aspx dropped ignoring case, and ".md" appended unless the name ends in ".md" exactly."""  # noqa: E501  The guidance, quoted.
    assert assigned(tmp_path, relative) == expected


def test_segment_rewrites_happen_before_the_collision_check(tmp_path: Path) -> None:
    """A rewritten path another page holds gains the identity's hash suffix."""
    mirror = new_mirror(tmp_path)
    holder = stored(mirror, requested=f"{SITE}/guide/-rovo/page.html")
    assert holder.path == f"{ROOT}-rovo/page.md"
    identity = f"{SITE}/guide/.ROVO/page.html"
    suffix = digest(identity)[: model.CONFIG.collision_hash_chars]
    path = assign_path(mirror, identity)
    assert path == f"{ROOT}-ROVO/page-{suffix}.md"
    assert_avoids_managed_names(path, ROOT)


def test_stored_pages_under_rewritten_directories_avoid_managed_names(tmp_path: Path) -> None:
    """StoreNewPage keeps PagePathsAvoidManagedNames for sources under rewritten directories."""
    mirror = new_mirror(tmp_path)
    for relative in (".Hidden/one.html", "LLMS.txt/two.html", "a.MD/three.html", "con/four.html"):
        page = stored(mirror, requested=f"{SITE}/guide/{relative}")
        assert_avoids_managed_names(page.path, ROOT)
    assert [page.path.removeprefix(ROOT) for page in mirror.pages] == [
        "-Hidden/one.md",
        "LLMS-txt/two.md",
        "a-MD/three.md",
        "con-/four.md",
    ]
