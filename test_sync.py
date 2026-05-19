from app import app, sincronizza_foto_wincar, get_db

with app.app_context():
    db = get_db()

    # 1. Check schemas
    table_info = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wincar_sync_log';").fetchone()
    print("Table exists:", bool(table_info))

    # Check syntax in the function
    import ast
    with open('app.py', 'r') as f:
        ast.parse(f.read())
        print("Syntax is valid")
