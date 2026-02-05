import os

class Config:
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL')

    # Telegram
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    if TELEGRAM_TOKEN:
        TELEGRAM_TOKEN = TELEGRAM_TOKEN.strip()

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
    CHART_URL = os.getenv('CHART_URL', '')
    
    if SPREADSHEET_ID:
        SPREADSHEET_ID = SPREADSHEET_ID.strip()
