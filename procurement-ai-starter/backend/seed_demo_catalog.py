"""Explicitly add missing sample records without replacing saved demo prices or stock."""

import argparse
import json

from dotenv import load_dotenv

from backend.repositories.procurement import SQLiteProcurementRepository


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Import missing DEMO catalog records; existing records are preserved.")
    parser.add_argument("--db", help="SQLite database path (defaults to PROCUREMENT_DB_PATH or data/procurement.db)")
    args = parser.parse_args()
    repository = SQLiteProcurementRepository(args.db)
    try:
        additions = repository.import_demo_catalog_additions()
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps({"database": str(repository.db_path), "added": additions, "source": "DEMO DATA"}))


if __name__ == "__main__":
    main()
