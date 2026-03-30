"""
Seed script for Telco Customer Churn database.
Loads the WA_Fn-UseC_-Telco-Customer-Churn.csv into a local SQLite database.

Run once before starting the MCP server:
    python seed_db.py

Or point to a different CSV:
    python seed_db.py --input /path/to/your/data.csv
"""

import argparse
import csv
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telco_churn.db")
DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "WA_Fn-UseC_-Telco-Customer-Churn.csv")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customerID          TEXT PRIMARY KEY,
    gender              TEXT,
    SeniorCitizen       INTEGER,
    Partner             TEXT,
    Dependents          TEXT,
    tenure              INTEGER,
    PhoneService        TEXT,
    MultipleLines       TEXT,
    InternetService     TEXT,
    OnlineSecurity      TEXT,
    OnlineBackup        TEXT,
    DeviceProtection    TEXT,
    TechSupport         TEXT,
    StreamingTV         TEXT,
    StreamingMovies     TEXT,
    Contract            TEXT,
    PaperlessBilling    TEXT,
    PaymentMethod       TEXT,
    MonthlyCharges      REAL,
    TotalCharges        REAL,
    Churn               INTEGER  -- 1 = churned, 0 = retained
);

CREATE INDEX IF NOT EXISTS idx_churn       ON customers (Churn);
CREATE INDEX IF NOT EXISTS idx_contract    ON customers (Contract);
CREATE INDEX IF NOT EXISTS idx_internet    ON customers (InternetService);
CREATE INDEX IF NOT EXISTS idx_tenure      ON customers (tenure);
CREATE INDEX IF NOT EXISTS idx_payment     ON customers (PaymentMethod);
"""


def parse_row(row: dict) -> tuple:
    """Clean and type-cast a CSV row for insertion."""
    # TotalCharges has 11 blank values — fill with tenure * MonthlyCharges
    monthly = float(row["MonthlyCharges"]) if row["MonthlyCharges"].strip() else 0.0
    tenure  = int(row["tenure"]) if row["tenure"].strip() else 0
    try:
        total = float(row["TotalCharges"])
    except (ValueError, KeyError):
        total = round(tenure * monthly, 2)

    return (
        row["customerID"].strip(),
        row["gender"].strip(),
        int(row["SeniorCitizen"]),
        row["Partner"].strip(),
        row["Dependents"].strip(),
        tenure,
        row["PhoneService"].strip(),
        row["MultipleLines"].strip(),
        row["InternetService"].strip(),
        row["OnlineSecurity"].strip(),
        row["OnlineBackup"].strip(),
        row["DeviceProtection"].strip(),
        row["TechSupport"].strip(),
        row["StreamingTV"].strip(),
        row["StreamingMovies"].strip(),
        row["Contract"].strip(),
        row["PaperlessBilling"].strip(),
        row["PaymentMethod"].strip(),
        monthly,
        total,
        1 if row["Churn"].strip() == "Yes" else 0,
    )


def seed(csv_path: str = DEFAULT_CSV, db_path: str = DB_PATH) -> None:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"CSV not found at {csv_path}\n"
            f"Usage: python seed_db.py --input /path/to/WA_Fn-UseC_-Telco-Customer-Churn.csv"
        )

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [parse_row(r) for r in reader]

    conn.executemany(
        "INSERT OR REPLACE INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()

    # Quick sanity check
    total    = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    churned  = conn.execute("SELECT COUNT(*) FROM customers WHERE Churn=1").fetchone()[0]
    retained = total - churned
    conn.close()

    print(f"✅ Database seeded at {db_path}")
    print(f"   Total customers : {total:,}")
    print(f"   Churned         : {churned:,} ({churned/total*100:.1f}%)")
    print(f"   Retained        : {retained:,} ({retained/total*100:.1f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the telco churn SQLite database.")
    parser.add_argument("--input",  default=DEFAULT_CSV, help="Path to CSV file")
    parser.add_argument("--db",     default=DB_PATH,     help="Path to SQLite database output")
    args = parser.parse_args()
    seed(args.input, args.db)