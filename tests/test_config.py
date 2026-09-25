""".env.example must stay in sync with the settings the app requires.

It is documentation nothing else checks, and it had already drifted: a
misspelt GROK_API_KEY and two required settings missing. Anyone following
the README would have hit "Field required" on startup.
"""

import re
from pathlib import Path

from app.core.config import Settings

# Resolved from this file's location, not the working directory.
ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _listed_names() -> set[str]:
    """Names of settings assigned in .env.example (comment lines ignored)."""
    return {
        match.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := re.match(r"^([A-Z_]+)=", line))
    }


def test_env_example_lists_every_required_setting():
    required = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.is_required()
    }

    assert required <= _listed_names()


def test_env_example_lists_no_unknown_settings():
    # Catches typos like GROK_API_KEY: a name the app would silently ignore.
    known = {name.upper() for name in Settings.model_fields}

    assert _listed_names() <= known