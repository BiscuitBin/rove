"""rovo.allium's configuration obligations: rovo.toml, resolve_config and the built-in defaults.

Each test is named after the obligation id `just plan-spec rovo` emits, dots and hyphens
as underscores, and its docstring quotes the obligation. The defaults are read from the
specification's `config` block, never restated: the template init writes and
`resolve_config` must both agree with it.
"""

import dataclasses
import re
import tomllib
from pathlib import Path

from rovo import _commands, _config
from rovo._config import Configuration, initial_scope, resolve_config, starter_config
from rovo._convert import profiles
from rovo._crawl.model import RenderMode, RobotsMode, StealthMode
from rovo._report import ExitCode
from spec_values import spec_bool, spec_int, spec_name

SITE = "http://docs.example"
SEED = f"{SITE}/guide/start.html"
HASH = re.compile(r"[0-9a-f]{16}")

# Every key init writes with a value (the absent defaults have none to write).
TEMPLATE_KEYS = {
    "site": {"root_url", "start_urls"},
    "scope": {
        "allowed_hosts",
        "path_prefixes",
        "include",
        "exclude",
        "max_depth",
        "meaningful_query_params",
    },
    "conversion": {"profile"},
    "crawl": {"robots", "render_mode", "stealth_mode", "refollow_unchanged_links"},
    "quality": {"fail_on_low_quality"},
}


def initialised(out_dir: Path) -> Path:
    """A mirror rovo init made for the seed URL."""
    assert _commands.init(SEED, out_dir) is ExitCode.ok
    return out_dir


def rovo_toml(out_dir: Path) -> Path:
    """The mirror's configuration file."""
    return out_dir / "rovo.toml"


def set_key(out_dir: Path, key: str, value: str) -> None:
    """Replace the one `key = ...` line of rovo.toml with `key = value`."""
    path = rovo_toml(out_dir)
    text, count = re.subn(
        rf"(?m)^{re.escape(key)} = .*$", f"{key} = {value}", path.read_text(encoding="utf-8")
    )
    assert count == 1, key
    path.write_text(text, encoding="utf-8")


def drop_key(out_dir: Path, key: str) -> None:
    """Remove the one `key = ...` line of rovo.toml."""
    path = rovo_toml(out_dir)
    text, count = re.subn(rf"(?m)^{re.escape(key)} = .*\n", "", path.read_text(encoding="utf-8"))
    assert count == 1, key
    path.write_text(text, encoding="utf-8")


def test_value_equality_Configuration(tmp_path: Path) -> None:
    """Verify value type Configuration has structural equality.

    The same file resolves to equal configurations with the same hash; a changed value
    gives a different configuration and a different hash.
    """
    out_dir = initialised(tmp_path)
    first = resolve_config(out_dir)
    again = resolve_config(out_dir)
    assert first == again
    assert hash(first) == hash(again)
    set_key(out_dir, "max_depth", "3")
    changed = resolve_config(out_dir)
    assert changed != first
    assert changed.hash != first.hash
    assert changed == dataclasses.replace(first, max_depth=3, hash=changed.hash)


def test_entity_fields_Configuration(tmp_path: Path) -> None:
    """Verify all declared fields on Configuration are present with correct types.

    Re-propagated by T14 at a0814ab: Configuration gains refollow_unchanged_links.
    """
    settings = resolve_config(initialised(tmp_path))
    assert isinstance(settings, Configuration)
    assert settings.valid is True
    assert settings.problems == ()
    assert HASH.fullmatch(settings.hash)
    assert settings.root_url == f"{SITE}/guide/"
    assert settings.start_urls == (SEED,)
    assert settings.allowed_hosts == frozenset({"docs.example"})
    assert settings.path_prefixes == ("/guide/",)
    assert settings.include == ()
    assert settings.exclude == ()
    assert settings.max_depth == _config.CONFIG.max_depth
    assert settings.locale is None
    assert settings.meaningful_query_params == ()
    assert settings.profile_name == "generic"
    assert settings.robots is RobotsMode.respect
    assert settings.render_mode is _config.CONFIG.render_mode
    assert settings.stealth_mode is StealthMode.off
    assert settings.max_age is None
    assert settings.refollow_unchanged_links is _config.CONFIG.refollow_unchanged_links
    assert settings.fail_on_low_quality is _config.CONFIG.fail_on_low_quality
    assert settings.unblocking_provider is None
    assert settings.has_seeds is True
    assert settings.needs_browser is False
    assert settings.needs_stealth is False
    assert settings.root_changed(None) is False
    assert settings.root_changed(settings.root_url) is False
    assert settings.root_changed(f"{SITE}/other/") is True


def test_config_default_render_mode(tmp_path: Path) -> None:
    """Verify config parameter render_mode has its declared default.

    The built-in default, the template's value and an absent key all agree.
    """
    declared = RenderMode[spec_name("rovo", "render_mode")]
    assert _config.CONFIG.render_mode is declared
    out_dir = initialised(tmp_path)
    parsed = tomllib.loads(rovo_toml(out_dir).read_text(encoding="utf-8"))
    assert parsed["crawl"]["render_mode"] == declared.value
    drop_key(out_dir, "render_mode")
    assert resolve_config(out_dir).render_mode is declared


