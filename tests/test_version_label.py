"""The version label in a page path and in Page.version (mirror.allium at 022eca4).

MovePage's guidance (688 to 702): only an identity carrying the profile's version_param
is labelled; the label is the value mapped through version_map, else the raw value,
either one with every character outside [A-Za-z0-9._-] replaced with "-"; the rewritten
last segment, less a final ".md", gets "@", the label and ".md". StoreNewPage's guidance
(827 to 832): Page.version is that label when the identity carries the parameter, the
profile's version_default when it does not, and null when the profile has no
version_param. T17 follow-up, the maintainer's answer to the batched question, item 2.

Two edges are the spec author's veto-able choices, recorded in the T17 ledger: an existing
".md" is stripped before the label goes on, and an empty raw value gives "foo@.md".
"""

import dataclasses
from pathlib import Path

import pytest

from rovo._convert import profiles
from rovo._convert.model import VersionMapping
from rovo._mirror.model import CrawlScope, Mirror
from rovo._mirror.urls import assign_path, version_label

SITE = "http://docs.example"
ROOT = "pages/docs.example/"


def learn_mirror(out_dir: Path) -> Mirror:
    """A mirror of the docs site's guide under mslearn, ?view= meaningful."""
    scope = CrawlScope(
        root_url=f"{SITE}/guide/",
        start_urls=(f"{SITE}/guide/start.html",),
        allowed_hosts=frozenset({"docs.example"}),
        path_prefixes=("/guide/",),
        include=(),
        exclude=(),
        max_depth=10,
        locale=None,
        meaningful_query_params=("view",),
        locale_codes=profiles.MSLEARN.locale_codes,
    )
    return Mirror(
        out_dir=out_dir,
        scope=scope,
        profile=profiles.MSLEARN,
        processing_signature="signature-1",
    )


# identity below SITE -> (page path below ROOT, Page.version)
LABELLED = {
    "mapped": ("/guide/foo?view=graph-rest-beta", "foo@beta.md", "beta"),
    "mapped-default-value": ("/guide/foo?view=graph-rest-1.0", "foo@v1.0.md", "v1.0"),
    "page-suffix-dropped": ("/guide/foo.html?view=graph-rest-beta", "foo@beta.md", "beta"),
    "scope-root": ("/guide/?view=x", "index@x.md", "x"),
    "directory": ("/guide/sub/?view=x", "sub/index@x.md", "x"),
    "existing-md": ("/guide/README.md?view=x", "README@x.md", "x"),
    "rewrites-first": ("/guide/con?view=x", "con-@x.md", "x"),
    "unmapped-raw": ("/guide/foo?view=graph-rest-2.0", "foo@graph-rest-2.0.md", "graph-rest-2.0"),
    "unmapped-raw-sanitised": ("/guide/foo?view=v2~rc", "foo@v2-rc.md", "v2-rc"),
    "empty-raw": ("/guide/foo?view=", "foo@.md", ""),
}


@pytest.mark.parametrize("name", list(LABELLED))
def test_a_labelled_identity_gets_at_and_its_label(tmp_path: Path, name: str) -> None:
    """The label goes after the rewritten last segment, before ".md"; Page.version is it."""
    identity, path, version = LABELLED[name]
    assert assign_path(learn_mirror(tmp_path), f"{SITE}{identity}") == f"{ROOT}{path}"
    assert version_label(profiles.MSLEARN, f"{SITE}{identity}") == version


def test_an_identity_without_the_parameter_gets_no_label(tmp_path: Path) -> None:
    """version_default never touches the path; it is only the recorded Page.version."""
    mirror = learn_mirror(tmp_path)
    assert profiles.MSLEARN.version_default == "v1.0"
    assert assign_path(mirror, f"{SITE}/guide/foo") == f"{ROOT}foo.md"
    assert assign_path(mirror, f"{SITE}/guide/") == f"{ROOT}index.md"
    assert version_label(profiles.MSLEARN, f"{SITE}/guide/foo") == "v1.0"
    undefaulted = dataclasses.replace(profiles.MSLEARN, version_default=None)
    assert version_label(undefaulted, f"{SITE}/guide/foo") is None


def test_a_profile_without_a_version_param_has_no_version(tmp_path: Path) -> None:
    """No version_param: Page.version is null and ?view= labels nothing."""
    mirror = dataclasses.replace(learn_mirror(tmp_path), profile=profiles.GENERIC)
    assert version_label(profiles.GENERIC, f"{SITE}/guide/foo?view=x") is None
    assert assign_path(mirror, f"{SITE}/guide/foo?view=x") == f"{ROOT}foo.md"


def test_a_mapped_label_is_sanitised_too(tmp_path: Path) -> None:
    """A version_map label outside [A-Za-z0-9._-] has each such character replaced."""
    odd = dataclasses.replace(
        profiles.MSLEARN, version_map=(VersionMapping(raw="r", label="v 2/x"),)
    )
    mirror = dataclasses.replace(learn_mirror(tmp_path), profile=odd)
    assert assign_path(mirror, f"{SITE}/guide/foo?view=r") == f"{ROOT}foo@v-2-x.md"
    assert version_label(odd, f"{SITE}/guide/foo?view=r") == "v-2-x"


def test_an_unlabelled_path_never_meets_a_labelled_one(tmp_path: Path) -> None:
    """Sanitising replaces "@" in every segment, so no unlabelled path holds one."""
    mirror = learn_mirror(tmp_path)
    unlabelled = assign_path(mirror, f"{SITE}/guide/foo@beta")
    assert unlabelled == f"{ROOT}foo-beta.md"
    assert assign_path(mirror, f"{SITE}/guide/foo?view=graph-rest-beta") != unlabelled


def test_the_version_value_is_form_decoded(tmp_path: Path) -> None:
    """The value is form-decoded before it is mapped or sanitised (mirror.allium at 86e2ec5).

    MovePage's guidance (688 to 704) and StoreNewPage's (829 to 834): "+" is a space and
    %XX is decoded, so a version_map raw value holding a space matches ?view=a+b and
    ?view=a%20b alike, and unmapped, ?view=a%2Fb is a/b, labelled a-b. Re-propagated by
    T18 (origin T17), the maintainer's answer to T18's batched question, item 3.
    """
    spaced = dataclasses.replace(
        profiles.MSLEARN, version_map=(VersionMapping(raw="graph rest", label="gr"),)
    )
    mirror = dataclasses.replace(learn_mirror(tmp_path), profile=spaced)
    for query in ("graph+rest", "graph%20rest"):
        assert version_label(spaced, f"{SITE}/guide/foo?view={query}") == "gr", query
        assert assign_path(mirror, f"{SITE}/guide/foo?view={query}") == f"{ROOT}foo@gr.md"
    assert version_label(profiles.MSLEARN, f"{SITE}/guide/foo?view=a%2Fb") == "a-b"
    assert version_label(profiles.MSLEARN, f"{SITE}/guide/foo?view=a+b") == "a-b"
