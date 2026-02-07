from app.charts import generate_chart
from datetime import datetime, timedelta
import random

def test():
    countries = ['Brasil', 'Argentina', 'Uruguai', 'Paraguai', 'Australia', 'Irlanda', 'Estados Unidos', 'China']
    data = []
    
    start_date = datetime.now() - timedelta(days=365)
    
    # Realistic base prices and trends based on recent market (approximate US$/@)
    base_prices = {
        'Brasil': 60,
        'Argentina': 70,
        'Uruguai': 80,
        'Paraguai': 65,
        'Australia': 85,
        'Irlanda': 120,
        'Estados Unidos': 110,
        'China': 140
    }
    
    for country, base_price in base_prices.items():
        current_price = base_price
        for i in range(52): # Weekly points for a year
            # Introduce random gaps (10% chance to skip a week)
            if random.random() < 0.1:
                continue
                
            date = start_date + timedelta(weeks=i)
            date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Add some "volatility" but with a general upward trend
            current_price += random.uniform(-2, 3)
            data.append({
                'country': country,
                'price': current_price,
                'date': date
            })
            
    print("Generating test chart...")
    path = generate_chart(data)
    if path:
        print(f"Chart generated at: {path}")
    else:
        print("Failed to generate chart")

if __name__ == "__main__":
    test()
