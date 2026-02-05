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
    
    # Admin
    ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '1118914866')  # Default to Robson's ID
    if ADMIN_CHAT_ID:
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        except ValueError:
            ADMIN_CHAT_ID = 1118914866
    
    if SPREADSHEET_ID:
        SPREADSHEET_ID = SPREADSHEET_ID.strip()
