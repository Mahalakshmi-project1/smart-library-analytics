"""pandas transformations.

pandas is used ONLY where it beats SQL/plain Python:
  * filling empty months in a time series (SQL GROUP BY omits months with no rows)
  * cleaning + deriving columns for the ETL job and building the summary tables
  * vectorised e-mail / phone validation
  * shaping CSV files for Excel / Power BI / Tableau / pandas users
The live dashboard KPIs are computed by SQL (see queries.py).
"""
import io
import re
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from config import FINE_PER_DAY

EMAIL_RE = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
PHONE_RE = r"^\+?\d{10,13}$"  # after removing spaces, dashes, brackets


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def jsonable(value):
    """Recursively convert Decimal/date/datetime so Flask can emit JSON."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def pct(numerator, denominator):
    """Safe percentage rounded to 1 decimal (0 when denominator is 0)."""
    if not denominator:
        return 0.0
    return round(float(numerator) * 100.0 / float(denominator), 1)


def to_native(df):
    """DataFrame -> list of tuples of plain Python values (None for NaN/NaT).
    mysql-connector cannot bind numpy types, so this is required before INSERT."""
    out = []
    for row in df.itertuples(index=False, name=None):
        clean = []
        for v in row:
            if v is None or (not isinstance(v, str) and pd.isna(v)):
                clean.append(None)
            elif isinstance(v, pd.Timestamp):
                # midnight -> DATE value; otherwise keep the time (DATETIME columns)
                clean.append(v.date() if v == v.normalize() else v.to_pydatetime())
            elif hasattr(v, "item"):  # numpy scalar
                clean.append(v.item())
            else:
                clean.append(v)
        out.append(tuple(clean))
    return out


# --------------------------------------------------------------------------
# time-series gap filling (dashboard)
# --------------------------------------------------------------------------
def month_labels(start, end):
    """['2026-01', '2026-02', ...] covering start..end inclusive."""
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def fill_months(rows, start, end, value_columns):
    """Return {'labels': [...], col: [...]} with zero for months that had no rows."""
    labels = month_labels(start, end)
    df = pd.DataFrame(rows, columns=["ym", *value_columns]) if rows else \
        pd.DataFrame(columns=["ym", *value_columns])
    for col in value_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df = df.set_index("ym").reindex(labels, fill_value=0)
    result = {"labels": labels}
    for col in value_columns:
        series = df[col].astype(float)
        result[col] = [int(v) if float(v).is_integer() else round(float(v), 2) for v in series]
    return result


# --------------------------------------------------------------------------
# data-quality: e-mail / phone format validation
# --------------------------------------------------------------------------
def validate_contacts(rows):
    """rows: dicts with student_id, name, email, phone.
    Returns a DataFrame of offending rows with an 'issue' column."""
    columns = ["student_id", "name", "email", "phone", "issue"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)
    email = df["email"].fillna("").astype(str).str.strip()
    phone = df["phone"].fillna("").astype(str).str.replace(r"[\s\-()]", "", regex=True)

    bad_email = (email != "") & ~email.str.match(EMAIL_RE)
    bad_phone = (phone != "") & ~phone.str.match(PHONE_RE)

    issues = pd.Series("", index=df.index)
    issues[bad_email] = "invalid email format"
    issues[bad_phone] = issues[bad_phone].where(issues[bad_phone] == "", issues[bad_phone] + " + ") \
        + "invalid phone format"
    out = df.loc[bad_email | bad_phone, ["student_id", "name", "email", "phone"]].copy()
    out["issue"] = issues[bad_email | bad_phone]
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------
# ETL: clean + derive + aggregate
# --------------------------------------------------------------------------
ISSUE_COLUMNS = ["issue_id", "book_id", "student_id", "issue_date", "due_date",
                 "return_date", "fine", "status", "department"]


def canonical_labels(series, default):
    """Collapse whitespace; case-variants of one label ('cse', 'CSE ') map to the
    most frequent spelling. Blank -> default."""
    s = series.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    s = s.where(s != "", default)
    key = s.str.casefold()
    best = (pd.DataFrame({"key": key, "label": s})
            .groupby(["key", "label"]).size().reset_index(name="n")
            .sort_values(["key", "n", "label"], ascending=[True, False, True])
            .drop_duplicates("key").set_index("key")["label"])
    return key.map(best)


def clean_issue_facts(issues, students, today):
    """Clean the extracted loan rows and derive overdue_days / fine columns.

    Returns (clean_df, rejected_df). A row is REJECTED (kept out of the summary
    tables, counted in etl_run_log) if a date is missing/unparseable, due date
    is before issue date, or a Returned loan has no valid return date.
    """
    today = pd.Timestamp(today)
    df = pd.DataFrame(issues)
    if df.empty:
        empty = pd.DataFrame(columns=ISSUE_COLUMNS)
        return empty, empty
    for col in ("issue_date", "due_date", "return_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["fine"] = pd.to_numeric(df["fine"], errors="coerce").fillna(0.0)

    bad = (df["issue_date"].isna() | df["due_date"].isna()
           | (df["due_date"] < df["issue_date"])
           | ((df["status"] == "Returned")
              & (df["return_date"].isna() | (df["return_date"] < df["issue_date"]))))
    rejected, df = df[bad].copy(), df[~bad].copy()

    dept = canonical_labels(students["department"], "Unknown") if len(students) else None
    dept_map = dict(zip(students["student_id"], dept)) if dept is not None else {}
    df["department"] = df["student_id"].map(dept_map).fillna("Unknown")
    df["category"] = canonical_labels(df["category"], "Uncategorized")

    returned = df["status"] == "Returned"
    end = df["return_date"].where(returned, today)
    df["overdue_days"] = (end - df["due_date"]).dt.days.clip(lower=0)
    df["loan_days"] = (df["return_date"] - df["issue_date"]).dt.days
    df["fine_expected"] = df["overdue_days"].where(returned, 0) * FINE_PER_DAY
    df["is_overdue_open"] = (~returned) & (df["due_date"] < today)
    df["issue_month"] = df["issue_date"].dt.strftime("%Y-%m")
    df["return_month"] = df["return_date"].dt.strftime("%Y-%m")
    return df.reset_index(drop=True), rejected.reset_index(drop=True)


def build_monthly_stats(clean, refreshed_at):
    cols = ["month", "books_issued", "books_returned", "unique_borrowers", "late_returns",
            "fine_collected", "avg_loan_days", "return_rate_pct", "refreshed_at"]
    if clean.empty:
        return pd.DataFrame(columns=cols)
    issues = clean.groupby("issue_month").agg(
        books_issued=("issue_id", "count"),
        unique_borrowers=("student_id", "nunique"),
        returned_of_issued=("status", lambda s: (s == "Returned").sum()),
    )
    ret = clean[clean["status"] == "Returned"]
    returns = ret.groupby("return_month").agg(
        books_returned=("issue_id", "count"),
        late_returns=("fine", lambda s: (s > 0).sum()),
        fine_collected=("fine", "sum"),
        avg_loan_days=("loan_days", "mean"),
    )
    m = issues.join(returns, how="outer")
    m.index.name = "month"
    m = m.reindex(month_labels(m.index.min() + "-01", m.index.max() + "-01"))
    m.index.name = "month"
    for c in ("books_issued", "unique_borrowers", "returned_of_issued",
              "books_returned", "late_returns", "fine_collected"):
        m[c] = m[c].fillna(0)
    m["return_rate_pct"] = (m["returned_of_issued"] * 100.0 / m["books_issued"]).where(m["books_issued"] > 0)
    m["avg_loan_days"] = m["avg_loan_days"].round(2)
    m["return_rate_pct"] = m["return_rate_pct"].round(2)
    m["fine_collected"] = m["fine_collected"].round(2)
    m["refreshed_at"] = refreshed_at
    for c in ("books_issued", "books_returned", "unique_borrowers", "late_returns"):
        m[c] = m[c].astype(int)
    return m.reset_index()[cols]


def build_department_stats(clean, students, refreshed_at):
    cols = ["department", "total_students", "active_borrowers", "total_issues", "total_returns",
            "currently_issued", "overdue_open", "fine_collected", "avg_issues_per_student",
            "refreshed_at"]
    if not len(students):
        return pd.DataFrame(columns=cols)
    stu = students.copy()
    stu["department"] = canonical_labels(stu["department"], "Unknown")
    base = stu.groupby("department").agg(total_students=("student_id", "nunique"))
    if clean.empty:
        agg = pd.DataFrame(index=base.index)
        for c in ("active_borrowers", "total_issues", "total_returns",
                  "currently_issued", "overdue_open", "fine_collected"):
            agg[c] = 0
    else:
        agg = clean.groupby("department").agg(
            active_borrowers=("student_id", "nunique"),
            total_issues=("issue_id", "count"),
            total_returns=("status", lambda s: (s == "Returned").sum()),
            currently_issued=("status", lambda s: (s == "Issued").sum()),
            overdue_open=("is_overdue_open", "sum"),
            fine_collected=("fine", "sum"),
        )
    d = base.join(agg, how="left").fillna(0)
    d["avg_issues_per_student"] = (d["total_issues"] / d["total_students"]).round(2)
    d["fine_collected"] = d["fine_collected"].round(2)
    for c in ("active_borrowers", "total_issues", "total_returns", "currently_issued",
              "overdue_open", "total_students"):
        d[c] = d[c].astype(int)
    d["refreshed_at"] = refreshed_at
    return d.reset_index()[cols]


def build_book_stats(clean, books, refreshed_at):
    cols = ["book_id", "title", "author", "category", "times_issued", "times_returned",
            "currently_issued", "total_fine", "avg_loan_days", "last_issued_date",
            "popularity_rank", "refreshed_at"]
    if not len(books):
        return pd.DataFrame(columns=cols)
    b = books.copy()
    b["category"] = canonical_labels(b["category"], "Uncategorized")
    if clean.empty:
        agg = pd.DataFrame(columns=["times_issued", "times_returned", "currently_issued",
                                    "total_fine", "avg_loan_days", "last_issued_date"])
    else:
        agg = clean.groupby("book_id").agg(
            times_issued=("issue_id", "count"),
            times_returned=("status", lambda s: (s == "Returned").sum()),
            currently_issued=("status", lambda s: (s == "Issued").sum()),
            total_fine=("fine", "sum"),
            avg_loan_days=("loan_days", "mean"),
            last_issued_date=("issue_date", "max"),
        )
    out = b.merge(agg, left_on="book_id", right_index=True, how="left")
    for c in ("times_issued", "times_returned", "currently_issued"):
        out[c] = out[c].fillna(0).astype(int)
    out["total_fine"] = out["total_fine"].fillna(0).round(2)
    out["avg_loan_days"] = out["avg_loan_days"].round(2)
    out["popularity_rank"] = out["times_issued"].rank(method="dense", ascending=False).astype(int)
    out["refreshed_at"] = refreshed_at
    return out[cols]


# --------------------------------------------------------------------------
# CSV shaping for Excel / Power BI / Tableau / pandas
# --------------------------------------------------------------------------
def prepare_export(rows, date_columns=()):
    """Rows (list of dicts) -> tidy DataFrame: one header row, ISO-8601 dates,
    no thousands separators, blanks for NULL, text trimmed."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].map(lambda v: isinstance(v, datetime)).any():
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M:%S")
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
        if pd.api.types.is_float_dtype(df[col]):
            # a NULL in an integer column makes pandas use float -> "19.0"; keep whole numbers whole
            non_null = df[col].dropna()
            if len(non_null) and (non_null % 1 == 0).all():
                df[col] = df[col].astype("Int64")
    present = df.notna()
    return df.astype(object).where(present, "")


def to_csv_bytes(df):
    """UTF-8 with BOM so Excel opens accented characters correctly; pandas,
    Power BI and Tableau read it without any special options."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
