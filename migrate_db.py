import os
from sqlalchemy import create_engine, text
from app.config import Config

def migrate():
    # Fix for SQLAlchemy requiring 'postgresql://' instead of 'postgres://'
    db_url = Config.DATABASE_URL
    if not db_url:
        print("❌ DATABASE_URL not found in environment variables.")
        return

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    print(f"Connecting to database...")
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        try:
            print("Applying migration: changing users.chat_id to BIGINT...")
            # PostgreSQL command to change column type
            conn.execute(text("ALTER TABLE users ALTER COLUMN chat_id TYPE BIGINT;"))
            conn.commit()
            print("✅ Migration successful! chat_id is now BIGINT.")
        except Exception as e:
            print(f"❌ Error during migration: {e}")
            print("Note: If the error says 'column does not exist', check if the table name is correct.")

if __name__ == "__main__":
    migrate()
