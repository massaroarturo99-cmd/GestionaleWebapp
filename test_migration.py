from app import app, get_db, migrate_db
import sqlite3

with app.app_context():
    # Intentionally drop the table to simulate an old DB
    db = get_db()
    db.execute("DROP TABLE IF EXISTS wincar_sync_log")
    db.commit()

    # Run migration
    migrate_db()

    # Check if table was created
    table_info = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wincar_sync_log';").fetchone()
    print("Table created by migrate_db:", bool(table_info))
