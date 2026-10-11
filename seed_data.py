"""Generate realistic DEMO data (for testing / screenshots only).

    python seed_data.py                 # add demo data to an empty database
    python seed_data.py --reset --yes   # wipe books/students/issues first
    python seed_data.py --dirty         # also insert a few deliberately bad rows
                                        # so the Data Quality page has something to find

Deterministic (fixed random seed) so results are reproducible. Loan history
spans the last 12 months relative to today. A book can only be out once at a
time, matching the app's single-status model.
"""
import argparse
import random
from datetime import date, timedelta

from config import FINE_PER_DAY  # config.py has no database dependency

DEPARTMENTS = ["CSE", "ECE", "EEE", "MECH", "CIVIL", "IT"]
FIRST = ["Aarav", "Diya", "Kavya", "Rohan", "Ananya", "Vikram", "Meera", "Arjun", "Sneha", "Karthik",
         "Priya", "Rahul", "Nisha", "Aditya", "Divya", "Harish", "Lakshmi", "Manoj", "Pooja", "Suresh",
         "Swathi", "Tarun", "Varsha", "Yash", "Zoya", "Bharath", "Deepa", "Gokul", "Ishita", "Naveen"]
LAST = ["Kumar", "Sharma", "Reddy", "Nair", "Iyer", "Patel", "Singh", "Menon", "Rao", "Das"]

CATALOG = [  # (title, author, category)
    ("Digital Design", "M. Morris Mano", "Electronics"),
    ("Microelectronic Circuits", "Adel Sedra", "Electronics"),
    ("Electronic Devices and Circuit Theory", "Robert Boylestad", "Electronics"),
    ("Signals and Systems", "Alan Oppenheim", "Communication"),
    ("Digital Signal Processing", "John Proakis", "Communication"),
    ("Communication Systems", "Simon Haykin", "Communication"),
    ("Digital Communications", "John Proakis", "Communication"),
    ("Analog and Digital Communication", "Sanjay Sharma", "Communication"),
    ("Microprocessor Architecture and Applications", "Ramesh Gaonkar", "Embedded Systems"),
    ("The 8051 Microcontroller", "Kenneth Ayala", "Embedded Systems"),
    ("Embedded Systems", "Raj Kamal", "Embedded Systems"),
    ("Making Embedded Systems", "Elecia White", "Embedded Systems"),
    ("Computer Organization", "Carl Hamacher", "Computer Science"),
    ("Operating System Concepts", "Abraham Silberschatz", "Computer Science"),
    ("Database System Concepts", "Abraham Silberschatz", "Computer Science"),
    ("Computer Networks", "Andrew Tanenbaum", "Computer Science"),
    ("Introduction to Algorithms", "Thomas Cormen", "Computer Science"),
    ("Data Structures Using C", "Reema Thareja", "Computer Science"),
    ("Let Us C", "Yashavant Kanetkar", "Programming"),
    ("Python Crash Course", "Eric Matthes", "Programming"),
    ("Fluent Python", "Luciano Ramalho", "Programming"),
    ("Learning Python", "Mark Lutz", "Programming"),
    ("Flask Web Development", "Miguel Grinberg", "Programming"),
    ("Clean Code", "Robert Martin", "Programming"),
    ("Python for Data Analysis", "Wes McKinney", "Data & Analytics"),
    ("Data Science from Scratch", "Joel Grus", "Data & Analytics"),
    ("SQL for Data Analysis", "Cathy Tanimura", "Data & Analytics"),
    ("Designing Data-Intensive Applications", "Martin Kleppmann", "Data & Analytics"),
    ("The Data Warehouse Toolkit", "Ralph Kimball", "Data & Analytics"),
    ("Storytelling with Data", "Cole Knaflic", "Data & Analytics"),
    ("Hands-On Machine Learning", "Aurelien Geron", "Data & Analytics"),
    ("Pattern Recognition and Machine Learning", "Christopher Bishop", "Data & Analytics"),
    ("Engineering Mathematics", "B. S. Grewal", "Mathematics"),
    ("Higher Engineering Mathematics", "B. V. Ramana", "Mathematics"),
    ("Linear Algebra and Its Applications", "Gilbert Strang", "Mathematics"),
    ("Probability and Statistics for Engineers", "Richard Johnson", "Mathematics"),
    ("Engineering Physics", "Gaur and Gupta", "Science"),
    ("Engineering Chemistry", "Jain and Jain", "Science"),
    ("Network Analysis", "M. E. Van Valkenburg", "Electrical"),
    ("Electric Circuits", "James Nilsson", "Electrical"),
    ("Power System Analysis", "Hadi Saadat", "Electrical"),
    ("Control Systems Engineering", "Norman Nise", "Electrical"),
    ("Electrical Machines", "P. S. Bimbhra", "Electrical"),
    ("Thermodynamics: An Engineering Approach", "Yunus Cengel", "Mechanical"),
    ("Strength of Materials", "R. K. Bansal", "Mechanical"),
    ("Fluid Mechanics", "Frank White", "Mechanical"),
    ("Theory of Machines", "S. S. Rattan", "Mechanical"),
    ("Structural Analysis", "R. C. Hibbeler", "Civil"),
    ("Surveying", "B. C. Punmia", "Civil"),
    ("Soil Mechanics and Foundations", "B. C. Punmia", "Civil"),
    ("Wings of Fire", "A. P. J. Abdul Kalam", "General Reading"),
    ("The Pragmatic Programmer", "Andrew Hunt", "Programming"),
    ("Atomic Habits", "James Clear", "General Reading"),
    ("Deep Work", "Cal Newport", "General Reading"),
    ("The Innovators", "Walter Isaacson", "General Reading"),
    ("Zero to One", "Peter Thiel", "General Reading"),
    ("Technical Communication", "Meenakshi Raman", "Humanities"),
    ("Professional Ethics in Engineering", "R. S. Naagarazan", "Humanities"),
]


