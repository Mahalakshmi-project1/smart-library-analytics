"""Create / upgrade the database. Safe to run repeatedly (idempotent).

    python init_db.py

1. Creates the database if needed.
2. Runs sql/schema.sql (CREATE TABLE IF NOT EXISTS ...) - a fresh install is complete here.
3. Upgrades an OLDER database that already has the 4 original tables: adds the
   books.category column, indexes, foreign keys and CHECK constraints that are
   missing. Each step is guarded and reported, and a step that cannot be applied
   because existing data violates it (e.g. orphan rows) is SKIPPED with the reason
   instead of crashing - fix the data (see the Data Quality page) and re-run.
"""
import os
import sys

from config import DB_NAME
from database import get_db_connection, get_server_connection

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "sql", "schema.sql")

# (table, index name, columns) - why each exists is documented in README.md
INDEXES = [
    ("books", "idx_books_title", "title"),
    ("books", "idx_books_author", "author"),
    ("books", "idx_books_category", "category"),
    ("students", "idx_students_department", "department"),
    ("students", "idx_students_email", "email"),
    ("issued_books", "idx_issued_issue_date", "issue_date"),
    ("issued_books", "idx_issued_return_date", "return_date"),
    ("issued_books", "idx_issued_status_due", "status, due_date"),
    ("issued_books", "idx_issued_book_status", "book_id, status"),
    ("issued_books", "idx_issued_student_date", "student_id, issue_date"),
]

FOREIGN_KEYS = [
    ("issued_books", "fk_issued_book",
     "FOREIGN KEY (book_id) REFERENCES books (book_id) "
     "ON DELETE RESTRICT ON UPDATE CASCADE"),
    ("issued_books", "fk_issued_student",
     "FOREIGN KEY (student_id) REFERENCES students (student_id) "
     "ON DELETE RESTRICT ON UPDATE CASCADE"),
]

CHECKS = [
    ("books", "chk_books_quantity", "quantity > 0"),
    ("books", "chk_books_status", "status IN ('Available', 'Issued')"),
    ("issued_books", "chk_issue_fine", "fine >= 0"),
    ("issued_books", "chk_issue_status", "status IN ('Issued', 'Returned')"),
]


def read_statements(path):
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.strip().startswith("--")]
    return [s.strip() for s in "".join(lines).split(";") if s.strip()]


def create_database():
    """Best effort: managed cloud MySQL usually provides the database already
    (and may not allow CREATE DATABASE), so a failure here is not fatal."""
    try:
        conn = get_server_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"  (could not open a server-level connection: {exc})")
        return
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"  (skipping CREATE DATABASE: {exc})")
    finally:
        conn.close()


def exists(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()[0] > 0


def column_exists(cur, table, column):
    return exists(cur, """SELECT COUNT(*) FROM information_schema.columns
                          WHERE table_schema = DATABASE() AND table_name = %s
                            AND column_name = %s""", (table, column))


def index_exists(cur, table, name):
    return exists(cur, """SELECT COUNT(*) FROM information_schema.statistics
                          WHERE table_schema = DATABASE() AND table_name = %s
                            AND index_name = %s""", (table, name))


def constraint_exists(cur, table, name):
    return exists(cur, """SELECT COUNT(*) FROM information_schema.table_constraints
                          WHERE table_schema = DATABASE() AND table_name = %s
                            AND constraint_name = %s""", (table, name))


def attempt(conn, cur, label, sql):
    """Run one upgrade step; report instead of crash if it cannot be applied."""
    try:
        cur.execute(sql)
        conn.commit()
        print(f"  [added]   {label}")
    except Exception as exc:  # noqa: BLE001 - report and continue
        conn.rollback()
        print(f"  [skipped] {label}: {exc}")


def main():
    create_database()
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        print("Step 1: creating missing tables from sql/schema.sql")
        for stmt in read_statements(SCHEMA_FILE):
            cur.execute(stmt)
        conn.commit()

        print("Step 2: upgrading existing tables")
        if not column_exists(cur, "books", "category"):
            attempt(conn, cur, "books.category column",
                    "ALTER TABLE books ADD COLUMN category VARCHAR(80) NULL AFTER author")

        for table, name, cols in INDEXES:
            if not index_exists(cur, table, name):
                attempt(conn, cur, f"index {name} ({cols})",
                        f"ALTER TABLE {table} ADD INDEX {name} ({cols})")

        for table, name, definition in FOREIGN_KEYS:
            if not constraint_exists(cur, table, name):
                attempt(conn, cur, f"foreign key {name}",
                        f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")

        for table, name, expr in CHECKS:
            if not constraint_exists(cur, table, name):
                attempt(conn, cur, f"check {name}",
                        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr})")

        print("Done. Next: python seed_data.py  (optional demo data), python etl.py")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"init_db failed: {exc}", file=sys.stderr)
        sys.exit(1)
