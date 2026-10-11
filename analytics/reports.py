"""Reporting layer: turns query results into the payloads the web pages, the JSON
API and the CSV exports consume. No SQL text lives here (see queries.py)."""
from datetime import date, datetime, timedelta

from analytics import queries as q
from analytics import transformations as tf
from analytics.etl import run_etl

PRESETS = [
    ("today", "Today"),
    ("last_7_days", "Last 7 Days"),
    ("last_30_days", "Last 30 Days"),
    ("this_month", "This Month"),
    ("this_year", "This Year"),
    ("custom", "Custom Range"),
]
DEFAULT_PRESET = "this_year"
LABELS = dict(PRESETS)


# --------------------------------------------------------------------------
# date-range filter
# --------------------------------------------------------------------------
def resolve_range(preset=None, start=None, end=None, today=None):
    """Turn the filter controls into an inclusive [start, end] date range.

    Always returns a usable range; problems (bad custom dates) are reported in
    'warning' and the default preset is used instead.
    """
    today = today or date.today()
    preset = preset if preset in LABELS else DEFAULT_PRESET
    warning = None

    if preset == "custom":
        try:
            s = datetime.strptime((start or "").strip(), "%Y-%m-%d").date()
            e = datetime.strptime((end or "").strip(), "%Y-%m-%d").date()
            if s > e:
                raise ValueError("start after end")
            return {"preset": "custom", "label": f"{s:%d %b %Y} – {e:%d %b %Y}",
                    "start": s, "end": e, "warning": None}
        except ValueError:
            warning = ("Custom range needs a valid start and end date (YYYY-MM-DD) "
                       "with start on or before end. Showing This Year instead.")
            preset = DEFAULT_PRESET

    if preset == "today":
        s = e = today
    elif preset == "last_7_days":
        s, e = today - timedelta(days=6), today
    elif preset == "last_30_days":
        s, e = today - timedelta(days=29), today
    elif preset == "this_month":
        s, e = today.replace(day=1), today
    else:  # this_year
        s, e = today.replace(month=1, day=1), today
    return {"preset": preset, "label": LABELS[preset], "start": s, "end": e, "warning": warning}


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------
def build_dashboard(cursor, rng, today=None):
    today = today or date.today()
    start, end = rng["start"], rng["end"]

    snap = q.snapshot_kpis(cursor, today)
    period = q.period_kpis(cursor, start, end)
    top_books = q.top_books(cursor, start, end)
    top_students = q.top_students(cursor, start, end)

    kpis = {
        "total_books": snap["total_books"],
        "total_students": snap["total_students"],
        "total_issues": period["total_issues"],
        "total_returns": period["total_returns"],
        "currently_issued": snap["currently_issued"],
        "overdue_books": snap["overdue_books"],
        "fine_collected": period["fine_collected"],
        "fine_accruing": snap["fine_accruing"],
        "active_borrowers": period["active_borrowers"],
        "avg_loan_days": round(float(period["avg_loan_days"] or 0), 1),
        "avg_fine_per_late_return": round(float(period["avg_fine_per_late_return"] or 0), 2),
        "availability_rate": tf.pct(snap["available_books"], snap["total_books"]),
        "return_rate": tf.pct(period["issues_returned"], period["total_issues"]),
        "overdue_rate": tf.pct(snap["overdue_books"], snap["currently_issued"]),
        "most_borrowed_book": top_books[0] if top_books else None,
        "most_active_student": top_students[0] if top_students else None,
    }

    issues_ts = tf.fill_months(q.monthly_issues(cursor, start, end), start, end, ["issue_count"])
    returns_ts = tf.fill_months(q.monthly_returns(cursor, start, end), start, end,
                                ["return_count", "fine_collected"])
    status = {r["book_status"]: r["book_count"] for r in q.book_status_counts(cursor)}
    categories = q.books_by_category(cursor)
    authors = q.top_authors(cursor)
    depts = q.department_borrowing(cursor, start, end)

    charts = {
        "monthly_issues": {"labels": issues_ts["labels"], "values": issues_ts["issue_count"]},
        "monthly_returns": {"labels": returns_ts["labels"], "values": returns_ts["return_count"]},
        "fine_trend": {"labels": returns_ts["labels"], "values": returns_ts["fine_collected"]},
        "books_by_category": {"labels": [r["category_name"] for r in categories],
                              "values": [r["titles"] for r in categories]},
        "top_authors": {"labels": [r["author_name"] for r in authors],
                        "values": [r["titles"] for r in authors]},
        "department_borrowing": {"labels": [r["dept_name"] for r in depts],
                                 "values": [r["issue_count"] for r in depts]},
        "availability": {"labels": ["Available", "Issued"],
                         "values": [status.get("Available", 0), status.get("Issued", 0)]},
        "top_books": {"labels": [r["title"] for r in top_books],
                      "values": [r["times_issued"] for r in top_books]},
        "top_students": {"labels": [r["name"] for r in top_students],
                         "values": [r["books_borrowed"] for r in top_students]},
    }
    tables = {
        "department_borrowing": depts,
        "overdue_now": q.overdue_now(cursor, today),
        "frequent_late": q.frequent_late_returners(cursor, start, end),
    }
    return tf.jsonable({
        "range": {"preset": rng["preset"], "label": rng["label"],
                  "start": start, "end": end},
        "as_of": today,
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
    })


