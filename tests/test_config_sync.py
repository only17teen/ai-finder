"""Guard against drift between DEFAULTS, config.toml.example, and SOURCE_NAMES."""

import tomllib
from pathlib import Path

from ai_finder.config import DEFAULTS
from ai_finder.main import SOURCE_NAMES

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config.toml.example"


def test_example_config_parses():
    assert EXAMPLE.exists(), "config.toml.example is missing"
    with open(EXAMPLE, "rb") as f:
        tomllib.load(f)  # must be valid TOML


def test_example_covers_all_source_keys():
    with open(EXAMPLE, "rb") as f:
        example = tomllib.load(f)
    example_sources = set(example.get("sources", {}))
    default_sources = set(DEFAULTS["sources"])
    missing = default_sources - example_sources
    extra = example_sources - default_sources
    assert not missing, f"config.toml.example missing sources: {missing}"
    assert not extra, f"config.toml.example has unknown sources: {extra}"


def test_source_names_match_defaults():
    # the CLI's canonical names must match the config's source toggles
    assert set(SOURCE_NAMES) == set(DEFAULTS["sources"])
