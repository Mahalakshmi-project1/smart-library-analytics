"""Run:  python -m unittest discover -s tests -v   (no MySQL needed)

Exercises the real analytics SQL on an SQLite stand-in (see sqlite_shim.py), the pandas
transformations, the ETL pipeline, the CSV exports and the Flask routes.
"""
import csv
import io
import json
import sys
import types
import unittest
from datetime import date
from decimal import Decimal

# the app imports mysql.connector at import time; tests never connect to MySQL
fake_mysql = types.ModuleType("mysql")
fake_connector = types.ModuleType("mysql.connector")
fake_connector.connect = lambda **kw: (_ for _ in ()).throw(RuntimeError("no MySQL in tests"))
fake_mysql.connector = fake_connector
sys.modules.setdefault("mysql", fake_mysql)
sys.modules.setdefault("mysql.connector", fake_connector)

import pandas as pd  # noqa: E402

from analytics import queries as q  # noqa: E402
from analytics import reports  # noqa: E402
from analytics import transformations as tf  # noqa: E402
from analytics.etl import run_etl  # noqa: E402
from tests.sqlite_shim import Connection  # noqa: E402

TODAY = date(2026, 10, 7)
THIS_YEAR = reports.resolve_range("this_year", today=TODAY)


def make_db():
    conn = Connection()
    c = conn.cursor()
    c.executemany("INSERT INTO students (student_id,name,department,year,email,phone) VALUES (%s,%s,%s,%s,%s,%s)", [
        (1, "Asha", "ECE", 2, "asha@x.com", "9876543210"),
        (2, "Ben", "ECE", 3, "ben@x.com", "9876543211"),
        (3, "Cara", "CSE", 1, "cara@x.com", "9876543212"),
        (4, "Dup1", "CSE", 1, "dup@x.com", "9876543213"),
        (5, "Dup2", "CSE", 1, "DUP@x.com ", "9876543214"),
        (6, "Blank", "", 1, "bad-email", "123"),
    ])
    c.executemany("INSERT INTO books (book_id,title,author,category,quantity,status) VALUES (%s,%s,%s,%s,%s,%s)", [
        (1, "Alpha", "A", "X", 1, "Available"),
        (2, "Beta", "B", "X", 1, "Issued"),
        (3, "Gamma", "C", "Y", 1, "Issued"),
        (4, "Delta", "D", "Y", 0, "Issued"),     # qty 0 AND Issued with no loan
    ])
    c.executemany("""INSERT INTO issued_books (issue_id,book_id,student_id,issue_date,due_date,return_date,fine,status)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", [
        (1, 1, 1, "2026-08-01", "2026-08-15", "2026-08-10", 0, "Returned"),
        (2, 1, 2, "2026-09-01", "2026-09-15", "2026-09-20", 25, "Returned"),
        (3, 2, 1, "2026-09-05", "2026-09-19", "2026-09-25", 30, "Returned"),
        (4, 3, 3, "2026-09-25", "2026-10-09", None, 0, "Issued"),
        (5, 2, 1, "2026-09-28", "2026-10-02", None, 0, "Issued"),   # overdue 5 days
        (6, 1, 3, "2025-12-20", "2026-01-03", "2025-12-30", 0, "Returned"),  # last year
        (7, 1, 2, "2026-07-10", "2026-07-01", "2026-07-12", 55, "Returned"),  # due < issue
    ])
    conn.commit()
    return conn


class DateRangeTests(unittest.TestCase):
    def r(self, *a, **k):
        return reports.resolve_range(*a, today=TODAY, **k)

    def test_presets(self):
        self.assertEqual((self.r("today")["start"], self.r("today")["end"]), (TODAY, TODAY))
        self.assertEqual(self.r("last_7_days")["start"], date(2026, 10, 1))
        self.assertEqual(self.r("last_30_days")["start"], date(2026, 9, 8))
        self.assertEqual(self.r("this_month")["start"], date(2026, 10, 1))
        self.assertEqual(self.r("this_year")["start"], date(2026, 1, 1))

    def test_custom_valid(self):
        r = self.r("custom", "2026-03-01", "2026-04-15")
        self.assertEqual((r["start"], r["end"], r["warning"]), (date(2026, 3, 1), date(2026, 4, 15), None))

    def test_custom_invalid_falls_back(self):
        for s, e in [("2026-05-01", "2026-04-01"), ("nope", "2026-04-01"), ("", "")]:
            r = self.r("custom", s, e)
            self.assertEqual(r["preset"], "this_year")
            self.assertTrue(r["warning"])

    def test_unknown_preset_defaults(self):
        self.assertEqual(self.r("garbage")["preset"], "this_year")
        self.assertEqual(self.r(None)["preset"], "this_year")


class DashboardSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = make_db()
        cls.cur = cls.conn.cursor(dictionary=True)
        cls.data = reports.build_dashboard(cls.cur, THIS_YEAR, TODAY)

    def test_kpis(self):
        k = self.data["kpis"]
        self.assertEqual(k["total_books"], 4)
        self.assertEqual(k["total_students"], 6)
        self.assertEqual(k["total_issues"], 6)          # 2025 loan excluded by range
        self.assertEqual(k["total_returns"], 4)
        self.assertEqual(k["currently_issued"], 2)
        self.assertEqual(k["overdue_books"], 1)
        self.assertEqual(k["fine_collected"], 110)
        self.assertEqual(k["fine_accruing"], 25)
        self.assertEqual(k["availability_rate"], 25.0)
        self.assertEqual(k["return_rate"], 66.7)
        self.assertEqual(k["overdue_rate"], 50.0)
        self.assertEqual(k["most_borrowed_book"]["title"], "Alpha")
        self.assertEqual(k["most_borrowed_book"]["times_issued"], 3)
        self.assertEqual(k["most_active_student"]["name"], "Asha")

    def test_date_filter_changes_numbers(self):
        rng = reports.resolve_range("custom", "2025-12-01", "2025-12-31", TODAY)
        d = reports.build_dashboard(self.cur, rng, TODAY)
        self.assertEqual(d["kpis"]["total_issues"], 1)
        self.assertEqual(d["kpis"]["total_returns"], 1)
        self.assertEqual(d["charts"]["monthly_issues"]["labels"], ["2025-12"])

    def test_empty_range_is_safe(self):
        rng = reports.resolve_range("custom", "2020-01-01", "2020-01-31", TODAY)
        d = reports.build_dashboard(self.cur, rng, TODAY)
        self.assertEqual(d["kpis"]["total_issues"], 0)
        self.assertEqual(d["kpis"]["return_rate"], 0.0)
        self.assertIsNone(d["kpis"]["most_borrowed_book"])
        self.assertEqual(sum(d["charts"]["monthly_issues"]["values"]), 0)

    def test_monthly_trends_gap_filled(self):
        ch = self.data["charts"]
        self.assertEqual(ch["monthly_issues"]["labels"][0], "2026-01")
        self.assertEqual(len(ch["monthly_issues"]["labels"]), 10)
        by_month = dict(zip(ch["monthly_issues"]["labels"], ch["monthly_issues"]["values"]))
        self.assertEqual((by_month["2026-07"], by_month["2026-08"], by_month["2026-09"], by_month["2026-02"]),
                         (1, 1, 4, 0))
        rets = dict(zip(ch["monthly_returns"]["labels"], ch["monthly_returns"]["values"]))
        fines = dict(zip(ch["fine_trend"]["labels"], ch["fine_trend"]["values"]))
        self.assertEqual((rets["2026-07"], rets["2026-08"], rets["2026-09"]), (1, 1, 2))
        self.assertEqual((fines["2026-07"], fines["2026-09"]), (55, 55))

    def test_breakdowns(self):
        ch = self.data["charts"]
        self.assertEqual(dict(zip(ch["department_borrowing"]["labels"], ch["department_borrowing"]["values"])),
                         {"ECE": 5, "CSE": 1})
        self.assertEqual(ch["availability"], {"labels": ["Available", "Issued"], "values": [1, 3]})
        self.assertEqual(dict(zip(ch["books_by_category"]["labels"], ch["books_by_category"]["values"])),
                         {"X": 2, "Y": 2})
        self.assertEqual(ch["top_books"]["labels"][:3], ["Alpha", "Beta", "Gamma"])
        self.assertEqual(ch["top_students"]["values"][:3], [3, 2, 1])

    def test_tables(self):
        t = self.data["tables"]
        self.assertEqual([r["title"] for r in t["overdue_now"]], ["Beta"])
        self.assertEqual(t["overdue_now"][0]["days_overdue"], 5)
        self.assertEqual(t["overdue_now"][0]["fine_accruing"], 25)
        self.assertEqual([r["name"] for r in t["frequent_late"]], ["Ben"])   # HAVING >= 2

    def test_payload_is_json_serialisable(self):
        json.dumps(self.data)


class DataQualityTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.cur = self.conn.cursor(dictionary=True)

    def counts(self):
        dq = reports.build_data_quality(self.cur, TODAY)
        return dq, {c["key"]: c["count"] for c in dq["checks"]}

    def test_detects_each_problem(self):
        dq, n = self.counts()
        self.assertEqual(n["students_missing_values"], 1)
        self.assertEqual(n["books_missing_values"], 0)
        self.assertEqual(n["duplicate_emails"], 1)
        self.assertEqual(n["invalid_contacts"], 1)
        self.assertEqual(n["invalid_dates"], 1)
        self.assertEqual(n["bad_quantity"], 1)
        self.assertEqual(n["inconsistent_book_status"], 1)
        self.assertEqual(n["inconsistent_issue_records"], 0)
        self.assertEqual(n["double_issued_books"], 0)
        self.assertEqual(n["fine_mismatch"], 0)
        self.assertEqual(n["overdue_books"], 1)
        self.assertEqual(n["unreturned_books"], 2)
        self.assertEqual(n["etl_reconciliation"], 1)      # ETL never run
        self.assertEqual(dq["summary"]["graded_checks"], 11)

    def test_detects_record_level_inconsistencies(self):
        c = self.conn.cursor()
        c.execute("UPDATE issued_books SET return_date = NULL WHERE issue_id = 1")           # Returned, no date
        c.execute("UPDATE issued_books SET fine = 99 WHERE issue_id = 2")                     # wrong fine
        c.execute("""INSERT INTO issued_books (book_id,student_id,issue_date,due_date,fine,status)
                     VALUES (3, 1, '2026-10-01', '2026-10-15', 0, 'Issued')""")               # book 3 twice
        self.conn.commit()
        _, n = self.counts()
        self.assertEqual(n["inconsistent_issue_records"], 1)
        self.assertEqual(n["fine_mismatch"], 1)
        self.assertEqual(n["double_issued_books"], 1)

    def test_clean_after_etl_reconciles(self):
        run_etl(self.conn, TODAY)
        _, n = self.counts()
        self.assertEqual(n["etl_reconciliation"], 0)   # difference fully explained by 1 rejected row


class TransformationTests(unittest.TestCase):
    def test_validate_contacts(self):
        bad = tf.validate_contacts([
            {"student_id": 1, "name": "ok", "email": "a@b.com", "phone": "98765 43210"},
            {"student_id": 2, "name": "e", "email": "nope", "phone": "9876543210"},
            {"student_id": 3, "name": "p", "email": "a@b.co", "phone": "12-34"},
            {"student_id": 4, "name": "both", "email": "x", "phone": "1"},
            {"student_id": 5, "name": "blank", "email": None, "phone": None},
            {"student_id": 6, "name": "intl", "email": "a@b.com", "phone": "+91 98765-43210"},
        ])
        self.assertEqual(list(bad["student_id"]), [2, 3, 4])
        self.assertIn("email", bad.loc[bad.student_id == 4, "issue"].iloc[0])
        self.assertIn("phone", bad.loc[bad.student_id == 4, "issue"].iloc[0])

    def test_fill_months(self):
        out = tf.fill_months([{"ym": "2026-02", "n": 3}], date(2026, 1, 15), date(2026, 3, 2), ["n"])
        self.assertEqual(out, {"labels": ["2026-01", "2026-02", "2026-03"], "n": [0, 3, 0]})
        self.assertEqual(tf.fill_months([], date(2026, 1, 1), date(2026, 1, 31), ["n"])["n"], [0])

    def test_canonical_labels(self):
        s = pd.Series(["CSE", "cse ", " CSE", None, "", "Ece"])
        out = list(tf.canonical_labels(s, "Unknown"))
        self.assertEqual(out, ["CSE", "CSE", "CSE", "Unknown", "Unknown", "Ece"])

    def test_to_native_and_jsonable(self):
        df = pd.DataFrame({"a": [1, 2], "b": [1.5, float("nan")], "c": pd.to_datetime(["2026-01-01", None])})
        rows = tf.to_native(df)
        self.assertEqual(rows[0], (1, 1.5, date(2026, 1, 1)))
        self.assertEqual(rows[1], (2, None, None))
        self.assertTrue(all(type(v) in (int, float, date, type(None)) for r in rows for v in r))
        self.assertEqual(tf.jsonable({"d": Decimal("2.50"), "i": Decimal("3"), "t": date(2026, 1, 2)}),
                         {"d": 2.5, "i": 3, "t": "2026-01-02"})

    def test_prepare_export_cleans_mysql_style_values(self):
        rows = [{"a": Decimal("1.50"), "d": date(2026, 1, 2), "n": None, "s": " x "},
                {"a": Decimal("2.00"), "d": None, "n": 3, "s": "y"}]
        df = tf.prepare_export(rows, ["d"])
        self.assertEqual(df.to_dict("records"),
                         [{"a": 1.5, "d": "2026-01-02", "n": "", "s": "x"},
                          {"a": 2.0, "d": "", "n": 3, "s": "y"}])
        self.assertTrue(tf.to_csv_bytes(df).startswith(b"\xef\xbb\xbf"))

    def test_etl_transform_with_mysql_style_types(self):
        """MySQL returns datetime.date objects and Decimal fines (SQLite returns text)."""
        from analytics import etl
        issues = [
            {"issue_id": 1, "book_id": 1, "student_id": 1, "issue_date": date(2026, 9, 1),
             "due_date": date(2026, 9, 15), "return_date": date(2026, 9, 20),
             "fine": Decimal("25.00"), "status": "Returned", "category": "X"},
            {"issue_id": 2, "book_id": 2, "student_id": 2, "issue_date": date(2026, 9, 28),
             "due_date": date(2026, 10, 2), "return_date": None,
             "fine": Decimal("0.00"), "status": "Issued", "category": None},
        ]
        books = pd.DataFrame([(1, "A", "a", "X"), (2, "B", "b", None)],
                             columns=["book_id", "title", "author", "category"])
        students = pd.DataFrame([(1, "cse"), (2, "CSE ")], columns=["student_id", "department"])
        stamp = pd.Timestamp("2026-10-07 10:30:00").to_pydatetime()
        res = etl.transform(issues, books, students, TODAY, stamp)
        dept = tf.to_native(res["department"])
        self.assertEqual(dept[0][:3], ("CSE", 2, 2))                    # 'cse' / 'CSE ' merged
        self.assertEqual(dept[0][-1], stamp)                            # time of day preserved
        book_rows = tf.to_native(res["books"])
        self.assertEqual(book_rows[1][3], "Uncategorized")
        self.assertIsNone(book_rows[1][8])                              # avg_loan_days NaN -> NULL
        self.assertEqual(book_rows[0][9], date(2026, 9, 1))            # DATE stays a date
        for row in tf.to_native(res["monthly"]) + dept + book_rows:
            self.assertTrue(all(type(v).__module__ != "numpy" for v in row))

    def test_pct(self):
        self.assertEqual(tf.pct(1, 3), 33.3)
        self.assertEqual(tf.pct(5, 0), 0.0)


class EtlTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.stats = run_etl(self.conn, TODAY)
        self.cur = self.conn.cursor(dictionary=True)

    def rows(self, sql):
        self.cur.execute(sql)
        return self.cur.fetchall()

    def test_stats_and_log(self):
        self.assertEqual(self.stats["source_rows"], 7)
        self.assertEqual(self.stats["rejected_rows"], 1)
        log = self.rows("SELECT * FROM etl_run_log")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["status"], "SUCCESS")

    def test_monthly_table(self):
        m = {r["month"]: r for r in self.rows("SELECT * FROM monthly_library_stats")}
        self.assertEqual(len(m), 10)                    # 2025-12 .. 2026-09, gaps filled
        self.assertEqual(m["2026-03"]["books_issued"], 0)
        sep = m["2026-09"]
        self.assertEqual((sep["books_issued"], sep["books_returned"], sep["late_returns"]), (4, 2, 2))
        self.assertEqual(sep["fine_collected"], 55)
        self.assertEqual(sep["return_rate_pct"], 50.0)
        self.assertEqual(sep["avg_loan_days"], 19.5)

    def test_department_table(self):
        d = {r["department"]: r for r in self.rows("SELECT * FROM department_library_stats")}
        self.assertEqual(set(d), {"ECE", "CSE", "Unknown"})
        self.assertEqual(d["ECE"]["total_students"], 2)
        self.assertEqual(d["ECE"]["total_issues"], 4)
        self.assertEqual((d["ECE"]["overdue_open"], d["ECE"]["fine_collected"]), (1, 55))
        self.assertEqual(d["Unknown"]["total_issues"], 0)

    def test_book_table(self):
        b = {r["title"]: r for r in self.rows("SELECT * FROM book_borrowing_stats")}
        self.assertEqual(len(b), 4)
        self.assertEqual((b["Alpha"]["times_issued"], b["Alpha"]["popularity_rank"]), (3, 1))
        self.assertEqual(b["Alpha"]["total_fine"], 25)
        self.assertEqual(round(b["Alpha"]["avg_loan_days"], 2), 12.67)
        self.assertEqual((b["Delta"]["times_issued"], b["Delta"]["popularity_rank"]), (0, 4))
        self.assertEqual(b["Alpha"]["last_issued_date"], "2026-09-01")

    def test_rerun_is_idempotent(self):
        run_etl(self.conn, TODAY)
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM book_borrowing_stats")[0]["n"], 4)
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM etl_run_log")[0]["n"], 2)

    def test_failure_rolls_back_and_logs(self):
        before = self.rows("SELECT COUNT(*) AS n FROM monthly_library_stats")[0]["n"]
        self.conn._conn.execute("DROP TABLE department_library_stats")   # break the load step
        with self.assertRaises(Exception):
            run_etl(self.conn, TODAY)
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM monthly_library_stats")[0]["n"], before)
        last = self.rows("SELECT status FROM etl_run_log ORDER BY run_id DESC LIMIT 1")[0]
        self.assertEqual(last["status"], "FAILED")

    def test_empty_database(self):
        empty = Connection()
        stats = run_etl(empty, TODAY)
        self.assertEqual((stats["source_rows"], stats["monthly_rows"], stats["book_rows"]), (0, 0, 0))


def parse_csv(payload):
    text = payload.decode("utf-8")
    assert text.startswith("\ufeff"), "CSV must start with a UTF-8 BOM for Excel"
    return list(csv.DictReader(io.StringIO(text[1:])))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def export(self, name, rng=THIS_YEAR):
        return reports.export_dataset(self.conn, name, rng, TODAY)

    def test_every_export_works(self):
        for spec in reports.EXPORTS:
            filename, payload = self.export(spec["name"])
            self.assertTrue(filename.endswith(".csv"))
            self.assertGreater(len(parse_csv(payload)), 0, spec["name"])

    def test_issue_return_fact_table(self):
        rows = parse_csv(self.export("issue_return")[1])
        self.assertEqual(len(rows), 6)
        r5 = next(r for r in rows if r["issue_id"] == "5")
        self.assertEqual((r5["overdue_days"], r5["is_overdue_open"], r5["return_date"]), ("5", "1", ""))
        r2 = next(r for r in rows if r["issue_id"] == "2")
        self.assertEqual((r2["issue_date"], r2["overdue_days"], r2["fine_charged"], r2["issue_month"]),
                         ("2026-09-01", "5", "25", "2026-09"))
        self.assertEqual(r2["loan_days"], "19")
        self.assertEqual(r2["department"], "ECE")

    def test_date_range_applies_to_export(self):
        rng = reports.resolve_range("custom", "2025-12-01", "2025-12-31", TODAY)
        self.assertEqual(len(parse_csv(self.export("issue_return", rng)[1])), 1)

    def test_fine_report(self):
        rows = parse_csv(self.export("fine_report")[1])
        self.assertEqual(sorted(r["issue_id"] for r in rows), ["2", "3", "5", "7"])
        r5 = next(r for r in rows if r["issue_id"] == "5")
        self.assertEqual((r5["fine_collected"], r5["fine_accruing"]), ("0", "25"))

    def test_summary_exports_refresh_etl(self):
        _, payload = self.export("monthly_analytics")
        self.assertEqual(len(parse_csv(payload)), 10)
        self.assertEqual(len(parse_csv(self.export("department_analytics")[1])), 3)
        books = parse_csv(self.export("book_borrowing_analytics")[1])
        self.assertEqual(books[0]["title"], "Alpha")

    def test_unknown_export(self):
        with self.assertRaises(KeyError):
            self.export("passwords")


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import analytics_routes
        import app as app_module
        cls.conn = make_db()
        analytics_routes.get_db_connection = lambda: cls.conn
        app_module.get_db_connection = lambda: cls.conn
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def login(self):
        with self.client.session_transaction() as s:
            s["user_id"] = 1
            s["user_name"] = "Tester"

    ALL = "preset=custom&start=2025-01-01&end=2030-12-31"

    def test_login_required(self):
        anon = self.__class__.client.application.test_client()
        for url in ("/analytics/", "/analytics/data-quality", "/analytics/exports",
                    "/analytics/export/books", "/analytics/api/dashboard"):
            r = anon.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])

    def test_dashboard_page(self):
        self.login()
        r = self.client.get("/analytics/?" + self.ALL)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for text in ("Analytics Dashboard", "Most Borrowed Book", "Alpha", "Monthly Book Issue Trend",
                     "Top 10 Active Students", "Overdue Right Now", "Available vs Issued Books"):
            self.assertIn(text, html)

    def test_dashboard_presets_and_bad_custom(self):
        self.login()
        for p in ("today", "last_7_days", "last_30_days", "this_month", "this_year"):
            self.assertEqual(self.client.get(f"/analytics/?preset={p}").status_code, 200, p)
        r = self.client.get("/analytics/?preset=custom&start=2026-05-01&end=2026-01-01")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Custom range needs a valid", r.get_data(as_text=True))

    def test_api_json(self):
        self.login()
        r = self.client.get("/analytics/api/dashboard?" + self.ALL)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["kpis"]["total_books"], 4)
        self.assertEqual(body["kpis"]["total_issues"], 7)
        self.assertEqual(self.client.get("/analytics/api/data-quality").get_json()["summary"]["graded_checks"], 11)

    def test_data_quality_and_exports_pages(self):
        self.login()
        html = self.client.get("/analytics/data-quality").get_data(as_text=True)
        self.assertIn("Duplicate student emails", html)
        self.assertIn("Quality score", html)
        html = self.client.get("/analytics/exports").get_data(as_text=True)
        for spec in reports.EXPORTS:
            self.assertIn(f"/analytics/export/{spec['name']}", html)

    def test_csv_download_and_etl_button(self):
        self.login()
        r = self.client.get("/analytics/export/books")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("attachment; filename=library_books_", r.headers["Content-Disposition"])
        self.assertEqual(self.client.get("/analytics/export/nope").status_code, 302)
        r = self.client.post("/analytics/etl/run")
        self.assertEqual(r.status_code, 302)
        html = self.client.get("/analytics/exports").get_data(as_text=True)
        self.assertIn("SUCCESS", html)

    def test_database_failure_is_handled(self):
        import analytics_routes
        self.login()
        good = analytics_routes.get_db_connection
        analytics_routes.get_db_connection = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            r = self.client.get("/analytics/")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Unable to load analytics", r.get_data(as_text=True))
            self.assertEqual(self.client.get("/analytics/api/dashboard").status_code, 500)
        finally:
            analytics_routes.get_db_connection = good

    def test_legacy_reports_page_renders_summary(self):
        self.login()
        r = self.client.get("/reports")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Total Transactions", html)
        self.assertIn("Alpha", html)


class SeedDataTests(unittest.TestCase):
    def test_generated_dataset_is_consistent(self):
        import seed_data
        d = seed_data.generate_dataset(TODAY)
        self.assertGreater(len(d["issues"]), 300)
        open_by_book = {}
        last_end = {}
        for b, s, issue, due, ret, fine, status in sorted(d["issues"], key=lambda r: (r[0], r[2])):
            self.assertLessEqual(issue, due)
            if status == "Issued":
                self.assertIsNone(ret)
                self.assertNotIn(b, open_by_book)
                open_by_book[b] = True
            else:
                self.assertGreaterEqual(ret, issue)
                self.assertLessEqual(ret, TODAY)
                self.assertEqual(fine, max((ret - due).days, 0) * 5)
            self.assertGreater(issue, last_end.get(b, date.min) if b in last_end else date.min)
            last_end[b] = ret or TODAY
            self.assertLessEqual(issue, TODAY)
        self.assertEqual(seed_data.generate_dataset(TODAY), d)    # deterministic

    def test_seed_through_dashboard(self):
        """Load the generated data into the SQLite stand-in and run the full dashboard."""
        import seed_data
        d = seed_data.generate_dataset(TODAY)
        conn = Connection()
        c = conn.cursor()
        c.executemany("INSERT INTO students (name,department,year,email,phone) VALUES (%s,%s,%s,%s,%s)", d["students"])
        c.executemany("INSERT INTO books (title,author,category,quantity,status) VALUES (%s,%s,%s,%s,'Available')",
                      [tuple(b) for b in d["books"]])
        c.executemany("""INSERT INTO issued_books (book_id,student_id,issue_date,due_date,return_date,fine,status)
                         VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                      [(b + 1, s + 1, i, du, r, f, st) for b, s, i, du, r, f, st in d["issues"]])
        for b, *_rest, st in d["issues"]:
            if st == "Issued":
                c.execute("UPDATE books SET status='Issued' WHERE book_id=%s", (b + 1,))
        conn.commit()
        cur = conn.cursor(dictionary=True)
        rng = reports.resolve_range("this_year", today=TODAY)
        dash = reports.build_dashboard(cur, rng, TODAY)
        self.assertGreater(dash["kpis"]["total_issues"], 100)
        self.assertEqual(dash["kpis"]["total_books"], len(d["books"]))
        dq = reports.build_data_quality(cur, TODAY)
        failing = {c["key"] for c in dq["checks"] if c["severity"] != "info" and c["count"]}
        self.assertEqual(failing, {"etl_reconciliation"})      # clean demo data, ETL not run yet
        run_etl(conn, TODAY)
        dq = reports.build_data_quality(cur, TODAY)
        self.assertEqual(dq["summary"]["score_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
