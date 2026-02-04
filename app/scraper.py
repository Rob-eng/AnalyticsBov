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
        
        # Get header to determine column positions
        header = sheet.row_values(1)
        
        # Map country names to column indices (0-indexed for list building)
        country_columns = {}
        for idx, col_name in enumerate(header):
            clean_name = col_name.strip()
            # Match country names
            if 'brasil' in clean_name.lower():
                country_columns['Brasil'] = idx
            elif 'argentina' in clean_name.lower():
                country_columns['Argentina'] = idx
            elif 'uruguai' in clean_name.lower():
                country_columns['Uruguai'] = idx
            elif 'paraguai' in clean_name.lower():
                country_columns['Paraguai'] = idx
            elif 'australia' in clean_name.lower() or 'austrália' in clean_name.lower():
                country_columns['Australia'] = idx
                country_columns['Austrália'] = idx
            elif 'irlanda' in clean_name.lower():
                country_columns['Irlanda'] = idx
            elif 'estados unidos' in clean_name.lower():
                country_columns['Estados Unidos'] = idx
            elif 'china' in clean_name.lower():
                country_columns['China'] = idx
        
        if not data:
            return
            
        # Group data by date (assuming all data is from the same scrape/date)
        date_obj = data[0]['date']
        date_str = date_obj.strftime('%d/%m/%Y')
        
        # Find if this date already exists in the sheet
        all_dates = sheet.col_values(1)  # Column A contains dates
        
        row_index = None
        for idx, existing_date in enumerate(all_dates[1:], start=2):  # Skip header
            if existing_date.strip() == date_str:
                row_index = idx
                break
        
        # If date doesn't exist, find next empty row
        if row_index is None:
            row_index = len(all_dates) + 1
        
        # Build the complete row with all values
        # Initialize row with empty strings matching header length
        row_data = [''] * len(header)
        row_data[0] = date_str  # First column is the date
        
        # Fill in prices for each country
        for item in data:
            country = item['country']
            price = item['price']
            
            if country in country_columns:
                col_index = country_columns[country]
                row_data[col_index] = price
                print(f"Preparing {country} price: {price}")
        
        # Update the entire row at once
        cell_range = f'A{row_index}:{chr(65 + len(header) - 1)}{row_index}'
        sheet.update(cell_range, [row_data])
        print(f"Updated row {row_index} with date {date_str}")
            
    except Exception as e:
        print(f"Error updating sheet: {e}")
        import traceback
        print(traceback.format_exc())

def save_to_db(data):
    session = SessionLocal()
    try:
        for item in data:
            # Check if record exists for this country on this specific day (ignoring time)
            # We assume 'date' in item is a datetime object
            start_of_day = item['date'].replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = item['date'].replace(hour=23, minute=59, second=59, microsecond=999999)
            
            exists = session.query(PriceHistory).filter(
                PriceHistory.country == item['country'],
                PriceHistory.date >= start_of_day,
                PriceHistory.date <= end_of_day
            ).first()
            
            if not exists:
                record = PriceHistory(
                    country=item['country'],
                    price=item['price'],
                    date=item['date']
                )
                session.add(record)
                print(f"Added record for {item['country']}")
            else:
                print(f"Skipped duplicate for {item['country']} on {start_of_day.date()}")
                
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
        # Save to DB (with duplicate check now)
        save_to_db(data)
        
        # NOTE: We continue to append to the sheet in 'log' format (Country, Price, Date)
        # Changing this to matched the wide format is complex without rewriting the whole sheet logic.
        # For now, we ensure the DB is clean.
        update_sheet(data)
        
        return data
    else:
        print("No data found.")
        return []

def import_history_from_sheet():
    print("Starting history import from Google Sheets...")
    session = SessionLocal()
    count = 0
    try:
        if not Config.GOOGLE_SHEETS_CREDENTIALS:
            return "❌ Credenciais do Google Sheets não configuradas."

        creds_dict = json.loads(Config.GOOGLE_SHEETS_CREDENTIALS)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(Config.SPREADSHEET_ID).sheet1
        all_values = sheet.get_all_values()
        
        if not all_values:
            return "⚠️ Planilha vazia."

        # Detect format based on Row 1 (Header)
        # Wide format expectation: Col A blank/Date, B=Brasil, C=Argentina... etc.
        header = all_values[0]
        
        # Mapping country name to column index based on the screenshot/user info
        # Header: [Action, Brasil, Argentina, Uruguai, Paraguai, Australia, Irlanda, Estados Unidos, China]
        # Or simple: Check if these names exist in the first row
        country_map = {}
        target_countries = ['Brasil', 'Argentina', 'Uruguai', 'Paraguai', 'Australia', 'Irlanda', 'Estados Unidos', 'China']
        
        for idx, col_name in enumerate(header):
            clean_name = col_name.strip()
            # Loose matching
            for target in target_countries:
                if target.lower() in clean_name.lower():
                    country_map[idx] = target
        
        print(f"Detected columns: {country_map}")

        # Iterate rows starting from 1 (skip header)
        for row_idx, row in enumerate(all_values[1:], start=1):
            # If row is less than parsing width, stop or skip
            if not row:
                continue
                
            # Column A (index 0) should be the date
            date_str = row[0].strip()
            if not date_str:
                continue
                
            # Parse Date
            try:
                date_obj = datetime.strptime(date_str, '%d/%m/%Y')
            except ValueError:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                except:
                    # If date parsing fails, it might be one of the 'log' rows at the bottom (Country, Price, Date)
                    # Let's try to handle that format too to be robust
                    if len(row) >= 3:
                        try:
                            # Try the format: Country, Price, Date-Time
                            log_country = row[0]
                            log_price = float(row[1].replace(',', '.'))
                            log_date = datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S')
                            
                            # Add this record
                            start_day = log_date.replace(hour=0, minute=0, second=0, microsecond=0)
                            end_day = log_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                            
                            exists = session.query(PriceHistory).filter(
                                PriceHistory.country == log_country,
                                PriceHistory.date >= start_day,
                                PriceHistory.date <= end_day
                            ).first()
                            
                            if not exists:
                                record = PriceHistory(country=log_country, price=log_price, date=log_date)
                                session.add(record)
                                count += 1
                            continue # Successfully handled as log row
                        except:
                            pass
                    continue # Skip if neither format matches

            # If we are here, it's likely a Wide Format row (Date in Col A)
            # Iterate through mapped columns
            for col_idx, country_name in country_map.items():
                if col_idx < len(row):
                    price_val_str = row[col_idx].strip()
                    if not price_val_str:
                        continue
                        
                    try:
                        # Handle potential localized floats
                        clean_price = price_val_str.replace('US$', '').replace(',', '.').strip()
                        price = float(clean_price)
                        
                        # Check existance
                        # Since wide format usually has Time=00:00:00, we check strict date or range
                        exists = session.query(PriceHistory).filter(
                            PriceHistory.country == country_name,
                            PriceHistory.date == date_obj
                        ).first()
                        
                        if not exists:
                            record = PriceHistory(country=country_name, price=price, date=date_obj)
                            session.add(record)
                            count += 1
                    except ValueError:
                        continue

        session.commit()
        return f"✅ Importação concluída! {count} novos registros."
        
    except Exception as e:
        print(f"Error importing history: {e}")
        session.rollback()
        return f"❌ Erro na importação: {str(e)}"
    finally:
        session.close()
