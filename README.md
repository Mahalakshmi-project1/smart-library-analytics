# Smart Library Management & Analytics System

A Flask + MySQL library system with transactional workflows **and** a SQL-driven analytics layer:
interactive Chart.js dashboards, date-range filtering, an ETL job that builds analytics-ready
summary tables, a data-quality monitor and CSV exports for Excel / Power BI / Tableau / pandas.

> **Resume line:** Developed a Flask and MySQL based Library Management System with transactional
> workflows, SQL-driven analytics, automated reporting, interactive dashboards, CSV data pipelines,
> data-quality monitoring and ETL-style data transformation for library insights.

**Skills shown:** Python · Flask · MySQL · SQL (JOIN, GROUP BY, HAVING, CASE, subqueries, DATE_FORMAT) ·
relational design (PK/FK/CHECK/indexes) · transactions · ETL · data cleaning · pandas · Chart.js ·
CSV pipelines · Power BI/Tableau-ready datasets · REST-style JSON endpoints · Git/GitHub

---

## 1. Quick start

Requires **MySQL 8.0.16+** (CHECK constraints; `FOR UPDATE OF` needs 8.0.1+) and Python 3.10+.

```bash
python -m venv venv && venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

# optional: override defaults instead of editing code
#   LIBRARY_DB_HOST, LIBRARY_DB_USER, LIBRARY_DB_PASSWORD, LIBRARY_DB_NAME, LIBRARY_SECRET_KEY
python init_db.py                 # creates DB + tables, upgrades an older DB in place
python seed_data.py --dirty       # OPTIONAL demo data (+ a few bad rows for the Data Quality page)
python etl.py                     # builds the summary tables
python app.py                     # http://127.0.0.1:5000
```
Demo login (created by the seed script if no user exists): `admin@library.local` / `admin123`.
Using your existing `library_db1`? `init_db.py` keeps your data and adds only what's missing
(`books.category`, indexes, FKs, CHECKs). Any step that your data blocks (e.g. orphan rows) is
**skipped and reported**, not forced - fix the data and re-run.

**Flow:** Login → Dashboard → Books → Students → Issue → Return → Reports → **Analytics → Data Quality → Export**
(sidebar: Analytics Dashboard / Data Quality / Data Export).

## 2. Architecture - three clearly separated layers

```
 TRANSACTIONAL (OLTP)            ANALYTICAL                     REPORTING
 users, books, students,   --->  analytics/queries.py     --->  analytics/reports.py
 issued_books  (app.py)          (all SQL lives here)           analytics_routes.py (Flask blueprint)
        |                                                       templates/analytics*.html, data_quality.html
        |  EXTRACT -> TRANSFORM -> LOAD  (analytics/etl.py, transformations.py)
        v
 monthly_library_stats / department_library_stats / book_borrowing_stats / etl_run_log
```
| File | Role |
|---|---|
| `sql/schema.sql`, `init_db.py` | schema (idempotent create + upgrade) |
| `analytics/queries.py` | every analytics SQL statement, named parameters only |
| `analytics/transformations.py` | pandas: cleaning, gap-filling, summary tables, CSV shaping, e-mail/phone validation |
| `analytics/etl.py`, `etl.py` | the ETL job (CLI + button) |
| `analytics/reports.py` | date-range logic, dashboard / data-quality / export payloads |
| `analytics_routes.py` | `/analytics/*` pages + JSON API |
| `seed_data.py` | deterministic demo data |
| `tests/` | 44 unit/integration tests |

**Dashboard KPIs are computed live by SQL** (nothing static). Pandas is used only where it adds value:
filling empty months in trends, ETL cleaning/aggregation, vectorised e-mail/phone validation, CSV shaping.

## 3. Analytics dashboard (`/analytics/`)

*Snapshot KPIs* (ignore the date filter): Total Books, Total Students, Currently Issued, Overdue Books,
Availability Rate (= available titles ÷ all titles), Overdue Rate (= overdue ÷ currently issued).
*Period KPIs* (follow the filter): Total Issues (by issue date), Total Returns & Fine Collected (by return date),
Return Rate (= issues in the period that are already returned ÷ issues in the period), Most Borrowed Book,
Most Active Student, plus average loan days and fine accruing on overdue loans.

*Charts (Chart.js):* monthly issue trend · monthly return trend · fine collection trend · department-wise
borrowing · available vs issued · books by category · top authors · top 10 borrowed books · top 10 active students.
*Tables:* department detail, frequent late returners (`HAVING COUNT(*) >= 2`), overdue right now.

*Filters:* Today · Last 7 Days · Last 30 Days · This Month · This Year · Custom range (validated; an invalid range
falls back to This Year with a message). JSON for every number: `GET /analytics/api/dashboard?preset=last_30_days`.

## 4. ETL pipeline

`python etl.py` or **Data Export → Run ETL now**.

| Stage | What happens |
|---|---|
| Extract | `issued_books ⋈ books`, `books`, `students` read from MySQL |
| Transform | trim/normalise labels (`'cse '` and `'CSE'` → one department), blank → `Unknown`/`Uncategorized`; **reject** rows with missing dates, due < issue, or *Returned* without a valid return date; derive loan days, overdue days, expected fine (`FINE_PER_DAY` in `config.py`); aggregate to month / department / book grain |
| Load | `DELETE` + bulk `INSERT` of the 3 summary tables **and** an `etl_run_log` row in **one transaction** - readers never see a half-built table; any error rolls back and logs `FAILED` |

