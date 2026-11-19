"""Tests run against the made-up household config in
config/household.example.json, never a real one. Set before any src module
is imported, since the ledger and SimpleFIN client read it at import time."""

import os
from pathlib import Path

os.environ["HOUSEHOLD_CONFIG"] = (
    Path(__file__).parent.parent / "config" / "household.example.json"
).read_text()
