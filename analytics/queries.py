"""SQL analytics layer.

Rules used throughout:
* All heavy lifting (COUNT/SUM/AVG, GROUP BY, JOIN, CASE, HAVING, subqueries,
  DATE_FORMAT) happens in MySQL - Python only formats the results.
* Queries use NAMED parameters (%(name)s) - never string formatting - so they are
  safe from SQL injection and the "as-of" date is explicit and testable.
* DATE_FORMAT's format string is passed as a parameter (%(month_fmt)s = '%Y-%m')
  so the SQL text never contains a literal % - this behaves identically across
  mysql-connector versions, which treat '%%' differently.
* Every function takes a *dictionary* cursor.
"""
from config import FINE_PER_DAY


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
MONTH_FMT = "%Y-%m"


def run(cursor, sql, params=None):
    """Execute and return all rows (month_fmt is always supplied)."""
    merged = {"month_fmt": MONTH_FMT}
    if params:
        merged.update(params)
    cursor.execute(sql, merged)
    return cursor.fetchall()


def one(cursor, sql, params=None):
    rows = run(cursor, sql, params)
    return rows[0] if rows else {}


def _range_params(start, end):
    return {"start": start, "end": end}


DEPT_EXPR = "COALESCE(NULLIF(TRIM(s.department), ''), 'Unknown')"


# --------------------------------------------------------------------------
# KPI queries
# --------------------------------------------------------------------------
SNAPSHOT_KPI_SQL = """
SELECT
    (SELECT COUNT(*) FROM books)                                   AS total_books,
    (SELECT COUNT(*) FROM students)                                AS total_students,
    (SELECT COUNT(*) FROM books WHERE status = 'Available')        AS available_books,
    (SELECT COUNT(*) FROM books WHERE status = 'Issued')           AS issued_book_titles,
    (SELECT COUNT(*) FROM issued_books WHERE status = 'Issued')    AS currently_issued,
    (SELECT COUNT(*) FROM issued_books
      WHERE status = 'Issued' AND due_date < %(today)s)            AS overdue_books,
    (SELECT COALESCE(SUM(DATEDIFF(%(today)s, due_date)), 0) * %(fine_per_day)s
       FROM issued_books
      WHERE status = 'Issued' AND due_date < %(today)s)            AS fine_accruing
"""


def snapshot_kpis(cursor, today):
    """Point-in-time numbers (not affected by the date filter)."""
    return one(cursor, SNAPSHOT_KPI_SQL,
               {"today": today, "fine_per_day": FINE_PER_DAY})


ISSUE_PERIOD_SQL = """
SELECT
    COUNT(*)                                                           AS total_issues,
    COALESCE(SUM(CASE WHEN status = 'Returned' THEN 1 ELSE 0 END), 0)  AS issues_returned,
    COUNT(DISTINCT student_id)                                         AS active_borrowers
FROM issued_books
WHERE issue_date BETWEEN %(start)s AND %(end)s
"""

RETURN_PERIOD_SQL = """
SELECT
    COUNT(*)                                                       AS total_returns,
    COALESCE(SUM(fine), 0)                                         AS fine_collected,
    COALESCE(AVG(DATEDIFF(return_date, issue_date)), 0)            AS avg_loan_days,
    COALESCE(SUM(CASE WHEN fine > 0 THEN 1 ELSE 0 END), 0)         AS late_returns,
    COALESCE(AVG(CASE WHEN fine > 0 THEN fine END), 0)             AS avg_fine_per_late_return
FROM issued_books
WHERE status = 'Returned'
  AND return_date BETWEEN %(start)s AND %(end)s
"""


def period_kpis(cursor, start, end):
    """Numbers for the selected date range (issues by issue_date, returns/fines by return_date)."""
    p = _range_params(start, end)
    out = dict(one(cursor, ISSUE_PERIOD_SQL, p))
    out.update(one(cursor, RETURN_PERIOD_SQL, p))
    return out


# --------------------------------------------------------------------------
# trends (GROUP BY DATE_FORMAT)
# --------------------------------------------------------------------------
MONTHLY_ISSUES_SQL = """
SELECT DATE_FORMAT(issue_date, %(month_fmt)s) AS ym,
       COUNT(*)                           AS issue_count
FROM issued_books
WHERE issue_date BETWEEN %(start)s AND %(end)s
GROUP BY ym
ORDER BY ym
"""

