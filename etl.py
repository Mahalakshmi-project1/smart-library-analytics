"""Command-line entry point:  python etl.py"""
import sys

from analytics.etl import run_etl
from database import get_db_connection


def main():
    connection = get_db_connection()
    try:
        stats = run_etl(connection)
    finally:
        connection.close()
    print("ETL finished:")
    for key, value in stats.items():
        print(f"  {key:16} {value}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ETL failed (rolled back): {exc}", file=sys.stderr)
        sys.exit(1)
