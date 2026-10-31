import psycopg2

def ensure_test_database():
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        user="postgres",
        password="postgres",
        dbname="postgres",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'signal_atlas_test'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE signal_atlas_test")
        print("Created database: signal_atlas_test")
    else:
        print("Database signal_atlas_test already exists")
    conn.close()

if __name__ == "__main__":
    ensure_test_database()