MONTHLY_RETURNS_SQL = """
SELECT DATE_FORMAT(return_date, %(month_fmt)s) AS ym,
       COUNT(*)                            AS return_count,
       COALESCE(SUM(fine), 0)              AS fine_collected
FROM issued_books
WHERE status = 'Returned'
  AND return_date BETWEEN %(start)s AND %(end)s
GROUP BY ym
ORDER BY ym
"""


def monthly_issues(cursor, start, end):
    return run(cursor, MONTHLY_ISSUES_SQL, _range_params(start, end))


def monthly_returns(cursor, start, end):
    return run(cursor, MONTHLY_RETURNS_SQL, _range_params(start, end))


# --------------------------------------------------------------------------
# catalogue composition (snapshot)
# --------------------------------------------------------------------------
BOOKS_BY_CATEGORY_SQL = """
SELECT COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') AS category_name,
       COUNT(*)                                              AS titles,
       COALESCE(SUM(quantity), 0)                            AS copies
FROM books
GROUP BY category_name
ORDER BY titles DESC, category_name
"""

TOP_AUTHORS_SQL = """
SELECT TRIM(author) AS author_name,
       COUNT(*)     AS titles
FROM books
WHERE author IS NOT NULL AND TRIM(author) <> ''
GROUP BY author_name
ORDER BY titles DESC, author_name
LIMIT 10
"""

BOOK_STATUS_SQL = """
SELECT status AS book_status, COUNT(*) AS book_count
FROM books
GROUP BY book_status
ORDER BY book_count DESC
"""


def books_by_category(cursor):
    return run(cursor, BOOKS_BY_CATEGORY_SQL)


def top_authors(cursor):
    return run(cursor, TOP_AUTHORS_SQL)


def book_status_counts(cursor):
    return run(cursor, BOOK_STATUS_SQL)


# --------------------------------------------------------------------------
# rankings and breakdowns for the selected range
# --------------------------------------------------------------------------
TOP_BOOKS_SQL = """
SELECT b.book_id,
       b.title,
       b.author,
       COUNT(*) AS times_issued
FROM issued_books ib
JOIN books b ON b.book_id = ib.book_id
WHERE ib.issue_date BETWEEN %(start)s AND %(end)s
GROUP BY b.book_id, b.title, b.author
ORDER BY times_issued DESC, b.title ASC
LIMIT 10
"""

TOP_STUDENTS_SQL = f"""
SELECT s.student_id,
       s.name,
       {DEPT_EXPR}  AS dept_name,
       COUNT(*)     AS books_borrowed
FROM issued_books ib
JOIN students s ON s.student_id = ib.student_id
WHERE ib.issue_date BETWEEN %(start)s AND %(end)s
GROUP BY s.student_id, s.name, dept_name
ORDER BY books_borrowed DESC, s.name ASC
LIMIT 10
"""

DEPT_BORROWING_SQL = f"""
SELECT {DEPT_EXPR}                                              AS dept_name,
       COUNT(*)                                                 AS issue_count,
       COUNT(DISTINCT ib.student_id)                            AS borrowers,
       SUM(CASE WHEN ib.status = 'Issued' THEN 1 ELSE 0 END)    AS still_issued
FROM issued_books ib
JOIN students s ON s.student_id = ib.student_id
WHERE ib.issue_date BETWEEN %(start)s AND %(end)s
GROUP BY dept_name
ORDER BY issue_count DESC, dept_name
"""

# HAVING: only students who returned late at least twice in the period
FREQUENT_LATE_SQL = f"""
SELECT s.student_id,
       s.name,
       {DEPT_EXPR}      AS dept_name,
       COUNT(*)         AS late_returns,
       SUM(ib.fine)     AS total_fine
FROM issued_books ib
JOIN students s ON s.student_id = ib.student_id
WHERE ib.status = 'Returned'
  AND ib.fine > 0
  AND ib.return_date BETWEEN %(start)s AND %(end)s
GROUP BY s.student_id, s.name, dept_name
HAVING COUNT(*) >= 2
ORDER BY total_fine DESC, s.name ASC
LIMIT 10
"""

