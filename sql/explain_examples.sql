-- Run these in MySQL Workbench / the mysql CLI AFTER seeding data, and keep the output
-- (screenshots or text) for your portfolio. Each query maps to an index in README.md.
-- Tip: also try EXPLAIN ANALYZE (MySQL 8.0.18+) for real row counts and timings.

-- 1. Date-range KPI / trend queries  -> idx_issued_issue_date (type: range)
EXPLAIN SELECT DATE_FORMAT(issue_date, '%Y-%m') AS ym, COUNT(*)
FROM issued_books
WHERE issue_date BETWEEN '2026-01-01' AND '2026-10-07'
GROUP BY ym ORDER BY ym;

-- 2. Overdue books  -> idx_issued_status_due (equality on status, then range on due_date)
EXPLAIN SELECT COUNT(*) FROM issued_books
WHERE status = 'Issued' AND due_date < CURDATE();

-- 3. Top borrowed books  -> idx_issued_issue_date + PRIMARY on books (eq_ref join)
EXPLAIN SELECT b.book_id, b.title, COUNT(*) AS times_issued
FROM issued_books ib JOIN books b ON b.book_id = ib.book_id
WHERE ib.issue_date BETWEEN '2026-01-01' AND '2026-10-07'
GROUP BY b.book_id, b.title ORDER BY times_issued DESC LIMIT 10;

-- 4. Is this book currently out?  -> idx_issued_book_status (ref on book_id, status)
EXPLAIN SELECT 1 FROM issued_books WHERE book_id = 10 AND status = 'Issued';

-- 5. Duplicate email detection  -> idx_students_email (index scan, no filesort of the table)
EXPLAIN SELECT LOWER(TRIM(email)) AS email_key, COUNT(*)
FROM students WHERE email IS NOT NULL GROUP BY email_key HAVING COUNT(*) > 1;

-- 6. Prefix title search  -> idx_books_title.   NOTE: LIKE '%word%' cannot use a B-tree
--    index (leading wildcard); compare the two plans:
EXPLAIN SELECT * FROM books WHERE title LIKE 'Python%';
EXPLAIN SELECT * FROM books WHERE title LIKE '%Python%';

-- Before/after experiment (shows why the index exists):
--   ALTER TABLE issued_books DROP INDEX idx_issued_issue_date;
--   EXPLAIN ...query 1...   -> type: ALL (full table scan)
--   ALTER TABLE issued_books ADD INDEX idx_issued_issue_date (issue_date);
