import csv
from pathlib import Path

REQUIRED_COLS = {"rule_id", "scenario_id", "severity"}


def main() -> int:
    p = Path("docs/rule_register.csv")
    if not p.exists():
        print("MISSING: docs/rule_register.csv")
        return 1
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        missing = REQUIRED_COLS - cols
        if missing:
            print(f"Missing required columns: {sorted(missing)}")
            return 1
        rows = list(reader)
        if len(rows) < 1:
            print("rule_register.csv has no rows")
            return 1
    print("OK: rule_register.csv present and has required columns/rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