def empty_dashboard(rng, today=None):
    """Safe fallback so the page still renders if the database is unreachable."""
    today = today or date.today()
    zero = {"labels": [], "values": []}
    kpis = {k: 0 for k in (
        "total_books", "total_students", "total_issues", "total_returns", "currently_issued",
        "overdue_books", "fine_collected", "fine_accruing", "active_borrowers", "avg_loan_days",
        "avg_fine_per_late_return", "availability_rate", "return_rate", "overdue_rate")}
    kpis.update(most_borrowed_book=None, most_active_student=None)
    return tf.jsonable({
        "range": {"preset": rng["preset"], "label": rng["label"],
                  "start": rng["start"], "end": rng["end"]},
        "as_of": today, "kpis": kpis,
        "charts": {k: dict(zero) for k in (
            "monthly_issues", "monthly_returns", "fine_trend", "books_by_category",
            "top_authors", "department_borrowing", "availability", "top_books", "top_students")},
        "tables": {"department_borrowing": [], "overdue_now": [], "frequent_late": []},
    })


# --------------------------------------------------------------------------
# data quality
# --------------------------------------------------------------------------
def _check_result(meta, count, sample):
    sample = tf.jsonable(sample)
    return {
        "key": meta["key"], "title": meta["title"], "description": meta["description"],
        "severity": meta["severity"], "count": count,
        "status": "pass" if count == 0 else meta["severity"],
        "columns": list(sample[0].keys()) if sample else [],
        "sample": sample,
    }


def build_data_quality(cursor, today=None):
    today = today or date.today()
    results = []
    for meta in q.DQ_CHECKS:
        count, sample = q.run_dq_check(cursor, meta, today)
        results.append(_check_result(meta, count, sample))
        if meta["key"] == "duplicate_emails":
            bad = tf.validate_contacts(q.student_contacts(cursor))
            results.append(_check_result(
                {"key": "invalid_contacts", "title": "Invalid student email / phone format",
                 "severity": "warning",
                 "description": "Email must look like name@domain.tld; phone must be 10-13 "
                                "digits (optional +) after removing spaces and dashes."},
                len(bad), bad.head(10).to_dict("records")))

    # ETL reconciliation: summary tables vs live SQL
    try:
        rec = q.reconcile_summary(cursor)
        etl_last = q.last_etl_run(cursor)
        diff = abs(int(rec["live_issues"]) - int(rec["summary_issues"])) + \
            abs(int(rec["live_returns"]) - int(rec["summary_returns"]))
        rejected = int(etl_last.get("rejected_rows", 0)) if etl_last else 0
        if not etl_last:
            diff, note = 1, "ETL has never been run - summary tables are empty."
        elif diff and diff <= rejected * 2 and rejected:
            note = "Difference explained by rows rejected during cleaning."
            diff = 0
        elif diff:
            note = "Summary tables are out of date - run the ETL job."
        else:
            note = "Summary tables match live SQL totals."
        results.append(_check_result(
            {"key": "etl_reconciliation", "title": "ETL summary tables vs live data",
             "severity": "warning", "description": note},
            diff, [{"live_issues": rec["live_issues"], "summary_issues": rec["summary_issues"],
                    "live_returns": rec["live_returns"], "summary_returns": rec["summary_returns"]}]
            if diff else []))
    except Exception as exc:  # summary tables missing on a not-yet-upgraded DB
        results.append(_check_result(
            {"key": "etl_reconciliation", "title": "ETL summary tables vs live data",
             "severity": "warning",
             "description": f"Summary tables unavailable ({exc}). Run python init_db.py."},
            1, []))

    graded = [r for r in results if r["severity"] != "info"]
    passed = sum(1 for r in graded if r["count"] == 0)
    return {
        "as_of": today.isoformat(),
        "checks": results,
        "summary": {
            "graded_checks": len(graded), "passed": passed,
            "failing": len(graded) - passed,
            "score_pct": tf.pct(passed, len(graded)),
            "errors": sum(1 for r in graded if r["status"] == "error"),
            "warnings": sum(1 for r in graded if r["status"] == "warning"),
            "open_loans": next((r["count"] for r in results if r["key"] == "unreturned_books"), 0),
            "overdue": next((r["count"] for r in results if r["key"] == "overdue_books"), 0),
        },
    }


