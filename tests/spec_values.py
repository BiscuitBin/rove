"""Read a module's `config` defaults from the committed specification, never restated.

A `config-default` test compares the code's value with the value the `.allium` file
declares, so a default changed in the specification fails the test until the code follows.
"""

import json
import re
from datetime import timedelta
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1] / "docs" / "specs"

_ENTRY = re.compile(r"(?P<name>\w+): [\w/<>]+ = (?P<value>.+)")
_DURATION = re.compile(r"(?P<count>\d+)\.(?P<unit>second|seconds|minute|minutes)")


def config_defaults(module: str) -> dict[str, str]:
    """Each `name: Type = value` of the module's config block, the value as written."""
    text = (SPECS / f"{module}.allium").read_text(encoding="utf-8")
    block = text[text.index("\nconfig {") :]
    block = block[: block.index("\n}")]
    defaults: dict[str, str] = {}
    for line in block.splitlines()[1:]:
        code = line.split("--", 1)[0].strip()
        match = _ENTRY.fullmatch(code)
        if match is not None:
            defaults[match["name"]] = match["value"].strip()
    return defaults


def _raw(module: str, name: str) -> str:
    return config_defaults(module)[name]


def spec_int(module: str, name: str) -> int:
    """An Integer default, underscores allowed."""
    return int(_raw(module, name).replace("_", ""))


def spec_float(module: str, name: str) -> float:
    """A Decimal default, including a quotient such as `0.05 / 3`."""
    numerator, _, denominator = _raw(module, name).partition("/")
    value = float(numerator)
    return value / float(denominator) if denominator else value


def spec_duration(module: str, name: str) -> timedelta:
    """A Duration default such as `30.seconds` or `5.minutes`."""
    match = _DURATION.fullmatch(_raw(module, name))
    assert match is not None, name
    unit = "seconds" if match["unit"].startswith("second") else "minutes"
    return timedelta(**{unit: int(match["count"])})


def spec_bool(module: str, name: str) -> bool:
    """A Boolean default."""
    raw = _raw(module, name)
    assert raw in {"true", "false"}, name
    return raw == "true"


def spec_string(module: str, name: str) -> str:
    """A String default, written as a quoted literal."""
    value = json.loads(_raw(module, name))
    assert isinstance(value, str), name
    return value


def spec_name(module: str, name: str) -> str:
    """An enumeration default, such as `never`."""
    return _raw(module, name)


def spec_names(module: str, name: str) -> frozenset[str]:
    """A set of enumeration values, such as `{ render_needed, empty_content }`."""
    raw = _raw(module, name).strip()
    assert raw.startswith("{"), name
    assert raw.endswith("}"), name
    return frozenset(part.strip() for part in raw[1:-1].split(",") if part.strip())


def spec_enum(module: str, name: str) -> tuple[str, ...]:
    """The values of `enum <name> { a | b | ... }`, in declaration order."""
    text = (SPECS / f"{module}.allium").read_text(encoding="utf-8")
    match = re.search(rf"\nenum {name} \{{(?P<body>.*?)\}}", text, re.DOTALL)
    assert match is not None, name
    body = " ".join(line.split("--", 1)[0] for line in match["body"].splitlines())
    return tuple(part.strip() for part in body.split("|") if part.strip())
