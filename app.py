from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    Response
)

from database import get_db_connection
from config import SECRET_KEY, FINE_PER_DAY
from analytics_routes import analytics_bp

from functools import wraps
from datetime import date, datetime
from decimal import Decimal
import csv
import io

from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = SECRET_KEY

# Analytics dashboard, data-quality, exports and ETL (see analytics_routes.py)
app.register_blueprint(analytics_bp)


@app.context_processor
def inject_template_globals():
    """issuebook.html / returnbook.html pre-fill today's date with datetime.utcnow()."""
    return {"datetime": datetime}


# ============================================================
# LOGIN REQUIRED DECORATOR
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def calculate_fine(due_date, return_date=None):
    """
    Fine calculation:
    ₹FINE_PER_DAY (config.py, default 5) per day after the due date.
    """

    if not due_date:
        return 0

    if isinstance(due_date, datetime):
        due_date = due_date.date()

    if isinstance(return_date, datetime):
        return_date = return_date.date()

    check_date = return_date if return_date else date.today()

    if check_date > due_date:
        days_late = (check_date - due_date).days
        return days_late * FINE_PER_DAY

    return 0


def close_connection(connection, cursor=None):

    try:
        if cursor:
            cursor.close()
    except Exception:
        pass

    try:
        if connection:
            connection.close()
    except Exception:
        pass


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("index.html")


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "danger")
            return render_template("register.html")

        connection = None
        cursor = None

        try:

            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )

            existing_user = cursor.fetchone()

            if existing_user:
                flash("Email already registered.", "warning")
                return render_template("register.html")

            hashed_password = generate_password_hash(password)

            cursor.execute(
                """
                INSERT INTO users (name, email, password)
                VALUES (%s, %s, %s)
                """,
                (name, email, hashed_password)
            )

            connection.commit()

            flash("Registration successful. Please login.", "success")

            return redirect(url_for("login"))

        except Exception as e:

            if connection:
                connection.rollback()

            print("REGISTER ERROR:", e)

            flash(
                "Registration failed. Please try again.",
                "danger"
            )

        finally:

            close_connection(connection, cursor)

    return render_template("register.html")


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("login.html")

        connection = None
        cursor = None

        try:

            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT id, name, email, password
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if user and check_password_hash(
                user["password"],
                password
            ):

                session.clear()

                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_email"] = user["email"]

                flash(
                    f"Welcome back, {user['name']}!",
                    "success"
                )

                return redirect(url_for("dashboard"))

            flash(
                "Invalid email or password.",
                "danger"
            )

        except Exception as e:

            print("LOGIN ERROR:", e)

            flash(
                "Login failed. Please try again.",
                "danger"
            )

        finally:

            close_connection(connection, cursor)

    return render_template("login.html")


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(url_for("login"))


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # ----------------------------------------------------
        # TOTAL BOOKS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM books
            """
        )

        total_books = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # AVAILABLE BOOKS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM books
            WHERE status = 'Available'
            """
        )

        available_books = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # ISSUED BOOKS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Issued'
            """
        )

        issued_books = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # TOTAL STUDENTS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM students
            """
        )

        total_students = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # RETURNED BOOKS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Returned'
            """
        )

        returned_books = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # TOTAL FINE
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COALESCE(SUM(fine), 0) AS total
            FROM issued_books
            """
        )

        total_fine = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # OVERDUE BOOKS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Issued'
            AND due_date < CURDATE()
            """
        )

        overdue_books = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # DUE TODAY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Issued'
            AND due_date = CURDATE()
            """
        )

        due_today = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # DUE SOON
        # Next 3 days excluding today
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Issued'
            AND due_date > CURDATE()
            AND due_date <= DATE_ADD(CURDATE(), INTERVAL 3 DAY)
            """
        )

        due_soon = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # FINE PENDING
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE fine > 0
            """
        )

        fine_pending = cursor.fetchone()["total"] or 0

        # ----------------------------------------------------
        # RECENT ISSUED
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                b.title,
                b.author,
                s.name AS student_name,
                ib.issue_date,
                ib.due_date,
                ib.return_date,
                ib.fine,
                ib.status
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            ORDER BY ib.issue_id DESC
            LIMIT 5
            """
        )

        recent_issued = cursor.fetchall()

        # ----------------------------------------------------
        # RECENT RETURNED
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                b.title,
                b.author,
                s.name AS student_name,
                ib.issue_date,
                ib.due_date,
                ib.return_date,
                ib.fine,
                ib.status
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            WHERE ib.status = 'Returned'
            ORDER BY ib.return_date DESC
            LIMIT 5
            """
        )

        recent_returned = cursor.fetchall()

        # ----------------------------------------------------
        # OVERDUE DETAILS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                b.title,
                b.author,
                s.name AS student_name,
                ib.issue_date,
                ib.due_date,
                ib.fine,
                ib.status
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            WHERE ib.status = 'Issued'
            AND ib.due_date < CURDATE()
            ORDER BY ib.due_date ASC
            LIMIT 10
            """
        )

        overdue_books_details = cursor.fetchall()

        stats = {
            "total_books": total_books,
            "available_books": available_books,
            "issued_books": issued_books,
            "total_students": total_students,
            "total_fine": total_fine,
            "returned_books": returned_books,
            "overdue_books": overdue_books,
            "due_today": due_today,
            "due_soon": due_soon,
            "fine_pending": fine_pending,
            "recent_issued": recent_issued,
            "recent_returned": recent_returned,
            "overdue_books_details": overdue_books_details
        }

        return render_template(
            "dashboard.html",
            stats=stats
        )

    except Exception as e:

        print("DASHBOARD ERROR:", e)

        flash(
            "Unable to load dashboard.",
            "danger"
        )

        return render_template(
            "dashboard.html",
            stats={
                "total_books": 0,
                "available_books": 0,
                "issued_books": 0,
                "total_students": 0,
                "total_fine": 0,
                "returned_books": 0,
                "overdue_books": 0,
                "due_today": 0,
                "due_soon": 0,
                "fine_pending": 0,
                "recent_issued": [],
                "recent_returned": [],
                "overdue_books_details": []
            }
        )

    finally:

        close_connection(connection, cursor)


# ============================================================
# ADD BOOK
# ============================================================

@app.route("/addbook", methods=["GET", "POST"])
@login_required
def addbook():

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        quantity = request.form.get("quantity", "1").strip()

        if not title or not author or not quantity:
            flash("All fields are required.", "danger")
            return render_template("addbook.html")

        try:
            quantity = int(quantity)

            if quantity <= 0:
                raise ValueError

        except ValueError:

            flash(
                "Quantity must be a positive number.",
                "danger"
            )

            return render_template("addbook.html")

        connection = None
        cursor = None

        try:

            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO books
                (title, author, quantity, status)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    title,
                    author,
                    quantity,
                    "Available"
                )
            )

            connection.commit()

            flash(
                "Book added successfully.",
                "success"
            )

            return redirect(url_for("viewbooks"))

        except Exception as e:

            if connection:
                connection.rollback()

            print("ADD BOOK ERROR:", e)

            flash(
                "Unable to add book.",
                "danger"
            )

        finally:

            close_connection(connection, cursor)

    return render_template("addbook.html")


# ============================================================
# VIEW BOOKS
# ============================================================

@app.route("/viewbooks")
@login_required
def viewbooks():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                book_id,
                title,
                author,
                quantity,
                status
            FROM books
            ORDER BY book_id DESC
            """
        )

        books = cursor.fetchall()

        return render_template(
            "viewbooks.html",
            books=books
        )

    except Exception as e:

        print("VIEW BOOKS ERROR:", e)

        flash(
            "Unable to load books.",
            "danger"
        )

        return render_template(
            "viewbooks.html",
            books=[]
        )

    finally:

        close_connection(connection, cursor)