Why summary tables? They are the stable, denormalised surface BI tools connect to, and the
three analytics CSVs are served from them (exports re-run the ETL first, so they are never stale).
The live dashboard deliberately does *not* depend on them, so it is always current; the Data Quality page
**reconciles** summary totals against live SQL totals to catch drift.

## 5. Data-quality monitor (`/analytics/data-quality`)

Errors = integrity problems, warnings = hygiene, info = operational. Score = share of non-info checks passing.

| Check | Severity |
|---|---|
| Missing values (books, students) | warning |
| Duplicate student emails (case/space-insensitive) | error |
| Invalid e-mail / phone format (pandas regex; phone = 10–13 digits, optional +) | warning |
| Invalid dates (NULL, due/return before issue, issue in future) | error |
| Zero / negative quantity | error |
| Book status inconsistent with loans; issue status inconsistent with return date; book with 2 open loans | error |
| Fine ≠ overdue days × rate | warning |
| ETL summary tables out of sync with live data | warning |
| Overdue books · Unreturned books | info |

## 6. Data export (`/analytics/exports`)

UTF-8 with BOM, ISO-8601 dates, one header row, blanks for NULL, whole numbers stay whole. The page shows each file's
grain and columns (a mini data dictionary).

| File | Grain | Source |
|---|---|---|
| books / students | one row per book / student (+ times issued) | live SQL |
| issue_return | one row per loan (fact table with `overdue_days`, `fine_charged`, `issue_month`) | live SQL, date-filtered |
| fine_report | loans with a fine or currently overdue | live SQL, date-filtered |
| monthly_analytics / department_analytics / book_borrowing_analytics | month / department / book | ETL summary tables |

pandas: `pd.read_csv("library_issue_return_....csv", parse_dates=["issue_date", "due_date", "return_date"])`.
Power BI/Tableau: *Get Data → Text/CSV*, or connect straight to the three summary tables in MySQL.

## 7. Database design, constraints and indexes

* **Keys:** every table has an integer PK; `issued_books.book_id/student_id` are FKs (`ON DELETE RESTRICT` - history can't be orphaned).
* **Constraints:** `quantity > 0`, `status IN (...)`, `fine >= 0`. `students.email` is *not* UNIQUE on purpose - uniqueness is checked by the
  data-quality monitor so legacy duplicates can be found and fixed rather than blocking the upgrade.
* **Transactions:** issuing/returning runs in one transaction with `SELECT … FOR UPDATE` row locks (two librarians can't issue the same book); the ETL load is atomic.

| Index | Why it exists |
|---|---|
| `issued_books(issue_date)` | every dashboard KPI/trend/top-N filters `issue_date BETWEEN …` → range scan instead of full scan |
| `issued_books(return_date)` | returns & fine trends filter on `return_date` |
| `issued_books(status, due_date)` | overdue query = *equality* on status then *range* on due_date; its leftmost prefix also serves status-only lookups, so a separate `status` index would be redundant |
| `issued_books(book_id, status)` | "is this book out?" (issue flow, consistency checks), per-book aggregation; also the index the `book_id` FK needs |
| `issued_books(student_id, issue_date)` | per-student history/top students; also the FK index for `student_id` |
| `books(title)` | prefix search and `ORDER BY title`. **Limitation:** `LIKE '%word%'` can't use a B-tree - use FULLTEXT if search speed matters |
| `books(author)`, `books(category)` | `GROUP BY` for top authors / books-by-category can walk the index |
| `students(department)` | department grouping and joins |
| `students(email)` | duplicate-email detection, login-style lookups (non-unique, see above) |

**Deliberately not indexed:** `books.status` (2 values, low selectivity, small table) and a stand-alone `issued_books.status` (covered above).
Prove it on your data with `sql/explain_examples.sql` (includes a drop-index before/after experiment).

## 8. Tests - and what they do and don't prove

```bash
python -m unittest discover -s tests -v
```
44 tests cover date-range logic, every KPI/chart/table value against hand-computed expectations, data-quality detection,
pandas transformations (incl. MySQL-style `Decimal`/`date` inputs), the ETL (idempotent re-run, rollback on failure, empty DB),
all 7 CSV exports, every `/analytics` route (login required, DB-down handling), and the seed generator.

**Limitation:** the analytics SQL was exercised on an **SQLite stand-in** (MySQL functions emulated), not on a live MySQL server -
so query *logic* is verified, MySQL-specific behaviour (strict `ONLY_FULL_GROUP_BY`, FK/CHECK creation on legacy data, `EXPLAIN` plans)
is not. Run the Quick start against MySQL 8 and click through every page once before demoing.

## 9. Known limitations / ideas

* The app's data model is one status per book title (`quantity` is informational), so analytics treat a title as a single copy.
* No CSRF protection or roles (inherited from the original app) - fine for a student project, add Flask-WTF/roles before real use.
* The legacy Tkinter prototype is in `legacy/` for reference only.
"# smart-library-analytics" 
