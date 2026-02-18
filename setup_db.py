import os
from app.models import init_db, engine
from sqlalchemy import text

def setup_supabase():
    print("Setting up Supabase PostGIS...")
    try:
        init_db()
        print("✓ Database schema initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    # You can override DATABASE_URL here if not set in environment
    # os.environ['DATABASE_URL'] = "postgresql://postgres:qTWmSxeojFaYYiJS@db.lnqpouvvciysonwvzidc.supabase.co:5432/postgres"
    setup_supabase()