# --------------------------------------------------------------------------
# CSV exports
# --------------------------------------------------------------------------
EXPORTS = [
    {"name": "books", "label": "Books", "sql": q.EXPORT_BOOKS_SQL, "source": "live",
     "uses_range": False, "dates": [],
     "grain": "one row per book title",
     "columns": "book_id, title, author, category, quantity, status, times_issued, currently_issued"},
    {"name": "students", "label": "Students", "sql": q.EXPORT_STUDENTS_SQL, "source": "live",
     "uses_range": False, "dates": [],
     "grain": "one row per student",
     "columns": "student_id, name, department, year, email, phone, total_issues, currently_issued"},
    {"name": "issue_return", "label": "Issue / Return", "sql": q.EXPORT_ISSUE_RETURN_SQL,
     "source": "live", "uses_range": True,
     "dates": ["issue_date", "due_date", "return_date"],
     "grain": "one row per issue transaction (fact table)",
     "columns": "issue_id, book/student keys + names, department, dates, status, loan_days, "
                "overdue_days, fine_charged, is_overdue_open, issue_month"},
    {"name": "fine_report", "label": "Fine Report", "sql": q.EXPORT_FINE_SQL, "source": "live",
     "uses_range": True, "dates": ["issue_date", "due_date", "return_date"],
     "grain": "one row per loan that has a fine or is overdue",
     "columns": "issue_id, student, department, book, dates, overdue_days, fine_collected, fine_accruing"},
    {"name": "monthly_analytics", "label": "Monthly Analytics", "sql": q.EXPORT_MONTHLY_SQL,
     "source": "summary", "uses_range": False, "dates": [],
     "grain": "one row per month (monthly_library_stats)",
     "columns": "month, books_issued, books_returned, unique_borrowers, late_returns, "
                "fine_collected, avg_loan_days, return_rate_pct, refreshed_at"},
    {"name": "department_analytics", "label": "Department Analytics",
     "sql": q.EXPORT_DEPARTMENT_SQL, "source": "summary", "uses_range": False, "dates": [],
     "grain": "one row per department (department_library_stats)",
     "columns": "department, total_students, active_borrowers, total_issues, total_returns, "
                "currently_issued, overdue_open, fine_collected, avg_issues_per_student"},
    {"name": "book_borrowing_analytics", "label": "Book Borrowing Analytics",
     "sql": q.EXPORT_BOOK_STATS_SQL, "source": "summary", "uses_range": False,
     "dates": ["last_issued_date"],
     "grain": "one row per book (book_borrowing_stats)",
     "columns": "book_id, title, author, category, times_issued, times_returned, currently_issued, "
                "total_fine, avg_loan_days, last_issued_date, popularity_rank"},
]
EXPORT_BY_NAME = {e["name"]: e for e in EXPORTS}


def export_dataset(connection, name, rng, today=None):
    """Return (filename, csv_bytes). Summary-table exports refresh the ETL first
    so the file is never stale."""
    spec = EXPORT_BY_NAME.get(name)
    if spec is None:
        raise KeyError(name)
    today = today or date.today()
    if spec["source"] == "summary":
        run_etl(connection, today)
    cursor = connection.cursor(dictionary=True)
    try:
        rows = q.export_rows(cursor, spec["sql"], rng["start"], rng["end"], today)
    finally:
        cursor.close()
    df = tf.prepare_export(rows, spec["dates"])
    if df.empty and not len(df.columns):
        df = tf.prepare_export([{"note": "no rows"}])
    suffix = f"_{rng['start']}_to_{rng['end']}" if spec["uses_range"] else ""
    return f"library_{name}{suffix}_{today:%Y%m%d}.csv", tf.to_csv_bytes(df)


def etl_status(cursor):
    try:
        return tf.jsonable(q.last_etl_run(cursor))
    except Exception:  # noqa: BLE001 - table may not exist yet
        return {}
