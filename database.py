
import sqlite3
from pathlib import Path

# Database file location
DATABASE = Path(__file__).resolve().parent / "payflow.db"


def get_db():

    conn = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    # Enable foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON")

    # Wait for another database transaction if necessary
    conn.execute("PRAGMA busy_timeout = 10000")

    return conn


def init_db():

    conn = get_db()

    try:

        conn.executescript("""

        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            email TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL

        );


        CREATE TABLE IF NOT EXISTS accounts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER UNIQUE NOT NULL,

            balance INTEGER NOT NULL DEFAULT 0
                CHECK(balance >= 0),

            FOREIGN KEY(user_id)
                REFERENCES users(id)

        );


        CREATE TABLE IF NOT EXISTS transactions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            sender_id INTEGER NOT NULL,

            receiver_id INTEGER NOT NULL,

            amount INTEGER NOT NULL
                CHECK(amount > 0),

            status TEXT NOT NULL,

            idempotency_key TEXT UNIQUE NOT NULL,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(sender_id)
                REFERENCES users(id),

            FOREIGN KEY(receiver_id)
                REFERENCES users(id),

            CHECK(sender_id != receiver_id)

        );

        """)

        print("Database tables created successfully!")

    finally:

        conn.close()