# ============================================================
# SEARCH BOOK
# ============================================================

@app.route("/searchbook", methods=["GET", "POST"])
@login_required
def searchbook():

    books = []
    search = ""

    if request.values.get("search") or request.values.get("keyword") or request.values.get("query"):

        search = (request.values.get("search") or request.values.get("keyword")
                  or request.values.get("query") or "").strip()

        if search:

            connection = None
            cursor = None

            try:

                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)

                keyword = f"%{search}%"

                cursor.execute(
                    """
                    SELECT
                        book_id,
                        title,
                        author,
                        quantity,
                        status
                    FROM books
                    WHERE title LIKE %s
                    OR author LIKE %s
                    ORDER BY book_id DESC
                    """,
                    (
                        keyword,
                        keyword
                    )
                )

                books = cursor.fetchall()

            except Exception as e:

                print("SEARCH BOOK ERROR:", e)

                flash(
                    "Unable to search books.",
                    "danger"
                )

            finally:

                close_connection(connection, cursor)

    return render_template(
        "searchbook.html",
        books=books,
        search=search
    )


# ============================================================
# EDIT BOOK
# ============================================================

@app.route("/editbook/<int:book_id>", methods=["GET", "POST"])
@login_required
def editbook(book_id):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM books
            WHERE book_id = %s
            """,
            (book_id,)
        )

        book = cursor.fetchone()

        if not book:

            flash(
                "Book not found.",
                "danger"
            )

            return redirect(url_for("viewbooks"))

        if request.method == "POST":

            title = request.form.get(
                "title",
                ""
            ).strip()

            author = request.form.get(
                "author",
                ""
            ).strip()

            quantity = request.form.get(
                "quantity",
                ""
            ).strip()

            status = request.form.get(
                "status",
                "Available"
            )

            if not title or not author or not quantity:

                flash(
                    "All fields are required.",
                    "danger"
                )

                return render_template(
                    "editbook.html",
                    book=book
                )

            try:

                quantity = int(quantity)

                if quantity <= 0:
                    raise ValueError

            except ValueError:

                flash(
                    "Quantity must be a positive number.",
                    "danger"
                )

                return render_template(
                    "editbook.html",
                    book=book
                )

            if status not in ["Available", "Issued"]:
                status = "Available"

            cursor.execute(
                """
                UPDATE books
                SET
                    title = %s,
                    author = %s,
                    quantity = %s,
                    status = %s
                WHERE book_id = %s
                """,
                (
                    title,
                    author,
                    quantity,
                    status,
                    book_id
                )
            )

            connection.commit()

            flash(
                "Book updated successfully.",
                "success"
            )

            return redirect(url_for("viewbooks"))

        return render_template(
            "editbook.html",
            book=book
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print("EDIT BOOK ERROR:", e)

        flash(
            "Unable to update book.",
            "danger"
        )

        return redirect(url_for("viewbooks"))

    finally:

        close_connection(connection, cursor)


# ============================================================
# DELETE BOOK
# ============================================================

@app.route("/deletebook/<int:book_id>", methods=["GET", "POST"])
@login_required
def deletebook(book_id):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM issued_books
            WHERE book_id = %s
            """,
            (book_id,)
        )

        issued_count = cursor.fetchone()[0]

        if issued_count > 0:

            flash(
                "This book has transaction records and cannot be deleted.",
                "warning"
            )

            return redirect(url_for("viewbooks"))

        cursor.execute(
            """
            DELETE FROM books
            WHERE book_id = %s
            """,
            (book_id,)
        )

        connection.commit()

        flash(
            "Book deleted successfully.",
            "success"
        )

        return redirect(url_for("viewbooks"))

    except Exception as e:

        if connection:
            connection.rollback()

        print("DELETE BOOK ERROR:", e)

        flash(
            "Unable to delete book.",
            "danger"
        )

        return redirect(url_for("viewbooks"))

    finally:

        close_connection(connection, cursor)


