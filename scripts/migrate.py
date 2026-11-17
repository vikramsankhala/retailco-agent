"""Create or upgrade the database without deleting anything (safe on every start-up).

Unlike scripts.seed, this never removes data: pending approvals and refunds survive.
    python -m scripts.migrate
"""
from agent import config, db

if __name__ == "__main__":
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    db.init_db(conn)
    print(f"database ready at {config.DB_PATH}")
