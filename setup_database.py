"""
Database Initialization & Seeder Script for OneWorkspace
Coolaire Consolidated Inc. (CCI)
Run this script in PyCharm to bootstrap SQLite database with 180-day telemetry.
"""

import sqlite3
import datetime
import random

DB_NAME = 'oneworkspace.db'

DEPARTMENTS = {
    'Finance & Accounting': {'batch': 'Batch 1', 'lead': 'Maria Santos', 'users': 6},
    'CNC & Treasury': {'batch': 'Batch 1', 'lead': 'Rolando Reyes', 'users': 4},
    'Purchasing': {'batch': 'Batch 1', 'lead': 'Grace Tan', 'users': 5},
    'Sales': {'batch': 'Batch 1', 'lead': 'Carlos Mendoza', 'users': 8},
    'Service': {'batch': 'Batch 1', 'lead': 'Danilo Bautista', 'users': 6},
    'Production': {'batch': 'Batch 2', 'lead': 'Eduardo Castro', 'users': 7},
    'Warehouse': {'batch': 'Batch 2', 'lead': 'Nestor Ramos', 'users': 5},
    'HR': {'batch': 'Batch 2', 'lead': 'Patricia Gomez', 'users': 4},
    'Audit': {'batch': 'Batch 2', 'lead': 'Ramon Villanueva', 'users': 3},
    'Asset': {'batch': 'Batch 3', 'lead': 'Lourdes Morales', 'users': 3},
    'Marketing': {'batch': 'Batch 3', 'lead': 'Kristine Lim', 'users': 4},
    'Imports': {'batch': 'Batch 3', 'lead': 'Ferdinand Diaz', 'users': 3},
    'IT Department': {'batch': 'IT', 'lead': 'Jarick Montojo', 'users': 4},
}

INITIAL_USERS = [
    ('Jarick Montojo', 'jarick.montojo@coolaireconsolidated.com', 'IT Department', 'IT'),
    ('Executive Admin', 'admin@coolaireconsolidated.com', 'IT Department', 'IT'),
    ('Maria Santos', 'maria.santos@coolaireconsolidated.com', 'Finance & Accounting', 'Batch 1'),
    ('Dennis Ramos', 'dennis.ramos@coolaireconsolidated.com', 'Finance & Accounting', 'Batch 1'),
    ('Rolando Reyes', 'rolando.reyes@coolaireconsolidated.com', 'CNC & Treasury', 'Batch 1'),
    ('Grace Tan', 'grace.tan@coolaireconsolidated.com', 'Purchasing', 'Batch 1'),
    ('Carlos Mendoza', 'carlos.mendoza@coolaireconsolidated.com', 'Sales', 'Batch 1'),
    ('Danilo Bautista', 'danilo.bautista@coolaireconsolidated.com', 'Service', 'Batch 1'),
    ('Eduardo Castro', 'eduardo.castro@coolaireconsolidated.com', 'Production', 'Batch 2'),
    ('Nestor Ramos', 'nestor.ramos@coolaireconsolidated.com', 'Warehouse', 'Batch 2'),
    ('Patricia Gomez', 'patricia.gomez@coolaireconsolidated.com', 'HR', 'Batch 2'),
    ('Ramon Villanueva', 'ramon.villanueva@coolaireconsolidated.com', 'Audit', 'Batch 2'),
    ('Lourdes Morales', 'lourdes.morales@coolaireconsolidated.com', 'Asset', 'Batch 3'),
    ('Kristine Lim', 'kristine.lim@coolaireconsolidated.com', 'Marketing', 'Batch 3'),
    ('Ferdinand Diaz', 'ferdinand.diaz@coolaireconsolidated.com', 'Imports', 'Batch 3'),
]

