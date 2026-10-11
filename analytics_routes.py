"""Flask blueprint: Analytics dashboard, data quality, CSV exports, ETL trigger.

Routes (all require login):
    GET  /analytics/                  dashboard (date-range filter via query string)
    GET  /analytics/api/dashboard     same data as JSON
    GET  /analytics/data-quality      data-quality indicators
    GET  /analytics/api/data-quality  same data as JSON
    GET  /analytics/exports           Analytics Data Export section
    GET  /analytics/export/<name>     download one CSV
    POST /analytics/etl/run           run the ETL job now
"""
from datetime import date

from flask import (Blueprint, Response, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from analytics import reports
from analytics.etl import run_etl
from database import get_db_connection

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@analytics_bp.before_request
def require_login():
    if "user_id" not in session:
        flash("Please login to continue.", "warning")
        return redirect(url_for("login"))
    return None


def _range_from_request():
    return reports.resolve_range(
        request.args.get("preset"), request.args.get("start"), request.args.get("end"))


def _close(connection, cursor=None):
    for obj in (cursor, connection):
        try:
            if obj:
                obj.close()
        except Exception:  # noqa: BLE001
            pass


@analytics_bp.route("/")
def dashboard():
    rng = _range_from_request()
    if rng["warning"]:
        flash(rng["warning"], "warning")
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        data = reports.build_dashboard(cursor, rng)
    except Exception as exc:  # noqa: BLE001
        print("ANALYTICS DASHBOARD ERROR:", exc)
        flash("Unable to load analytics. Check the database connection and run init_db.py.",
              "danger")
        data = reports.empty_dashboard(rng)
    finally:
        _close(connection, cursor)
    return render_template("analytics.html", data=data, presets=reports.PRESETS,
                           rng=rng, today=date.today().isoformat())


@analytics_bp.route("/api/dashboard")
def api_dashboard():
    rng = _range_from_request()
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        return jsonify(reports.build_dashboard(cursor, rng))
    except Exception as exc:  # noqa: BLE001
        print("ANALYTICS API ERROR:", exc)
        return jsonify({"error": "Unable to compute analytics"}), 500
    finally:
        _close(connection, cursor)


@analytics_bp.route("/data-quality")
def data_quality():
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        dq = reports.build_data_quality(cursor)
    except Exception as exc:  # noqa: BLE001
        print("DATA QUALITY ERROR:", exc)
        flash("Unable to run data-quality checks.", "danger")
        dq = {"as_of": date.today().isoformat(), "checks": [],
              "summary": {"graded_checks": 0, "passed": 0, "failing": 0, "score_pct": 0,
                          "errors": 0, "warnings": 0, "open_loans": 0, "overdue": 0}}
    finally:
        _close(connection, cursor)
    return render_template("data_quality.html", dq=dq)


@analytics_bp.route("/api/data-quality")
def api_data_quality():
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        return jsonify(reports.build_data_quality(cursor))
    except Exception as exc:  # noqa: BLE001
        print("DATA QUALITY API ERROR:", exc)
        return jsonify({"error": "Unable to run data-quality checks"}), 500
    finally:
        _close(connection, cursor)


@analytics_bp.route("/exports")
def exports():
    rng = _range_from_request()
    if rng["warning"]:
        flash(rng["warning"], "warning")
    etl = {}
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        etl = reports.etl_status(cursor)
    except Exception as exc:  # noqa: BLE001
        print("EXPORT PAGE ERROR:", exc)
    finally:
        _close(connection, cursor)
    return render_template("analytics_exports.html", exports=reports.EXPORTS, etl=etl,
                           presets=reports.PRESETS, rng=rng, today=date.today().isoformat())


@analytics_bp.route("/export/<string:name>")
def export_csv(name):
    if name not in reports.EXPORT_BY_NAME:
        flash("Unknown export.", "danger")
        return redirect(url_for("analytics.exports"))
    rng = _range_from_request()
    connection = None
    try:
        connection = get_db_connection()
        filename, payload = reports.export_dataset(connection, name, rng)
    except Exception as exc:  # noqa: BLE001
        print("EXPORT ERROR:", exc)
        flash("Unable to export data.", "danger")
        return redirect(url_for("analytics.exports"))
    finally:
        _close(connection)
    return Response(payload, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@analytics_bp.route("/etl/run", methods=["POST"])
def etl_run():
    connection = None
    try:
        connection = get_db_connection()
        stats = run_etl(connection)
        flash(f"ETL complete: {stats['source_rows']} loans read, "
              f"{stats['monthly_rows']} months, {stats['department_rows']} departments, "
              f"{stats['book_rows']} books loaded"
              + (f" ({stats['rejected_rows']} invalid rows excluded)."
                 if stats["rejected_rows"] else "."), "success")
    except Exception as exc:  # noqa: BLE001
        print("ETL ERROR:", exc)
        flash("ETL failed and was rolled back. See etl_run_log for details.", "danger")
    finally:
        _close(connection)
    return redirect(url_for("analytics.exports"))