# ============================================================
# ADD STUDENT
# ============================================================

@app.route("/addstudent", methods=["GET", "POST"])
@login_required
def addstudent():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        department = request.form.get(
            "department",
            ""
        ).strip()

        year = request.form.get(
            "year",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        if not all([
            name,
            department,
            year,
            email,
            phone
        ]):

            flash(
                "All fields are required.",
                "danger"
            )

            return render_template(
                "addstudent.html"
            )

        try:

            year = int(year)

            if year <= 0:
                raise ValueError

        except ValueError:

            flash(
                "Year must be a valid number.",
                "danger"
            )

            return render_template(
                "addstudent.html"
            )

        connection = None
        cursor = None

        try:

            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO students
                (name, department, year, email, phone)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    department,
                    year,
                    email,
                    phone
                )
            )

            connection.commit()

            flash(
                "Student added successfully.",
                "success"
            )

            return redirect(
                url_for("viewstudents")
            )

        except Exception as e:

            if connection:
                connection.rollback()

            print("ADD STUDENT ERROR:", e)

            flash(
                "Unable to add student.",
                "danger"
            )

        finally:

            close_connection(connection, cursor)

    return render_template(
        "addstudent.html"
    )


# ============================================================
# VIEW STUDENTS
# ============================================================

@app.route("/viewstudents")
@login_required
def viewstudents():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                student_id,
                name,
                department,
                year,
                email,
                phone
            FROM students
            ORDER BY student_id DESC
            """
        )

        students = cursor.fetchall()

        return render_template(
            "viewstudents.html",
            students=students
        )

    except Exception as e:

        print("VIEW STUDENTS ERROR:", e)

        flash(
            "Unable to load students.",
            "danger"
        )

        return render_template(
            "viewstudents.html",
            students=[]
        )

    finally:

        close_connection(connection, cursor)


# ============================================================
# SEARCH STUDENT
# ============================================================

@app.route("/searchstudent", methods=["GET", "POST"])
@login_required
def searchstudent():

    students = []
    search = ""

    if request.values.get("search") or request.values.get("keyword") or request.values.get("query"):

        search = (request.values.get("search") or request.values.get("keyword")
                  or request.values.get("query") or "").strip()

        if search:

            connection = None
            cursor = None

            try:

                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)

                keyword = f"%{search}%"

                cursor.execute(
                    """
                    SELECT
                        student_id,
                        name,
                        department,
                        year,
                        email,
                        phone
                    FROM students
                    WHERE name LIKE %s
                    OR department LIKE %s
                    OR email LIKE %s
                    OR phone LIKE %s
                    ORDER BY student_id DESC
                    """,
                    (
                        keyword,
                        keyword,
                        keyword,
                        keyword
                    )
                )

                students = cursor.fetchall()

            except Exception as e:

                print(
                    "SEARCH STUDENT ERROR:",
                    e
                )

                flash(
                    "Unable to search students.",
                    "danger"
                )

            finally:

                close_connection(
                    connection,
                    cursor
                )

    return render_template(
        "searchstudent.html",
        students=students,
        search=search
    )


# ============================================================
# EDIT STUDENT
# ============================================================

@app.route(
    "/editstudent/<int:student_id>",
    methods=["GET", "POST"]
)
@login_required
def editstudent(student_id):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM students
            WHERE student_id = %s
            """,
            (student_id,)
        )

        student = cursor.fetchone()

        if not student:

            flash(
                "Student not found.",
                "danger"
            )

            return redirect(
                url_for("viewstudents")
            )

        if request.method == "POST":

            name = request.form.get(
                "name",
                ""
            ).strip()

            department = request.form.get(
                "department",
                ""
            ).strip()

            year = request.form.get(
                "year",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip()

            phone = request.form.get(
                "phone",
                ""
            ).strip()

            if not all([
                name,
                department,
                year,
                email,
                phone
            ]):

                flash(
                    "All fields are required.",
                    "danger"
                )

                return render_template(
                    "editstudent.html",
                    student=student
                )

            try:

                year = int(year)

                if year <= 0:
                    raise ValueError

            except ValueError:

                flash(
                    "Year must be a valid number.",
                    "danger"
                )

                return render_template(
                    "editstudent.html",
                    student=student
                )

            cursor.execute(
                """
                UPDATE students
                SET
                    name = %s,
                    department = %s,
                    year = %s,
                    email = %s,
                    phone = %s
                WHERE student_id = %s
                """,
                (
                    name,
                    department,
                    year,
                    email,
                    phone,
                    student_id
                )
            )

            connection.commit()

            flash(
                "Student updated successfully.",
                "success"
            )

            return redirect(
                url_for("viewstudents")
            )

        return render_template(
            "editstudent.html",
            student=student
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "EDIT STUDENT ERROR:",
            e
        )

        flash(
            "Unable to update student.",
            "danger"
        )

        return redirect(
            url_for("viewstudents")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# DELETE STUDENT
# ============================================================

@app.route(
    "/deletestudent/<int:student_id>",
    methods=["GET", "POST"]
)
@login_required
def deletestudent(student_id):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM issued_books
            WHERE student_id = %s
            """,
            (student_id,)
        )

        transaction_count = cursor.fetchone()[0]

        if transaction_count > 0:

            flash(
                "This student has transaction records and cannot be deleted.",
                "warning"
            )

            return redirect(
                url_for("viewstudents")
            )

        cursor.execute(
            """
            DELETE FROM students
            WHERE student_id = %s
            """,
            (student_id,)
        )

        connection.commit()

        flash(
            "Student deleted successfully.",
            "success"
        )

        return redirect(
            url_for("viewstudents")
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "DELETE STUDENT ERROR:",
            e
        )

        flash(
            "Unable to delete student.",
            "danger"
        )

        return redirect(
            url_for("viewstudents")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# ISSUE BOOK
# ============================================================

@app.route(
    "/issuebook",
    methods=["GET", "POST"]
)
@login_required
def issuebook():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "POST":

            book_id = request.form.get(
                "book_id",
                ""
            ).strip()

            student_id = request.form.get(
                "student_id",
                ""
            ).strip()

            issue_date = request.form.get(
                "issue_date",
                ""
            ).strip()

            due_date = request.form.get(
                "due_date",
                ""
            ).strip()

            if not all([
                book_id,
                student_id,
                issue_date,
                due_date
            ]):

                flash(
                    "All fields are required.",
                    "danger"
                )

                return redirect(
                    url_for("issuebook")
                )

            # --------------------------------------------
            # Check book (row lock: two librarians cannot issue the same book at once;
            # the lock is released by commit/rollback when the connection closes)
            # --------------------------------------------

            cursor.execute(
                """
                SELECT *
                FROM books
                WHERE book_id = %s
                FOR UPDATE
                """,
                (book_id,)
            )

            book = cursor.fetchone()

            if not book:

                flash(
                    "Book not found.",
                    "danger"
                )

                return redirect(
                    url_for("issuebook")
                )

            if book["status"] == "Issued":

                flash(
                    "This book is already issued.",
                    "warning"
                )

                return redirect(
                    url_for("issuebook")
                )

            # --------------------------------------------
            # Check student
            # --------------------------------------------

            cursor.execute(
                """
                SELECT *
                FROM students
                WHERE student_id = %s
                """,
                (student_id,)
            )

            student = cursor.fetchone()

            if not student:

                flash(
                    "Student not found.",
                    "danger"
                )

                return redirect(
                    url_for("issuebook")
                )

            # --------------------------------------------
            # Date validation
            # --------------------------------------------

            try:

                issue_date_obj = datetime.strptime(
                    issue_date,
                    "%Y-%m-%d"
                ).date()

                due_date_obj = datetime.strptime(
                    due_date,
                    "%Y-%m-%d"
                ).date()

                if due_date_obj < issue_date_obj:

                    flash(
                        "Due date cannot be before issue date.",
                        "danger"
                    )

                    return redirect(
                        url_for("issuebook")
                    )

            except ValueError:

                flash(
                    "Invalid date format.",
                    "danger"
                )

                return redirect(
                    url_for("issuebook")
                )

            # --------------------------------------------
            # Insert issue
            # --------------------------------------------

            cursor.execute(
                """
                INSERT INTO issued_books
                (
                    book_id,
                    student_id,
                    issue_date,
                    due_date,
                    fine,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    book_id,
                    student_id,
                    issue_date_obj,
                    due_date_obj,
                    0,
                    "Issued"
                )
            )

            # --------------------------------------------
            # Update book
            # --------------------------------------------

            cursor.execute(
                """
                UPDATE books
                SET status = 'Issued'
                WHERE book_id = %s
                """,
                (book_id,)
            )

            connection.commit()

            flash(
                "Book issued successfully.",
                "success"
            )

            return redirect(
                url_for("returnbook")
            )

        # ------------------------------------------------
        # GET BOOKS
        # ------------------------------------------------

        cursor.execute(
            """
            SELECT *
            FROM books
            WHERE status = 'Available'
            ORDER BY title
            """
        )

        books = cursor.fetchall()

        # ------------------------------------------------
        # GET STUDENTS
        # ------------------------------------------------

        cursor.execute(
            """
            SELECT *
            FROM students
            ORDER BY name
            """
        )

        students = cursor.fetchall()

        return render_template(
            "issuebook.html",
            books=books,
            students=students
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "ISSUE BOOK ERROR:",
            e
        )

        flash(
            "Unable to issue book.",
            "danger"
        )

        # a failed page LOAD must not redirect to itself (infinite loop)
        if request.method == "GET":
            return redirect(url_for("dashboard"))

        return redirect(
            url_for("issuebook")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# RETURN BOOK
# ============================================================

@app.route(
    "/returnbook",
    methods=["GET", "POST"]
)
@login_required
def returnbook():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        if request.method == "POST":

            issue_id = request.form.get(
                "issue_id",
                ""
            ).strip()

            return_date = request.form.get(
                "return_date",
                ""
            ).strip()

            if not issue_id or not return_date:

                flash(
                    "Issue ID and return date are required.",
                    "danger"
                )

                return redirect(
                    url_for("returnbook")
                )

            # --------------------------------------------
            # Find issued book
            # --------------------------------------------

            cursor.execute(
                """
                SELECT
                    ib.*,
                    b.title,
                    b.author,
                    s.name AS student_name
                FROM issued_books ib
                JOIN books b
                    ON ib.book_id = b.book_id
                JOIN students s
                    ON ib.student_id = s.student_id
                WHERE ib.issue_id = %s
                FOR UPDATE OF ib
                """,
                (issue_id,)
            )

            issue = cursor.fetchone()

            if not issue:

                flash(
                    "Issue record not found.",
                    "danger"
                )

                return redirect(
                    url_for("returnbook")
                )

            if issue["status"] == "Returned":

                flash(
                    "This book has already been returned.",
                    "warning"
                )

                return redirect(
                    url_for("returnbook")
                )

            try:

                return_date_obj = datetime.strptime(
                    return_date,
                    "%Y-%m-%d"
                ).date()

            except ValueError:

                flash(
                    "Invalid return date.",
                    "danger"
                )

                return redirect(
                    url_for("returnbook")
                )

            issue_date_obj = issue["issue_date"]

            if isinstance(issue_date_obj, datetime):
                issue_date_obj = issue_date_obj.date()

            if return_date_obj < issue_date_obj:

                flash(
                    "Return date cannot be before issue date.",
                    "danger"
                )

                return redirect(
                    url_for("returnbook")
                )

            # --------------------------------------------
            # Calculate fine
            # --------------------------------------------

            fine = calculate_fine(
                issue["due_date"],
                return_date_obj
            )

            # --------------------------------------------
            # Update issue
            # --------------------------------------------

            cursor.execute(
                """
                UPDATE issued_books
                SET
                    return_date = %s,
                    fine = %s,
                    status = 'Returned'
                WHERE issue_id = %s
                """,
                (
                    return_date_obj,
                    fine,
                    issue_id
                )
            )

            # --------------------------------------------
            # Make book available
            # --------------------------------------------

            cursor.execute(
                """
                UPDATE books
                SET status = 'Available'
                WHERE book_id = %s
                """,
                (issue["book_id"],)
            )

            connection.commit()

            if fine > 0:

                flash(
                    f"Book returned successfully. Fine: ₹{fine}",
                    "warning"
                )

            else:

                flash(
                    "Book returned successfully. No fine.",
                    "success"
                )

            return redirect(
                url_for("returnbook")
            )

        # ------------------------------------------------
        # CURRENTLY ISSUED BOOKS
        # ------------------------------------------------

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                ib.book_id,
                ib.student_id,
                ib.issue_date,
                ib.due_date,
                ib.fine,
                ib.status,
                b.title,
                b.author,
                s.name AS student_name
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            WHERE ib.status = 'Issued'
            ORDER BY ib.due_date ASC
            """
        )

        issued_books = cursor.fetchall()

        return render_template(
            "returnbook.html",
            issued_books=issued_books
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "RETURN BOOK ERROR:",
            e
        )

        flash(
            "Unable to return book.",
            "danger"
        )

        # a failed page LOAD must not redirect to itself (infinite loop)
        if request.method == "GET":
            return redirect(url_for("dashboard"))

        return redirect(
            url_for("returnbook")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# REPORTS
# ============================================================

@app.route("/reports")
@login_required
def reports():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # ----------------------------------------------------
        # ALL TRANSACTIONS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                b.title,
                b.author,
                s.name AS student_name,
                s.department,
                ib.issue_date,
                ib.due_date,
                ib.return_date,
                ib.fine,
                ib.status
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            ORDER BY ib.issue_id DESC
            """
        )

        transactions = cursor.fetchall()

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            """
        )

        total_transactions = cursor.fetchone()["total"] or 0

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Issued'
            """
        )

        active_issues = cursor.fetchone()["total"] or 0

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM issued_books
            WHERE status = 'Returned'
            """
        )

        total_returns = cursor.fetchone()["total"] or 0

        cursor.execute(
            """
            SELECT COALESCE(SUM(fine), 0) AS total
            FROM issued_books
            """
        )

        total_fines = cursor.fetchone()["total"] or 0

        summary = {
            "total_transactions": total_transactions,
            "active_issues": active_issues,
            "total_returns": total_returns,
            "total_fines": total_fines
        }

        return render_template(
            "reports.html",
            transactions=transactions,
            summary=summary
        )

    except Exception as e:

        print(
            "REPORT ERROR:",
            e
        )

        flash(
            "Unable to load reports.",
            "danger"
        )

        return render_template(
            "reports.html",
            transactions=[],
            summary={
                "total_transactions": 0,
                "active_issues": 0,
                "total_returns": 0,
                "total_fines": 0
            }
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# BOOK STATUS CHART
# ============================================================

@app.route("/chart/books_status")
@login_required
def books_status_chart():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                status,
                COUNT(*) AS total
            FROM books
            GROUP BY status
            """
        )

        rows = cursor.fetchall()

        labels = []
        counts = []

        for row in rows:

            labels.append(
                row["status"]
            )

            counts.append(
                row["total"]
            )

        return jsonify({
            "labels": labels,
            "counts": counts
        })

    except Exception as e:

        print(
            "BOOK STATUS CHART ERROR:",
            e
        )

        return jsonify({
            "labels": [],
            "counts": []
        })

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# ISSUE / RETURN CHART
# ============================================================