OVERDUE_NOW_SQL = """
SELECT ib.issue_id,
       b.title,
       s.name                                   AS student_name,
       ib.due_date,
       DATEDIFF(%(today)s, ib.due_date)         AS days_overdue,
       DATEDIFF(%(today)s, ib.due_date) * %(fine_per_day)s AS fine_accruing
FROM issued_books ib
JOIN books b    ON b.book_id = ib.book_id
JOIN students s ON s.student_id = ib.student_id
WHERE ib.status = 'Issued'
  AND ib.due_date < %(today)s
ORDER BY ib.due_date ASC, ib.issue_id ASC
LIMIT 10
"""


def top_books(cursor, start, end):
    return run(cursor, TOP_BOOKS_SQL, _range_params(start, end))


def top_students(cursor, start, end):
    return run(cursor, TOP_STUDENTS_SQL, _range_params(start, end))


def department_borrowing(cursor, start, end):
    return run(cursor, DEPT_BORROWING_SQL, _range_params(start, end))


def frequent_late_returners(cursor, start, end):
    return run(cursor, FREQUENT_LATE_SQL, _range_params(start, end))


def overdue_now(cursor, today):
    return run(cursor, OVERDUE_NOW_SQL,
               {"today": today, "fine_per_day": FINE_PER_DAY})


# --------------------------------------------------------------------------
# DATA QUALITY checks - each query lists the offending rows
# (reports.py wraps them in COUNT(*) / LIMIT for the indicators)
# --------------------------------------------------------------------------
# severity: error   = breaks integrity / numbers cannot be trusted
#           warning = data hygiene problem
#           info    = operational follow-up, not a data defect
DQ_CHECKS = [
    {
        "key": "books_missing_values",
        "title": "Books with missing values",
        "description": "Title or author is NULL/blank, or quantity is NULL.",
        "severity": "warning",
        "sql": """
            SELECT book_id, title, author, quantity
            FROM books
            WHERE title IS NULL OR TRIM(title) = ''
               OR author IS NULL OR TRIM(author) = ''
               OR quantity IS NULL
        """,
    },
    {
        "key": "students_missing_values",
        "title": "Students with missing values",
        "description": "Name, department, email or phone is NULL/blank.",
        "severity": "warning",
        "sql": """
            SELECT student_id, name, department, email, phone
            FROM students
            WHERE name IS NULL OR TRIM(name) = ''
               OR department IS NULL OR TRIM(department) = ''
               OR email IS NULL OR TRIM(email) = ''
               OR phone IS NULL OR TRIM(phone) = ''
        """,
    },
    {
        "key": "duplicate_emails",
        "title": "Duplicate student emails",
        "description": "Same email (case/space-insensitive) used by more than one student.",
        "severity": "error",
        "sql": """
            SELECT LOWER(TRIM(email)) AS email_key,
                   COUNT(*)           AS students_sharing
            FROM students
            WHERE email IS NOT NULL AND TRIM(email) <> ''
            GROUP BY email_key
            HAVING COUNT(*) > 1
        """,
    },
    {
        "key": "invalid_dates",
        "title": "Invalid or illogical dates",
        "description": "NULL dates, due/return date before issue date, or issue date in the future.",
        "severity": "error",
        "sql": """
            SELECT issue_id, book_id, student_id, issue_date, due_date, return_date
            FROM issued_books
            WHERE issue_date IS NULL OR due_date IS NULL
               OR due_date < issue_date
               OR return_date < issue_date
               OR issue_date > %(today)s
        """,
    },
    {
        "key": "bad_quantity",
        "title": "Zero or negative book quantity",
        "description": "quantity <= 0 (a CHECK constraint blocks this on new installs; "
                       "legacy rows may still violate it).",
        "severity": "error",
        "sql": """
            SELECT book_id, title, quantity
            FROM books
            WHERE quantity IS NOT NULL AND quantity <= 0
        """,
    },
    {
        "key": "inconsistent_book_status",
        "title": "Books with inconsistent status",
        "description": "Book marked Issued with no open loan, or Available while an open loan exists.",
        "severity": "error",
        "sql": """
            SELECT b.book_id, b.title, b.status AS book_status,
                   (SELECT COUNT(*) FROM issued_books ib
                     WHERE ib.book_id = b.book_id AND ib.status = 'Issued') AS open_loans
            FROM books b
            WHERE (b.status = 'Issued' AND NOT EXISTS (
                      SELECT 1 FROM issued_books ib
                       WHERE ib.book_id = b.book_id AND ib.status = 'Issued'))
               OR (b.status = 'Available' AND EXISTS (
                      SELECT 1 FROM issued_books ib
                       WHERE ib.book_id = b.book_id AND ib.status = 'Issued'))
        """,
    },
    {
        "key": "inconsistent_issue_records",
        "title": "Issue records with inconsistent status",
        "description": "Returned without a return date, or Issued but carrying a return date.",
        "severity": "error",
        "sql": """
            SELECT issue_id, book_id, student_id, status, return_date
            FROM issued_books
            WHERE (status = 'Returned' AND return_date IS NULL)
               OR (status = 'Issued'   AND return_date IS NOT NULL)
        """,
    },
    {
        "key": "double_issued_books",
        "title": "Books with more than one open loan",
        "description": "A single copy cannot be out with two students at once.",
        "severity": "error",
        "sql": """
            SELECT book_id, COUNT(*) AS open_loans
            FROM issued_books
            WHERE status = 'Issued'
            GROUP BY book_id
            HAVING COUNT(*) > 1
        """,
    },
    {
        "key": "fine_mismatch",
        "title": "Fines that do not match the fine rule",
        "description": "Returned loans where stored fine != overdue days x fine per day.",
        "severity": "warning",
        "sql": """
            SELECT issue_id, due_date, return_date, fine,
                   GREATEST(DATEDIFF(return_date, due_date), 0) * %(fine_per_day)s AS expected_fine
            FROM issued_books
            WHERE status = 'Returned'
              AND return_date IS NOT NULL
              AND fine <> GREATEST(DATEDIFF(return_date, due_date), 0) * %(fine_per_day)s
        """,
    },
    {
        "key": "overdue_books",
        "title": "Overdue books",
        "description": "Open loans past their due date.",
        "severity": "info",
        "sql": """
            SELECT ib.issue_id, b.title, s.name AS student_name, ib.due_date,
                   DATEDIFF(%(today)s, ib.due_date) AS days_overdue
            FROM issued_books ib
            JOIN books b    ON b.book_id = ib.book_id
            JOIN students s ON s.student_id = ib.student_id
            WHERE ib.status = 'Issued' AND ib.due_date < %(today)s
        """,
    },
    {
        "key": "unreturned_books",
        "title": "Unreturned books (all open loans)",
        "description": "Every loan that has not been returned yet, oldest first.",
        "severity": "info",
        "sql": """
            SELECT ib.issue_id, b.title, s.name AS student_name, ib.issue_date, ib.due_date
            FROM issued_books ib
            JOIN books b    ON b.book_id = ib.book_id
            JOIN students s ON s.student_id = ib.student_id
            WHERE ib.status = 'Issued'
        """,
    },
]

