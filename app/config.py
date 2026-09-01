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
    
    # Stripe
    STRIPE_API_KEY = os.getenv('STRIPE_SECRET_KEY') or os.getenv('STRIPE_API_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

    # Agromonitoring
    AGROMONITORING_API_KEY = os.getenv('AGROMONITORING_API_KEY', '280441f10a0d93bfd62aae39fa4cdcaa')

    # Admin
    ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '1118914866')  # Default to Robson's ID
    if ADMIN_CHAT_ID:
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        except ValueError:
            ADMIN_CHAT_ID = 1118914866

    if SPREADSHEET_ID:
        SPREADSHEET_ID = SPREADSHEET_ID.strip()

    # PRODES tool
    PRODES_GCS_BUCKET = os.getenv('PRODES_GCS_BUCKET')  # sem isso, feature roda sem cache persistente
    PRODES_MAX_CONCURRENT_JOBS = int(os.getenv('PRODES_MAX_CONCURRENT_JOBS', '2'))
    PRODES_POLL_INTERVAL_SECONDS = int(os.getenv('PRODES_POLL_INTERVAL_SECONDS', '20'))
    PRODES_JOB_STALE_MINUTES = int(os.getenv('PRODES_JOB_STALE_MINUTES', '10'))
