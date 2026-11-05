"""assign_path's full-digest fallback and its null outcome (mirror.allium MovePage, at fed9ed8).

The guidance (mirror.allium 706 to 732): a path another page holds (ignoring case) or one
past max_path_chars becomes a stem cut to max_path_chars - 10, "-" and the first
collision_hash_chars hex of the identity's digest. "When that suffixed path is itself held
(ignoring case) or too long, the suffix is the full 64-hex digest instead, with the stem
cut so the result still fits max_path_chars." max_path_chars counts the whole
mirror-relative path, pages/<host>/ included, and "a cut never shortens pages/<host>/".
"When the full-digest path is unusable too, assign_path is null."

A test holds a path by giving a stored page of another identity that path, as the
mirror would after an earlier assignment.
"""

from pathlib import Path

from rovo._mirror import model
from rovo._mirror.model import Mirror
from rovo._mirror.urls import assign_path, digest
from test_mirror import ROOT, SITE, new_mirror, stored

VICTIM = f"{SITE}/guide/victim.html"
STEM = f"{ROOT}victim"
PLAIN = f"{STEM}.md"
HOLDERS = (
    f"{SITE}/guide/holder-one.html",
    f"{SITE}/guide/holder-two.html",
    f"{SITE}/guide/holder-three.html",
)
FULL_DIGEST_CHARS = 64


def short_path(stem: str, identity: str) -> str:
    """The first fallback: stem, "-" and the first collision_hash_chars hex."""
    return f"{stem}-{digest(identity)[: model.CONFIG.collision_hash_chars]}.md"


def full_path(stem: str, identity: str) -> str:
    """The second fallback: stem, "-" and the full 64-hex digest."""
    return f"{stem}-{digest(identity)}.md"


def hold(mirror: Mirror, *paths: str) -> None:
    """Give each path to a stored page of another identity."""
    for holder, path in zip(HOLDERS, paths, strict=False):
        stored(mirror, requested=holder).path = path


def test_full_digest_when_the_short_suffixed_path_is_held(tmp_path: Path) -> None:
    """The short-suffixed path is held, so the suffix is the full 64-hex digest."""
    mirror = new_mirror(tmp_path)
    hold(mirror, PLAIN, short_path(STEM, VICTIM))
    path = assign_path(mirror, VICTIM)
    assert path == full_path(STEM, VICTIM)
    assert len(digest(VICTIM)) == FULL_DIGEST_CHARS


def test_full_digest_when_the_short_suffixed_path_is_held_ignoring_case(tmp_path: Path) -> None:
    """A holder of the short-suffixed path in another case holds it too."""
    mirror = new_mirror(tmp_path)
    hold(mirror, PLAIN.upper(), short_path(STEM, VICTIM).upper())
    assert assign_path(mirror, VICTIM) == full_path(STEM, VICTIM)


def test_short_suffix_kept_when_only_the_plain_path_is_held(tmp_path: Path) -> None:
    """Positive control: the first fallback still applies when its path is free."""
    mirror = new_mirror(tmp_path)
    hold(mirror, PLAIN)
    assert assign_path(mirror, VICTIM) == short_path(STEM, VICTIM)


def test_full_digest_depends_on_the_identity_alone(tmp_path: Path) -> None:
    """The holders' order and identities do not change the fallback path."""
    first = new_mirror(tmp_path / "first")
    hold(first, PLAIN, short_path(STEM, VICTIM))
    second = new_mirror(tmp_path / "second")
    hold(second, short_path(STEM, VICTIM), PLAIN)
    assert assign_path(first, VICTIM) == assign_path(second, VICTIM) == full_path(STEM, VICTIM)


def test_full_digest_path_fits_max_path_chars(tmp_path: Path) -> None:
    """A long path's full-digest fallback cuts the stem so the whole path fits max_path_chars."""
    mirror = new_mirror(tmp_path)
    max_chars = model.CONFIG.max_path_chars
    name = "x" * (max_chars + 1)
    identity = f"{SITE}/guide/{name}.html"
    first = assign_path(mirror, identity)  # too long, so the first fallback
    assert first == short_path(f"{ROOT}{name}"[: max_chars - 10], identity)
    assert len(first) == max_chars
    hold(mirror, first)
    path = assign_path(mirror, identity)
    assert path is not None
    assert path.endswith(f"-{digest(identity)}.md")
    assert len(path) <= max_chars
    stem = path[: -len(f"-{digest(identity)}.md")]
    assert stem.startswith(ROOT)  # the cut never shortens pages/<host>/
    assert stem.removeprefix(ROOT)
    assert name.startswith(stem.removeprefix(ROOT))


def test_max_path_chars_counts_the_whole_mirror_relative_path(tmp_path: Path) -> None:
    """A relative path that fits max_path_chars alone, but not with pages/<host>/, is too long."""
    mirror = new_mirror(tmp_path)
    max_chars = model.CONFIG.max_path_chars
    name = "y" * (max_chars - len(".md"))
    identity = f"{SITE}/guide/{name}.html"
    assert len(f"{name}.md") == max_chars
    path = assign_path(mirror, identity)
    assert path == short_path(f"{ROOT}{name}"[: max_chars - 10], identity)
    assert len(path) == max_chars


def test_null_when_the_host_leaves_no_room_for_a_page(tmp_path: Path) -> None:
    """A host too long to leave room for a page within max_path_chars has its pages refused."""
    mirror = new_mirror(tmp_path)
    host = f"{'h' * model.CONFIG.max_path_chars}.example"
    path: str | None = assign_path(mirror, f"http://{host}/guide/page.html")
    assert path is None


def test_null_when_the_full_digest_path_is_held(tmp_path: Path) -> None:
    """The plain, short-suffixed and full-digest paths are all held: assign_path is null."""
    mirror = new_mirror(tmp_path)
    hold(mirror, PLAIN, short_path(STEM, VICTIM), full_path(STEM, VICTIM))
    path: str | None = assign_path(mirror, VICTIM)
    assert path is None


def test_null_when_the_full_digest_path_is_held_ignoring_case(tmp_path: Path) -> None:
    """A holder of the full-digest path in another case holds it too."""
    mirror = new_mirror(tmp_path)
    hold(
        mirror,
        PLAIN,
        short_path(STEM, VICTIM),
        full_path(STEM, VICTIM).upper(),
    )
    path: str | None = assign_path(mirror, VICTIM)
    assert path is None


def test_own_page_does_not_hold_its_paths(tmp_path: Path) -> None:
    """The identity's own page never makes its own path held."""
    mirror = new_mirror(tmp_path)
    own = stored(mirror, requested=VICTIM)
    assert own.path == PLAIN
    assert assign_path(mirror, VICTIM) == PLAIN
