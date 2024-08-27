import sqlite3

def init_db():
    # Initialize the database connection
    conn = sqlite3.connect('rsa_bot_users.db')
    cursor = conn.cursor()

    # Create a table for storing credentials if it doesn't exist
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rsa_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        broker TEXT NOT NULL,
        username TEXT NOT NULL,
        password TEXT NOT NULL
    )
    ''')

    conn.commit()
