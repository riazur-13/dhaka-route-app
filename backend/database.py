import sqlite3


DB_NAME = "fares.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fare_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            distance_km REAL NOT NULL,
            fare_amount REAL NOT NULL,
            route_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_NAME)