"""Household-specific settings that stay out of the repo: SimpleFIN account
ids, account-number digits and payee names the joint account ledger matches
on, its start date, and the mortgage split.

Read from the HOUSEHOLD_CONFIG env var (the JSON itself, as stored in the
GitHub Actions secret of that name) or, locally, from config/household.json
(gitignored). config/household.example.json shows the shape. With neither,
the config is empty: the joint account ledger refuses to run, and nothing
else needs it.
"""

import json
import os
from functools import cache

from src.constants.paths import PROJECT_ROOT

HOUSEHOLD_CONFIG_ENV_VAR = "HOUSEHOLD_CONFIG"
HOUSEHOLD_CONFIG_FILE = PROJECT_ROOT / "config" / "household.json"


@cache
def load() -> dict:
    raw = os.getenv(HOUSEHOLD_CONFIG_ENV_VAR)
    source = f"the {HOUSEHOLD_CONFIG_ENV_VAR} env var"
    if not raw:
        if not HOUSEHOLD_CONFIG_FILE.exists():
            return {}
        raw = HOUSEHOLD_CONFIG_FILE.read_text()
        source = str(HOUSEHOLD_CONFIG_FILE)
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        # Position only: the message would otherwise quote the config itself
        raise ValueError(
            f"Household config in {source} isn't valid JSON (line {e.lineno}, column {e.colno})"
        ) from None
    if not isinstance(config, dict):
        raise ValueError(f"Household config in {source} must be a JSON object")
    return config