def generate_dataset(today, seed=42):
    """Pure function: returns dict of lists (no DB access)."""
    rng = random.Random(seed)

    students = []
    for i in range(1, 61):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        dept = DEPARTMENTS[(i - 1) % len(DEPARTMENTS)]
        year = rng.randint(1, 4)
        email = f"{name.lower().replace(' ', '.')}{i}@college.edu"
        phone = str(rng.choice([6, 7, 8, 9])) + "".join(str(rng.randint(0, 9)) for _ in range(9))
        students.append((name, dept, year, email, phone))
    # a few power users / heavy readers, ECE-skewed (project owner is an ECE student)
    weights = [3 if s[1] == "ECE" else 1 for s in students]
    for i in rng.sample(range(len(students)), 8):
        weights[i] *= 5

    books = []
    for title, author, category in CATALOG:
        books.append([title, author, category, rng.choice([1, 1, 2, 3])])

    # popularity: a few hot titles, long tail
    popularity = [rng.paretovariate(1.6) for _ in books]

    issues = []   # (book_idx, student_idx, issue, due, return|None, fine, status)
    start_window = today - timedelta(days=365)
    for b_idx, pop in enumerate(popularity):
        t = start_window + timedelta(days=rng.randint(0, 40))
        mean_gap = max(4, 70 / pop)
        while t <= today:
            s_idx = rng.choices(range(len(students)), weights=weights)[0]
            issue_d = t
            due_d = issue_d + timedelta(days=14)
            if rng.random() < 0.22:                       # late return
                ret_d = due_d + timedelta(days=rng.randint(1, 25))
            else:
                ret_d = issue_d + timedelta(days=rng.randint(3, 14))
            if ret_d > today:                             # still out
                issues.append((b_idx, s_idx, issue_d, due_d, None, 0, "Issued"))
                break
            fine = max((ret_d - due_d).days, 0) * FINE_PER_DAY
            issues.append((b_idx, s_idx, issue_d, due_d, ret_d, fine, "Returned"))
            t = ret_d + timedelta(days=1 + int(rng.expovariate(1 / mean_gap)))
    issues.sort(key=lambda r: (r[2], r[0]))
    return {"students": students, "books": books, "issues": issues}