STUDENT_CONTACTS_SQL = """
SELECT student_id, name, email, phone
FROM students
"""


def student_contacts(cursor):
    return run(cursor, STUDENT_CONTACTS_SQL)


def run_dq_check(cursor, check, today):
    """Return (count, sample_rows) for one check using SQL COUNT(*) and LIMIT."""
    params = {"today": today, "fine_per_day": FINE_PER_DAY}
    count_sql = f"SELECT COUNT(*) AS n FROM ({check['sql']}) AS dq"
    sample_sql = f"SELECT * FROM ({check['sql']}) AS dq ORDER BY 1 LIMIT 10"
    count = one(cursor, count_sql, params).get("n", 0)
    sample = run(cursor, sample_sql, params)
    return int(count or 0), sample


# --------------------------------------------------------------------------
# ETL reconciliation: live SQL totals vs. summary tables
# --------------------------------------------------------------------------
RECONCILE_SQL = """
SELECT
    (SELECT COUNT(*) FROM issued_books)                                  AS live_issues,
    (SELECT COUNT(*) FROM issued_books WHERE status = 'Returned')        AS live_returns,
    (SELECT COALESCE(SUM(books_issued), 0)   FROM monthly_library_stats) AS summary_issues,
    (SELECT COALESCE(SUM(books_returned), 0) FROM monthly_library_stats) AS summary_returns,
    (SELECT COUNT(*) FROM monthly_library_stats)                         AS summary_months
"""


def reconcile_summary(cursor):
    return one(cursor, RECONCILE_SQL)


LAST_ETL_SQL = """
SELECT run_id, started_at, finished_at, status, source_rows, rejected_rows,
       monthly_rows, department_rows, book_rows, message
FROM etl_run_log
ORDER BY run_id DESC
LIMIT 1
"""


def last_etl_run(cursor):
    return one(cursor, LAST_ETL_SQL)


