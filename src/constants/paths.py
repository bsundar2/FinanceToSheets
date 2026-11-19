from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FIDELITY_STATEMENTS_DIR = DATA_DIR / "fidelity_statements"
FIDELITY_ACCOUNT_HISTORY_CSV = FIDELITY_STATEMENTS_DIR / "account_history.csv"