def test_config_default_max_depth(tmp_path: Path) -> None:
    """Verify config parameter max_depth has its declared default."""
    declared = spec_int("rovo", "max_depth")
    assert _config.CONFIG.max_depth == declared
    out_dir = initialised(tmp_path)
    parsed = tomllib.loads(rovo_toml(out_dir).read_text(encoding="utf-8"))
    assert parsed["scope"]["max_depth"] == declared
    drop_key(out_dir, "max_depth")
    assert resolve_config(out_dir).max_depth == declared


def test_config_default_fail_on_low_quality(tmp_path: Path) -> None:
    """Verify config parameter fail_on_low_quality has its declared default."""
    declared = spec_bool("rovo", "fail_on_low_quality")
    assert _config.CONFIG.fail_on_low_quality is declared
    out_dir = initialised(tmp_path)
    parsed = tomllib.loads(rovo_toml(out_dir).read_text(encoding="utf-8"))
    assert parsed["quality"]["fail_on_low_quality"] is declared
    drop_key(out_dir, "fail_on_low_quality")
    assert resolve_config(out_dir).fail_on_low_quality is declared


def test_config_default_refollow_unchanged_links(tmp_path: Path) -> None:
    """Verify config parameter refollow_unchanged_links has its declared default.

    The built-in default, the template's crawl.refollow_unchanged_links and an absent key
    agree; the file's false is read as false, and a value that is not a boolean is a
    problem naming the key.
    """
    declared = spec_bool("rovo", "refollow_unchanged_links")
    assert _config.CONFIG.refollow_unchanged_links is declared
    out_dir = initialised(tmp_path)
    parsed = tomllib.loads(rovo_toml(out_dir).read_text(encoding="utf-8"))
    assert parsed["crawl"]["refollow_unchanged_links"] is declared
    set_key(out_dir, "refollow_unchanged_links", "false")
    assert resolve_config(out_dir).refollow_unchanged_links is False
    set_key(out_dir, "refollow_unchanged_links", '"no"')
    invalid = resolve_config(out_dir)
    assert invalid.valid is False
    assert invalid.problems == ("crawl.refollow_unchanged_links: invalid value 'no'",)
    drop_key(out_dir, "refollow_unchanged_links")
    assert resolve_config(out_dir).refollow_unchanged_links is declared


def test_rovo_toml_round_trips() -> None:
    """The template init writes parses with tomllib and names every key with its value."""
    parsed = tomllib.loads(starter_config(SEED, profiles.GENERIC))
    for section, keys in TEMPLATE_KEYS.items():
        assert keys <= set(parsed[section]), section
    scope = initial_scope(SEED, profiles.GENERIC)
    assert parsed["site"]["root_url"] == scope.root_url
    assert parsed["site"]["start_urls"] == list(scope.start_urls)
    assert parsed["scope"]["allowed_hosts"] == sorted(scope.allowed_hosts)
    assert parsed["scope"]["path_prefixes"] == list(scope.path_prefixes)
    assert parsed["conversion"]["profile"] == "generic"
    assert parsed["crawl"]["robots"] == RobotsMode.respect.value
    assert parsed["crawl"]["stealth_mode"] == StealthMode.off.value


def test_initial_scope_from_the_site_url() -> None:
    """initial_scope keeps the first product segment, the URL, its host and its directory."""
    scope = initial_scope(SEED, profiles.GENERIC)
    assert scope.root_url == f"{SITE}/guide/"
    assert scope.start_urls == (SEED,)
    assert scope.allowed_hosts == frozenset({"docs.example"})
    assert scope.path_prefixes == ("/guide/",)
    assert scope.max_depth == _config.CONFIG.max_depth
    ported = initial_scope("http://127.0.0.1:8123/guide/start.html", profiles.GENERIC)
    assert ported.allowed_hosts == frozenset({"127.0.0.1"})


def test_resolve_config_names_every_bad_key(tmp_path: Path) -> None:
    """An unknown key, a bad enum value, a wrong type and an unknown profile are problems."""
    out_dir = initialised(tmp_path)
    set_key(out_dir, "render_mode", '"sometimes"')
    set_key(out_dir, "max_depth", '"deep"')
    set_key(out_dir, "profile", '"no-such-profile"')
    path = rovo_toml(out_dir)
    path.write_text(path.read_text(encoding="utf-8") + "\n[extra]\ncolour = 1\n", encoding="utf-8")
    settings = resolve_config(out_dir)
    assert settings.valid is False
    for key in ("crawl.render_mode", "scope.max_depth", "conversion.profile", "extra"):
        assert any(key in problem for problem in settings.problems), key


def test_resolve_config_rejects_an_unreadable_file(tmp_path: Path) -> None:
    """A file that does not parse, or no file at all, is an invalid configuration."""
    out_dir = initialised(tmp_path)
    rovo_toml(out_dir).write_text("[site\n", encoding="utf-8")
    assert resolve_config(out_dir).valid is False
    rovo_toml(out_dir).unlink()
    assert resolve_config(out_dir).valid is False
