"""ETL pipeline: transactional tables -> analytics summary tables.

    python etl.py            # run from the command line
    POST /analytics/etl/run  # or from the Exports page

EXTRACT   read books / students / issued_books from MySQL (SQL JOINs)
TRANSFORM clean labels, reject invalid rows, derive overdue days + fines,
          aggregate to monthly / department / book grain (pandas)
LOAD      DELETE + INSERT the three summary tables and write etl_run_log,
          all inside ONE transaction: readers never see a half-built table,
          and any error rolls everything back.
"""
from datetime import date, datetime

import pandas as pd

from analytics import transformations as tf

EXTRACT_ISSUES_SQL = """
SELECT ib.issue_id, ib.book_id, ib.student_id, ib.issue_date, ib.due_date,
       ib.return_date, ib.fine, ib.status,
       b.category
FROM issued_books ib
JOIN books b ON b.book_id = ib.book_id
"""
EXTRACT_BOOKS_SQL = "SELECT book_id, title, author, category FROM books"
EXTRACT_STUDENTS_SQL = "SELECT student_id, department FROM students"

INSERT_MONTHLY = """INSERT INTO monthly_library_stats
    (month, books_issued, books_returned, unique_borrowers, late_returns,
     fine_collected, avg_loan_days, return_rate_pct, refreshed_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
INSERT_DEPARTMENT = """INSERT INTO department_library_stats
    (department, total_students, active_borrowers, total_issues, total_returns,
     currently_issued, overdue_open, fine_collected, avg_issues_per_student, refreshed_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
INSERT_BOOKS = """INSERT INTO book_borrowing_stats
    (book_id, title, author, category, times_issued, times_returned, currently_issued,
     total_fine, avg_loan_days, last_issued_date, popularity_rank, refreshed_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
INSERT_LOG = """INSERT INTO etl_run_log
    (started_at, finished_at, status, source_rows, rejected_rows,
     monthly_rows, department_rows, book_rows, message)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""


def extract(cursor):
    cursor.execute(EXTRACT_ISSUES_SQL)
    issues = cursor.fetchall()
    cursor.execute(EXTRACT_BOOKS_SQL)
    books = pd.DataFrame(cursor.fetchall(), columns=["book_id", "title", "author", "category"])
    cursor.execute(EXTRACT_STUDENTS_SQL)
    students = pd.DataFrame(cursor.fetchall(), columns=["student_id", "department"])
    return issues, books, students


def transform(issues, books, students, today, refreshed_at):
    clean, rejected = tf.clean_issue_facts(issues, students, today)
    return {
        "clean_rows": len(clean),
        "rejected_rows": len(rejected),
        "monthly": tf.build_monthly_stats(clean, refreshed_at),
        "department": tf.build_department_stats(clean, students, refreshed_at),
        "books": tf.build_book_stats(clean, books, refreshed_at),
    }


def load(cursor, result):
    """Full refresh. Caller owns the transaction (commit / rollback)."""
    for table in ("monthly_library_stats", "department_library_stats", "book_borrowing_stats"):
        cursor.execute(f"DELETE FROM {table}")
    for sql, key in ((INSERT_MONTHLY, "monthly"), (INSERT_DEPARTMENT, "department"),
                     (INSERT_BOOKS, "books")):
        rows = tf.to_native(result[key])
        if rows:
            cursor.executemany(sql, rows)


def run_etl(connection, today=None):
    """Run the whole pipeline on an open connection. Returns a stats dict."""
    today = today or date.today()
    started = datetime.now().replace(microsecond=0)
    cursor = connection.cursor(dictionary=True)
    try:
        issues, books, students = extract(cursor)
        result = transform(issues, books, students, today, started)
        load(cursor, result)
        stats = {
            "source_rows": len(issues),
            "rejected_rows": result["rejected_rows"],
            "monthly_rows": len(result["monthly"]),
            "department_rows": len(result["department"]),
            "book_rows": len(result["books"]),
        }
        msg = (f"{result['rejected_rows']} invalid loan row(s) excluded"
               if result["rejected_rows"] else "OK")
        cursor.execute(INSERT_LOG, (started, datetime.now().replace(microsecond=0), "SUCCESS",
                                    stats["source_rows"], stats["rejected_rows"],
                                    stats["monthly_rows"], stats["department_rows"],
                                    stats["book_rows"], msg))
        connection.commit()
        return stats
    except Exception as exc:
        connection.rollback()
        try:
            cursor.execute(INSERT_LOG, (started, datetime.now().replace(microsecond=0),
                                        "FAILED", 0, 0, 0, 0, 0, str(exc)[:250]))
            connection.commit()
        except Exception:  # noqa: BLE001 - logging must never mask the real error
            connection.rollback()
        raise
    finally:
        cursor.close()
