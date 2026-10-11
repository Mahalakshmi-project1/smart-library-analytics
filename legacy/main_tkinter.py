from tkinter import *
import mysql.connector

# Database Connection
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root123",
    database="library_db1"
)

cursor = conn.cursor()

# Add Book
def add_book():
    title = title_entry.get()
    author = author_entry.get()
    quantity = quantity_entry.get()

    query = """
    INSERT INTO books(title, author, quantity)
    VALUES (%s,%s,%s)
    """

    cursor.execute(query, (title, author, quantity))
    conn.commit()

    status_label.config(text="Book Added Successfully!")

# View Books
def view_books():
    cursor.execute("SELECT * FROM books")
    rows = cursor.fetchall()

    result_text.delete(1.0, END)

    for row in rows:
        result_text.insert(END, str(row) + "\n")

# Search Book
def search_book():
    keyword = title_entry.get()

    query = """
    SELECT * FROM books
    WHERE title LIKE %s OR author LIKE %s
    """

    cursor.execute(
        query,
        ("%" + keyword + "%", "%" + keyword + "%")
    )

    rows = cursor.fetchall()

    result_text.delete(1.0, END)

    if len(rows) == 0:
        result_text.insert(END, "No matching books found")
    else:
        for row in rows:
            result_text.insert(END, str(row) + "\n")

# Delete Book
def delete_book():
    book_id = bookid_entry.get()

    query = "DELETE FROM books WHERE book_id=%s"

    cursor.execute(query, (book_id,))
    conn.commit()

    status_label.config(text="Book Deleted Successfully!")

    view_books()

# Issue Book
def issue_book():
    book_id = bookid_entry.get()

    query = """
    UPDATE books
    SET status='Issued'
    WHERE book_id=%s
    """

    cursor.execute(query, (book_id,))
    conn.commit()

    status_label.config(text="Book Issued Successfully!")

    view_books()

# Return Book
def return_book():
    book_id = bookid_entry.get()

    query = """
    UPDATE books
    SET status='Available'
    WHERE book_id=%s
    """

    cursor.execute(query, (book_id,))
    conn.commit()

    status_label.config(text="Book Returned Successfully!")

    view_books()

# GUI
root = Tk()
root.title("Library Management System")
root.geometry("800x650")

Label(
    root,
    text="Library Management System",
    font=("Arial", 20, "bold")
).pack(pady=10)

Label(root, text="Book Title / Search").pack()
title_entry = Entry(root, width=40)
title_entry.pack()

Label(root, text="Author").pack()
author_entry = Entry(root, width=40)
author_entry.pack()

Label(root, text="Quantity").pack()
quantity_entry = Entry(root, width=40)
quantity_entry.pack()

Label(root, text="Book ID").pack()
bookid_entry = Entry(root, width=40)
bookid_entry.pack()

Button(
    root,
    text="Add Book",
    command=add_book,
    bg="lightgreen",
    width=20
).pack(pady=5)

Button(
    root,
    text="View Books",
    command=view_books,
    bg="lightblue",
    width=20
).pack(pady=5)

Button(
    root,
    text="Search Book",
    command=search_book,
    bg="yellow",
    width=20
).pack(pady=5)

Button(
    root,
    text="Delete Book",
    command=delete_book,
    bg="red",
    width=20
).pack(pady=5)

Button(
    root,
    text="Issue Book",
    command=issue_book,
    bg="orange",
    width=20
).pack(pady=5)

Button(
    root,
    text="Return Book",
    command=return_book,
    bg="lightpink",
    width=20
).pack(pady=5)

status_label = Label(root, text="", fg="green")
status_label.pack(pady=10)

result_text = Text(root, height=15, width=90)
result_text.pack()

root.mainloop()

conn.close()