# --------------------------------------------------------------------------
# datasets for CSV export (analytics-ready, one row per grain)
# --------------------------------------------------------------------------
EXPORT_BOOKS_SQL = """
SELECT b.book_id, b.title, b.author,
       COALESCE(NULLIF(TRIM(b.category), ''), 'Uncategorized') AS category,
       b.quantity, b.status,
       (SELECT COUNT(*) FROM issued_books ib WHERE ib.book_id = b.book_id) AS times_issued,
       (SELECT COUNT(*) FROM issued_books ib
         WHERE ib.book_id = b.book_id AND ib.status = 'Issued')           AS currently_issued
FROM books b
ORDER BY b.book_id
"""

EXPORT_STUDENTS_SQL = f"""
SELECT s.student_id, s.name,
       {DEPT_EXPR} AS department,
       s.year, s.email, s.phone,
       (SELECT COUNT(*) FROM issued_books ib WHERE ib.student_id = s.student_id) AS total_issues,
       (SELECT COUNT(*) FROM issued_books ib
         WHERE ib.student_id = s.student_id AND ib.status = 'Issued')            AS currently_issued
FROM students s
ORDER BY s.student_id
"""

# one row per issue transaction; overdue_days / fine computed with CASE in SQL
EXPORT_ISSUE_RETURN_SQL = f"""
SELECT ib.issue_id, ib.book_id, b.title AS book_title, b.author,
       COALESCE(NULLIF(TRIM(b.category), ''), 'Uncategorized') AS category,
       ib.student_id, s.name AS student_name,
       {DEPT_EXPR} AS department,
       ib.issue_date, ib.due_date, ib.return_date, ib.status,
       CASE WHEN ib.return_date IS NOT NULL
            THEN DATEDIFF(ib.return_date, ib.issue_date) END AS loan_days,
       CASE WHEN ib.status = 'Returned'
            THEN GREATEST(DATEDIFF(ib.return_date, ib.due_date), 0)
            ELSE GREATEST(DATEDIFF(%(today)s, ib.due_date), 0) END AS overdue_days,
       ib.fine AS fine_charged,
       CASE WHEN ib.status = 'Issued' AND ib.due_date < %(today)s
            THEN 1 ELSE 0 END AS is_overdue_open,
       DATE_FORMAT(ib.issue_date, %(month_fmt)s) AS issue_month
FROM issued_books ib
JOIN books b    ON b.book_id = ib.book_id
JOIN students s ON s.student_id = ib.student_id
WHERE ib.issue_date BETWEEN %(start)s AND %(end)s
ORDER BY ib.issue_id
"""

EXPORT_FINE_SQL = f"""
SELECT ib.issue_id, s.student_id, s.name AS student_name,
       {DEPT_EXPR} AS department,
       b.title AS book_title, ib.issue_date, ib.due_date, ib.return_date, ib.status,
       CASE WHEN ib.status = 'Returned'
            THEN GREATEST(DATEDIFF(ib.return_date, ib.due_date), 0)
            ELSE GREATEST(DATEDIFF(%(today)s, ib.due_date), 0) END AS overdue_days,
       CASE WHEN ib.status = 'Returned' THEN ib.fine ELSE 0 END    AS fine_collected,
       CASE WHEN ib.status = 'Issued'
            THEN GREATEST(DATEDIFF(%(today)s, ib.due_date), 0) * %(fine_per_day)s
            ELSE 0 END                                              AS fine_accruing
FROM issued_books ib
JOIN books b    ON b.book_id = ib.book_id
JOIN students s ON s.student_id = ib.student_id
WHERE ib.issue_date BETWEEN %(start)s AND %(end)s
  AND (ib.fine > 0 OR (ib.status = 'Issued' AND ib.due_date < %(today)s))
ORDER BY ib.issue_id
"""

EXPORT_MONTHLY_SQL = "SELECT * FROM monthly_library_stats ORDER BY month"
EXPORT_DEPARTMENT_SQL = "SELECT * FROM department_library_stats ORDER BY total_issues DESC, department"
EXPORT_BOOK_STATS_SQL = "SELECT * FROM book_borrowing_stats ORDER BY popularity_rank, title"


def export_rows(cursor, sql, start=None, end=None, today=None):
    params = {"start": start, "end": end, "today": today, "fine_per_day": FINE_PER_DAY}
    return run(cursor, sql, params)