DIRTY_STUDENTS = [  # name, dept, year, email, phone
    ("Duplicate Dan", "CSE", 2, "aarav.demo@college.edu", "9876543210"),
    ("Duplicate Dina", "ECE", 3, "AARAV.demo@college.edu ", "9876543211"),
    ("Bad Email Ben", "IT", 1, "ben-at-college.edu", "9123456780"),
    ("Bad Phone Bella", "EEE", 2, "bella@college.edu", "12345"),
    ("No Department Nia", "", 1, "nia@college.edu", "9988776655"),
    ("Messy Case Max", " ece ", 3, "max@college.edu", "9812345670"),
]


def main():
    from database import get_db_connection
    from werkzeug.security import generate_password_hash

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete existing books/students/issues first")
    parser.add_argument("--yes", action="store_true", help="confirm --reset without prompting")
    parser.add_argument("--dirty", action="store_true", help="add deliberately bad rows for the data-quality demo")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if args.reset:
            if not args.yes and input("This DELETES all books, students and issues. Type YES: ") != "YES":
                print("Aborted.")
                return
            for table in ("issued_books", "books", "students",
                          "monthly_library_stats", "department_library_stats",
                          "book_borrowing_stats", "etl_run_log"):
                cur.execute(f"DELETE FROM {table}")
        else:
            cur.execute("SELECT (SELECT COUNT(*) FROM books) + (SELECT COUNT(*) FROM students)")
            if cur.fetchone()[0] > 0:
                print("Database already has books/students. Use --reset --yes to replace them.")
                return

        data = generate_dataset(date.today())
        cur.executemany(
            "INSERT INTO students (name, department, year, email, phone) VALUES (%s,%s,%s,%s,%s)",
            data["students"])
        cur.executemany(
            "INSERT INTO books (title, author, category, quantity, status) VALUES (%s,%s,%s,%s,'Available')",
            [tuple(b) for b in data["books"]])
        conn.commit()

        cur.execute("SELECT student_id FROM students ORDER BY student_id")
        student_ids = [r[0] for r in cur.fetchall()][:len(data["students"])]
        cur.execute("SELECT book_id FROM books ORDER BY book_id")
        book_ids = [r[0] for r in cur.fetchall()][:len(data["books"])]

        rows, open_books = [], set()
        for b_idx, s_idx, issue_d, due_d, ret_d, fine, status in data["issues"]:
            rows.append((book_ids[b_idx], student_ids[s_idx], issue_d, due_d, ret_d, fine, status))
            if status == "Issued":
                open_books.add(book_ids[b_idx])
        cur.executemany(
            """INSERT INTO issued_books (book_id, student_id, issue_date, due_date, return_date, fine, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""", rows)
        for book_id in open_books:
            cur.execute("UPDATE books SET status='Issued' WHERE book_id=%s", (book_id,))

        if args.dirty:
            cur.executemany(
                "INSERT INTO students (name, department, year, email, phone) VALUES (%s,%s,%s,%s,%s)",
                DIRTY_STUDENTS)
            cur.execute("INSERT INTO books (title, author, category, quantity, status) "
                        "VALUES ('Untitled Gift Donation', '', NULL, 1, 'Issued')")  # Issued with no loan
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (name, email, password) VALUES (%s,%s,%s)",
                        ("Demo Admin", "admin@library.local", generate_password_hash("admin123")))
            print("Created demo login: admin@library.local / admin123")
        conn.commit()
        print(f"Seeded {len(data['students'])} students, {len(data['books'])} books, "
              f"{len(rows)} issue records ({len(open_books)} currently out)."
              + (" Dirty rows added." if args.dirty else ""))
        print("Next: python etl.py")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
