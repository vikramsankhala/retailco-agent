"""Create data/retailco.db with the lab's sample customers, orders and shipments."""
from agent import config, db

if __name__ == "__main__":
    config.DB_PATH.unlink(missing_ok=True)
    conn = db.connect()
    db.init_db(conn)
    print(f"seeded {config.DB_PATH}")
