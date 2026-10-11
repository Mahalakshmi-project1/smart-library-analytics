-- ============================================================================
-- Smart Library Management & Analytics System - MySQL 8.0 schema
-- Layers:  1) transactional tables   2) analytics (summary) tables   3) ETL log
-- Run with:  python init_db.py        (idempotent, also upgrades older databases)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) TRANSACTIONAL LAYER
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(150) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS books (
    book_id     INT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(255) NOT NULL,
    author      VARCHAR(150) NOT NULL,
    category    VARCHAR(80)  NULL,
    quantity    INT          NOT NULL DEFAULT 1,
    status      VARCHAR(20)  NOT NULL DEFAULT 'Available',
    CONSTRAINT chk_books_quantity CHECK (quantity > 0),
    CONSTRAINT chk_books_status   CHECK (status IN ('Available', 'Issued')),
    INDEX idx_books_title    (title),
    INDEX idx_books_author   (author),
    INDEX idx_books_category (category)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS students (
    student_id  INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    department  VARCHAR(80)  NULL,
    year        INT          NULL,
    email       VARCHAR(150) NULL,
    phone       VARCHAR(20)  NULL,
    INDEX idx_students_department (department),
    INDEX idx_students_email      (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS issued_books (
    issue_id    INT AUTO_INCREMENT PRIMARY KEY,
    book_id     INT          NOT NULL,
    student_id  INT          NOT NULL,
    issue_date  DATE         NOT NULL,
    due_date    DATE         NOT NULL,
    return_date DATE         NULL,
    fine        DECIMAL(8,2) NOT NULL DEFAULT 0,
    status      VARCHAR(20)  NOT NULL DEFAULT 'Issued',
    CONSTRAINT chk_issue_fine   CHECK (fine >= 0),
    CONSTRAINT chk_issue_status CHECK (status IN ('Issued', 'Returned')),
    CONSTRAINT fk_issued_book    FOREIGN KEY (book_id)
        REFERENCES books (book_id)       ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_issued_student FOREIGN KEY (student_id)
        REFERENCES students (student_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    INDEX idx_issued_issue_date    (issue_date),
    INDEX idx_issued_return_date   (return_date),
    INDEX idx_issued_status_due    (status, due_date),
    INDEX idx_issued_book_status   (book_id, status),
    INDEX idx_issued_student_date  (student_id, issue_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 2) ANALYTICS LAYER (rebuilt by the ETL job: python etl.py)
--    Denormalised on purpose: BI tools (Power BI / Tableau) can read these
--    tables directly. No foreign keys: they are a derived snapshot, refreshed
--    by DELETE + INSERT inside one transaction.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS monthly_library_stats (
    month               CHAR(7)       NOT NULL PRIMARY KEY,   -- 'YYYY-MM'
    books_issued        INT           NOT NULL DEFAULT 0,
    books_returned      INT           NOT NULL DEFAULT 0,
    unique_borrowers    INT           NOT NULL DEFAULT 0,
    late_returns        INT           NOT NULL DEFAULT 0,
    fine_collected      DECIMAL(10,2) NOT NULL DEFAULT 0,
    avg_loan_days       DECIMAL(6,2)  NULL,
    return_rate_pct     DECIMAL(5,2)  NULL,
    refreshed_at        DATETIME      NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS department_library_stats (
    department              VARCHAR(80)   NOT NULL PRIMARY KEY,
    total_students          INT           NOT NULL DEFAULT 0,
    active_borrowers        INT           NOT NULL DEFAULT 0,
    total_issues            INT           NOT NULL DEFAULT 0,
    total_returns           INT           NOT NULL DEFAULT 0,
    currently_issued        INT           NOT NULL DEFAULT 0,
    overdue_open            INT           NOT NULL DEFAULT 0,
    fine_collected          DECIMAL(10,2) NOT NULL DEFAULT 0,
    avg_issues_per_student  DECIMAL(6,2)  NULL,
    refreshed_at            DATETIME      NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS book_borrowing_stats (
    book_id             INT           NOT NULL PRIMARY KEY,
    title               VARCHAR(255)  NOT NULL,
    author              VARCHAR(150)  NULL,
    category            VARCHAR(80)   NULL,
    times_issued        INT           NOT NULL DEFAULT 0,
    times_returned      INT           NOT NULL DEFAULT 0,
    currently_issued    INT           NOT NULL DEFAULT 0,
    total_fine          DECIMAL(10,2) NOT NULL DEFAULT 0,
    avg_loan_days       DECIMAL(6,2)  NULL,
    last_issued_date    DATE          NULL,
    popularity_rank     INT           NOT NULL,
    refreshed_at        DATETIME      NOT NULL,
    INDEX idx_bbs_rank (popularity_rank)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 3) ETL RUN LOG (observability for the pipeline)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id           INT AUTO_INCREMENT PRIMARY KEY,
    started_at       DATETIME     NOT NULL,
    finished_at      DATETIME     NOT NULL,
    status           VARCHAR(10)  NOT NULL,                  -- SUCCESS / FAILED
    source_rows      INT          NOT NULL DEFAULT 0,
    rejected_rows    INT          NOT NULL DEFAULT 0,
    monthly_rows     INT          NOT NULL DEFAULT 0,
    department_rows  INT          NOT NULL DEFAULT 0,
    book_rows        INT          NOT NULL DEFAULT 0,
    message          VARCHAR(255) NULL
) ENGINE=InnoDB;
