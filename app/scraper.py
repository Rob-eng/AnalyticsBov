import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from datetime import datetime
from app.config import Config
from app.models import SessionLocal, PriceHistory

def fetch_data():
    url = "https://www.scotconsultoria.com.br/cotacoes/boi-no-mundo/"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Logic to parse the specific table structure of Scot Consultoria
    # Note: This selector might need adjustment based on actual site structure
    # Checking for the table. usually it's inside a div capable of scrolling or clear table tag
    data = []
    
    # Finding the table - this is a best-guess based on common layouts, 
    # might need refinement if the site changes.
    # Looking for tables with price data.
    tables = soup.find_all('table')
    
    if not tables:
        print("No tables found")
        return []

    # Assuming the first relevant table contains the data
    # We iterate and look for 'País' and 'Preço' headers or similar structure if possible
    # For now, let's assume the first table is the one or we look for specific headers.
    
    target_table = None
    for table in tables:
        if 'País' in table.get_text() and 'US$' in table.get_text():
            target_table = table
            break
            
    if not target_table:
        # Fallback to first table if specific text not found, or log error
        if tables:
            target_table = tables[0]
        else:
            return []

    rows = target_table.find_all('tr')
    
    current_date = datetime.now()
    
    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 2:
            country_text = cols[0].get_text(strip=True)
            price_text = cols[1].get_text(strip=True)
            
            # Basic validation to ensure it's data
            if not country_text or not price_text:
                continue
                
            # Clean price string (remove 'US$', replace ',' with '.')
            try:
                # Remove non-numeric chars except dot and comma
                clean_price = price_text.replace('US$', '').replace(',', '.').strip()
                price = float(clean_price)
                
                data.append({
                    'country': country_text,
                    'price': price,
                    'date': current_date
                })
            except ValueError:
                continue
                
    return data

def update_sheet(data):
    try:
        if not Config.GOOGLE_SHEETS_CREDENTIALS:
            print("No Google Sheets credentials provided.")
            return

        creds_dict = json.loads(Config.GOOGLE_SHEETS_CREDENTIALS)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(Config.SPREADSHEET_ID).sheet1
        
        for item in data:
            row = [
                item['country'],
                item['price'],
                item['date'].strftime('%Y-%m-%d %H:%M:%S')
            ]
            sheet.append_row(row)
            
    except Exception as e:
        print(f"Error updating sheet: {e}")

def save_to_db(data):
    session = SessionLocal()
    try:
        for item in data:
            record = PriceHistory(
                country=item['country'],
                price=item['price'],
                date=item['date']
            )
            session.add(record)
        session.commit()
    except Exception as e:
        print(f"Error saving to DB: {e}")
        session.rollback()
    finally:
        session.close()

def run_scraping_cycle():
    print("Starting scraping cycle...")
    data = fetch_data()
    if data:
        print(f"Found {len(data)} records.")
        save_to_db(data)
        update_sheet(data)
        return data
    else:
        print("No data found.")
        return []