@app.route("/chart/issue_return")
@login_required
def issue_return_chart():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                DATE_FORMAT(issue_date, '%Y-%m') AS month,
                COUNT(*) AS issued
            FROM issued_books
            GROUP BY DATE_FORMAT(issue_date, '%Y-%m')
            ORDER BY month
            LIMIT 12
            """
        )

        issue_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                DATE_FORMAT(return_date, '%Y-%m') AS month,
                COUNT(*) AS returned
            FROM issued_books
            WHERE return_date IS NOT NULL
            GROUP BY DATE_FORMAT(return_date, '%Y-%m')
            ORDER BY month
            LIMIT 12
            """
        )

        return_rows = cursor.fetchall()

        issue_data = {
            row["month"]: row["issued"]
            for row in issue_rows
        }

        return_data = {
            row["month"]: row["returned"]
            for row in return_rows
        }

        all_months = sorted(
            set(issue_data.keys()) |
            set(return_data.keys())
        )

        labels = all_months

        issued = [
            issue_data.get(month, 0)
            for month in all_months
        ]

        returned = [
            return_data.get(month, 0)
            for month in all_months
        ]

        return jsonify({
            "labels": labels,
            "issued": issued,
            "returned": returned
        })

    except Exception as e:

        print(
            "ISSUE RETURN CHART ERROR:",
            e
        )

        return jsonify({
            "labels": [],
            "issued": [],
            "returned": []
        })

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# FINE CHART
# ============================================================