DEFAULT_CHECKLIST = {
    'Finance & Accounting': {'chk1': 1, 'chk2': 1, 'chk3': 1, 'chk4': 0},
    'CNC & Treasury': {'chk1': 1, 'chk2': 1, 'chk3': 0, 'chk4': 0},
    'Purchasing': {'chk1': 1, 'chk2': 1, 'chk3': 0, 'chk4': 0},
    'Sales': {'chk1': 1, 'chk2': 1, 'chk3': 1, 'chk4': 1},
    'Service': {'chk1': 1, 'chk2': 0, 'chk3': 0, 'chk4': 0},
    'Production': {'chk1': 1, 'chk2': 1, 'chk3': 0, 'chk4': 0},
    'Warehouse': {'chk1': 1, 'chk2': 0, 'chk3': 0, 'chk4': 0},
    'HR': {'chk1': 1, 'chk2': 1, 'chk3': 1, 'chk4': 1},
    'Audit': {'chk1': 1, 'chk2': 1, 'chk3': 0, 'chk4': 0},
    'Asset': {'chk1': 0, 'chk2': 0, 'chk3': 0, 'chk4': 0},
    'Marketing': {'chk1': 1, 'chk2': 1, 'chk3': 1, 'chk4': 0},
    'Imports': {'chk1': 1, 'chk2': 0, 'chk3': 0, 'chk4': 0},
    'IT Department': {'chk1': 1, 'chk2': 1, 'chk3': 1, 'chk4': 1},
}


def setup_database():
    print(f"[*] Initializing SQLite database: {DB_NAME} (WAL Mode)")
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_metrics (
            date TEXT,
            email TEXT,
            name TEXT,
            department TEXT,
            batch TEXT,
            docs INTEGER DEFAULT 0,
            sheets INTEGER DEFAULT 0,
            forms INTEGER DEFAULT 0,
            slides INTEGER DEFAULT 0,
            calendar_events INTEGER DEFAULT 0,
            meet_calls INTEGER DEFAULT 0,
            meet_minutes INTEGER DEFAULT 0,
            emails INTEGER DEFAULT 0,
            PRIMARY KEY (date, email)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS department_checklists (
            department TEXT,
            item_id TEXT,
            completed INTEGER DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (department, item_id)
        )
    ''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_date ON daily_metrics(date);')
    c.execute('CREATE INDEX IF NOT EXISTS idx_metrics_dept_date ON daily_metrics(department, date);')

    # Seed Checklist states
    print("[*] Seeding department compliance checklists...")
    now_str = datetime.datetime.utcnow().isoformat()
    for dept, items in DEFAULT_CHECKLIST.items():
        for chk_id, status in items.items():
            c.execute('''
                INSERT OR REPLACE INTO department_checklists (department, item_id, completed, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (dept, chk_id, status, now_str))

    # Generate 180 days of realistic daily metrics
    print("[*] Generating 180 days of historical Workspace telemetry across all units...")
    c.execute("DELETE FROM daily_metrics;")
    today = datetime.date.today()

    random.seed(42)  # Deterministic seed for reproducible realistic data
    inserted_count = 0

    for day_offset in range(0, 180):
        current_date = today - datetime.timedelta(days=day_offset)
        date_str = current_date.isoformat()
        is_weekend = current_date.weekday() >= 5

        for (u_name, u_email, u_dept, u_batch) in INITIAL_USERS:
            # Multiplier based on department activity
            dept_factor = 1.4 if u_dept in ['Sales', 'Finance & Accounting', 'IT Department'] else 0.9

            if is_weekend:
                docs = 1 if random.random() < 0.1 else 0
                sheets = 1 if random.random() < 0.1 else 0
                forms = 0
                slides = 0
                calendar_events = 0
                meet_calls = 0
                meet_minutes = 0
                emails = random.randint(0, 2)
            else:
                docs = int(random.randint(0, 4) * dept_factor)
                sheets = int(random.randint(0, 6) * dept_factor)
                forms = 1 if random.random() < 0.3 else 0
                slides = 1 if random.random() < 0.25 else 0
                calendar_events = random.randint(1, 4)
                meet_calls = random.randint(1, 3)
                meet_minutes = meet_calls * random.randint(15, 45)
                emails = int(random.randint(8, 25) * dept_factor)

            c.execute('''
                INSERT INTO daily_metrics 
                (date, email, name, department, batch, docs, sheets, forms, slides, calendar_events, meet_calls, meet_minutes, emails)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                date_str, u_email, u_name, u_dept, u_batch,
                docs, sheets, forms, slides, calendar_events, meet_calls, meet_minutes, emails
            ))
            inserted_count += 1

    conn.commit()
    conn.close()
    print(f"[+] Successfully seeded {inserted_count} daily telemetry records into {DB_NAME}!")


if __name__ == '__main__':
    setup_database()
