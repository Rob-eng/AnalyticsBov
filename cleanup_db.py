from app.models import car_engine
from sqlalchemy import text

def cleanup():
    print("WARNING: This will DELETE ALL DATA from 'car_properties'.")
    print("Beginning truncation...")
    try:
        with car_engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE car_properties RESTART IDENTITY CASCADE;"))
            if hasattr(conn, 'commit'):
                conn.commit()
        print("✅ Success: Table 'car_properties' truncated.")
    except Exception as e:
        print(f"❌ Error truncating table: {e}")

if __name__ == "__main__":
    confirm = input("Are you sure you want to WIPEOUT ALL CAR DATA? (yes/no): ")
    if confirm.lower() == "yes":
        cleanup()
    else:
        print("Aborted.")
