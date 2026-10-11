"""Test helper: runs the project's MySQL-style analytics SQL on in-memory SQLite.

It registers MySQL functions (DATE_FORMAT, DATEDIFF, GREATEST) and translates the
%(name)s / %s placeholders. It verifies QUERY LOGIC (joins, aggregation, filters,
date-range handling). It does NOT prove MySQL dialect/ONLY_FULL_GROUP_BY behaviour -
run the app against a real MySQL 8 for that.
"""
import re
import sqlite3
from datetime import date, datetime

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, password TEXT);
CREATE TABLE books (book_id INTEGER PRIMARY KEY, title TEXT NOT NULL, author TEXT, category TEXT,
                    quantity INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'Available');
CREATE TABLE students (student_id INTEGER PRIMARY KEY, name TEXT NOT NULL, department TEXT,
                       year INTEGER, email TEXT, phone TEXT);
CREATE TABLE issued_books (issue_id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
                           issue_date TEXT, due_date TEXT, return_date TEXT,
                           fine REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'Issued');
CREATE TABLE monthly_library_stats (month TEXT PRIMARY KEY, books_issued INT, books_returned INT,
    unique_borrowers INT, late_returns INT, fine_collected REAL, avg_loan_days REAL,
    return_rate_pct REAL, refreshed_at TEXT);
CREATE TABLE department_library_stats (department TEXT PRIMARY KEY, total_students INT, active_borrowers INT,
    total_issues INT, total_returns INT, currently_issued INT, overdue_open INT, fine_collected REAL,
    avg_issues_per_student REAL, refreshed_at TEXT);
CREATE TABLE book_borrowing_stats (book_id INTEGER PRIMARY KEY, title TEXT, author TEXT, category TEXT,
    times_issued INT, times_returned INT, currently_issued INT, total_fine REAL, avg_loan_days REAL,
    last_issued_date TEXT, popularity_rank INT, refreshed_at TEXT);
CREATE TABLE etl_run_log (run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
    status TEXT, source_rows INT, rejected_rows INT, monthly_rows INT, department_rows INT,
    book_rows INT, message TEXT);
"""


def _d(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _datediff(a, b):
    a, b = _d(a), _d(b)
    return None if a is None or b is None else (a - b).days


def _date_format(v, fmt):
    d = _d(v)
    return None if d is None else d.strftime(fmt)


def _greatest(*args):
    vals = [a for a in args if a is not None]
    return max(vals) if vals else None


def _adapt(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


class Cursor:
    def __init__(self, conn, dictionary=False):
        self._c = conn.cursor()
        self._dict = dictionary

    def execute(self, sql, params=None):
        if isinstance(params, dict):
            sql = re.sub(r"%\((\w+)\)s", r":\1", sql)
            params = {k: _adapt(v) for k, v in params.items()}
        elif params is not None:
            sql = sql.replace("%s", "?")
            params = tuple(_adapt(v) for v in params)
        self._c.execute(sql, params if params is not None else ())

    def executemany(self, sql, rows):
        self._c.executemany(sql.replace("%s", "?"),
                            [tuple(_adapt(v) for v in r) for r in rows])

    def _wrap(self, row):
        if row is None or not self._dict:
            return row
        return {d[0]: v for d, v in zip(self._c.description, row)}

    def fetchall(self):
        return [self._wrap(r) for r in self._c.fetchall()]

    def fetchone(self):
        return self._wrap(self._c.fetchone())

    def close(self):
        self._c.close()


class Connection:
    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.create_function("DATEDIFF", 2, _datediff)
        self._conn.create_function("DATE_FORMAT", 2, _date_format)
        self._conn.create_function("GREATEST", -1, _greatest)
        self._conn.executescript(SCHEMA)

    def cursor(self, dictionary=False):
        return Cursor(self._conn, dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        pass  # keep the in-memory DB alive across route calls in tests
