from app.charts import generate_chart
from app.models import get_recent_prices
import os

def test_real_data():
    print("Fetching real data from database...")
    data = get_recent_prices()
    
    if not data:
        print("No data found in database. Please ensure the database is populated.")
        return
        
    print(f"Found {len(data)} records. Generating chart...")
    path = generate_chart(data)
    
    if path:
        print(f"Chart generated successfully at: {path}")
    else:
        print("Failed to generate chart with real data.")

if __name__ == "__main__":
    test_real_data()
