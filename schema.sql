-- File: schema.sql
-- Defines the database structure for Poddar Enterprise

DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS businesses;
DROP TABLE IF EXISTS attendance;
DROP TABLE IF EXISTS payments;

CREATE TABLE businesses (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL UNIQUE,
color TEXT DEFAULT '#cccccc'
);

CREATE TABLE users (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL,
phone TEXT,
role TEXT NOT NULL DEFAULT 'employee', -- 'employee' or 'manager'
pin TEXT NOT NULL DEFAULT '1234',
daily_wage REAL DEFAULT 0,
business_id INTEGER,
is_active INTEGER NOT NULL DEFAULT 1, -- 1 for active, 0 for terminated
FOREIGN KEY (business_id) REFERENCES businesses (id)
);

CREATE TABLE attendance (
id INTEGER PRIMARY KEY AUTOINCREMENT,
employee_id INTEGER NOT NULL,
timestamp DATETIME NOT NULL,
event_type TEXT NOT NULL, -- 'Start' or 'End'
photo_path TEXT,
details TEXT,
notes TEXT, -- New column for daily work notes
FOREIGN KEY (employee_id) REFERENCES users (id)
);

CREATE TABLE payments (
id INTEGER PRIMARY KEY AUTOINCREMENT,
employee_id INTEGER NOT NULL,
amount REAL NOT NULL,
payment_type TEXT NOT NULL, -- 'Payment', 'Advance', or 'Wages Paid'
date TEXT NOT NULL,
notes TEXT,
FOREIGN KEY (employee_id) REFERENCES users (id)
);