@app.route("/chart/fine")
@login_required
def fine_chart():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                DATE_FORMAT(
                    COALESCE(return_date, issue_date),
                    '%Y-%m'
                ) AS month,
                COALESCE(SUM(fine), 0) AS fine
            FROM issued_books
            GROUP BY
                DATE_FORMAT(
                    COALESCE(return_date, issue_date),
                    '%Y-%m'
                )
            ORDER BY month
            LIMIT 12
            """
        )

        rows = cursor.fetchall()

        labels = []
        fines = []

        for row in rows:

            labels.append(
                row["month"]
            )

            value = row["fine"]

            if isinstance(value, Decimal):
                value = float(value)

            fines.append(
                value or 0
            )

        return jsonify({
            "labels": labels,
            "fines": fines
        })

    except Exception as e:

        print(
            "FINE CHART ERROR:",
            e
        )

        return jsonify({
            "labels": [],
            "fines": []
        })

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# PROFILE
# ============================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                id,
                name,
                email
            FROM users
            WHERE id = %s
            """,
            (session["user_id"],)
        )

        user = cursor.fetchone()

        if not user:

            session.clear()

            flash(
                "User account not found.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        if request.method == "POST":

            name = request.form.get(
                "name",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip().lower()

            if not name or not email:

                flash(
                    "Name and email are required.",
                    "danger"
                )

                return render_template(
                    "profile.html",
                    user=user
                )

            # --------------------------------------------
            # Check duplicate email
            # --------------------------------------------

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE email = %s
                AND id != %s
                """,
                (
                    email,
                    session["user_id"]
                )
            )

            duplicate = cursor.fetchone()

            if duplicate:

                flash(
                    "Email is already used by another account.",
                    "danger"
                )

                return render_template(
                    "profile.html",
                    user=user
                )

            cursor.execute(
                """
                UPDATE users
                SET
                    name = %s,
                    email = %s
                WHERE id = %s
                """,
                (
                    name,
                    email,
                    session["user_id"]
                )
            )

            connection.commit()

            session["user_name"] = name
            session["user_email"] = email

            flash(
                "Profile updated successfully.",
                "success"
            )

            return redirect(
                url_for("profile")
            )

        return render_template(
            "profile.html",
            user=user
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "PROFILE ERROR:",
            e
        )

        flash(
            "Unable to update profile.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# EXPORT CSV
# ============================================================

@app.route("/export/<string:data_type>")
@login_required
def export_data(data_type):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        output = io.StringIO()

        writer = csv.writer(output)

        # ----------------------------------------------------
        # BOOKS
        # ----------------------------------------------------

        if data_type == "books":

            cursor.execute(
                """
                SELECT
                    book_id,
                    title,
                    author,
                    quantity,
                    status
                FROM books
                ORDER BY book_id
                """
            )

            rows = cursor.fetchall()

            writer.writerow([
                "Book ID",
                "Title",
                "Author",
                "Quantity",
                "Status"
            ])

            for row in rows:

                writer.writerow([
                    row["book_id"],
                    row["title"],
                    row["author"],
                    row["quantity"],
                    row["status"]
                ])

            filename = "library_books.csv"

        # ----------------------------------------------------
        # STUDENTS
        # ----------------------------------------------------

        elif data_type == "students":

            cursor.execute(
                """
                SELECT
                    student_id,
                    name,
                    department,
                    year,
                    email,
                    phone
                FROM students
                ORDER BY student_id
                """
            )

            rows = cursor.fetchall()

            writer.writerow([
                "Student ID",
                "Name",
                "Department",
                "Year",
                "Email",
                "Phone"
            ])

            for row in rows:

                writer.writerow([
                    row["student_id"],
                    row["name"],
                    row["department"],
                    row["year"],
                    row["email"],
                    row["phone"]
                ])

            filename = "library_students.csv"

        # ----------------------------------------------------
        # TRANSACTIONS
        # ----------------------------------------------------

        elif data_type == "transactions":

            cursor.execute(
                """
                SELECT
                    ib.issue_id,
                    b.title,
                    s.name AS student_name,
                    ib.issue_date,
                    ib.due_date,
                    ib.return_date,
                    ib.fine,
                    ib.status
                FROM issued_books ib
                JOIN books b
                    ON ib.book_id = b.book_id
                JOIN students s
                    ON ib.student_id = s.student_id
                ORDER BY ib.issue_id
                """
            )

            rows = cursor.fetchall()

            writer.writerow([
                "Issue ID",
                "Book",
                "Student",
                "Issue Date",
                "Due Date",
                "Return Date",
                "Fine",
                "Status"
            ])

            for row in rows:

                writer.writerow([
                    row["issue_id"],
                    row["title"],
                    row["student_name"],
                    row["issue_date"],
                    row["due_date"],
                    row["return_date"] or "",
                    row["fine"],
                    row["status"]
                ])

            filename = "library_transactions.csv"

        else:

            flash(
                "Invalid export type.",
                "danger"
            )

            return redirect(
                url_for("reports")
            )

        response = Response(
            output.getvalue(),
            mimetype="text/csv"
        )

        response.headers[
            "Content-Disposition"
        ] = f"attachment; filename={filename}"

        return response

    except Exception as e:

        print(
            "EXPORT ERROR:",
            e
        )

        flash(
            "Unable to export data.",
            "danger"
        )

        return redirect(
            url_for("reports")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# PDF REPORT
# ============================================================

@app.route("/generate_pdf")
@login_required
def generate_pdf():

    try:

        from fpdf import FPDF

    except ImportError:

        flash(
            "fpdf2 is not installed. Run: pip install fpdf2",
            "danger"
        )

        return redirect(
            url_for("reports")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                ib.issue_id,
                b.title,
                s.name AS student_name,
                ib.issue_date,
                ib.due_date,
                ib.return_date,
                ib.fine,
                ib.status
            FROM issued_books ib
            JOIN books b
                ON ib.book_id = b.book_id
            JOIN students s
                ON ib.student_id = s.student_id
            ORDER BY ib.issue_id DESC
            """
        )

        rows = cursor.fetchall()

        pdf = FPDF(
            orientation="L",
            unit="mm",
            format="A4"
        )

        pdf.set_auto_page_break(
            auto=True,
            margin=15
        )

        pdf.add_page()

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        pdf.set_font(
            "Arial",
            "B",
            20
        )

        pdf.cell(
            0,
            12,
            "Smart Library Management System",
            ln=True,
            align="C"
        )

        pdf.set_font(
            "Arial",
            "B",
            14
        )

        pdf.cell(
            0,
            10,
            "Library Transaction Report",
            ln=True,
            align="C"
        )

        pdf.set_font(
            "Arial",
            "",
            9
        )

        pdf.cell(
            0,
            8,
            f"Generated on: {date.today()}",
            ln=True,
            align="C"
        )

        pdf.ln(5)

        # ----------------------------------------------------
        # TABLE HEADER
        # ----------------------------------------------------

        headers = [
            ("ID", 15),
            ("Book", 60),
            ("Student", 55),
            ("Issue Date", 30),
            ("Due Date", 30),
            ("Return Date", 30),
            ("Fine", 25),
            ("Status", 30)
        ]

        pdf.set_font(
            "Arial",
            "B",
            8
        )

        for header, width in headers:

            pdf.cell(
                width,
                8,
                header,
                border=1,
                align="C"
            )

        pdf.ln()

        # ----------------------------------------------------
        # TABLE DATA
        # ----------------------------------------------------

        pdf.set_font(
            "Arial",
            "",
            7
        )

        for row in rows:

            pdf.cell(
                15,
                8,
                str(row["issue_id"]),
                border=1
            )

            pdf.cell(
                60,
                8,
                str(row["title"])[:35],
                border=1
            )

            pdf.cell(
                55,
                8,
                str(row["student_name"])[:32],
                border=1
            )

            pdf.cell(
                30,
                8,
                str(row["issue_date"]),
                border=1
            )

            pdf.cell(
                30,
                8,
                str(row["due_date"]),
                border=1
            )

            pdf.cell(
                30,
                8,
                str(row["return_date"] or "-"),
                border=1
            )

            fine = row["fine"] or 0

            if isinstance(fine, Decimal):
                fine = float(fine)

            pdf.cell(
                25,
                8,
                f"Rs. {fine:.2f}",
                border=1
            )

            pdf.cell(
                30,
                8,
                str(row["status"]),
                border=1
            )

            pdf.ln()

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------

        pdf_bytes = bytes(
            pdf.output()
        )

        response = Response(
            pdf_bytes,
            mimetype="application/pdf"
        )

        response.headers[
            "Content-Disposition"
        ] = "attachment; filename=library_report.pdf"

        return response

    except Exception as e:

        print(
            "PDF ERROR:",
            e
        )

        flash(
            "Unable to generate PDF report.",
            "danger"
        )

        return redirect(
            url_for("reports")
        )

    finally:

        close_connection(
            connection,
            cursor
        )


# ============================================================
# 404 ERROR
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


# ============================================================
# 500 ERROR
# ============================================================

@app.errorhandler(500)
def internal_server_error(error):

    return render_template(
        "500.html"
    ), 500


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )