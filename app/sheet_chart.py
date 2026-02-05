import requests
import json
from app.config import Config
from oauth2client.service_account import ServiceAccountCredentials
import gspread

def get_chart_from_sheet():
    """
    Fetch the chart image from Google Sheets.
    
    This function retrieves the first chart from the spreadsheet and downloads it as an image.
    The chart must exist in the Google Sheet for this to work.
    
    Returns:
        str: Path to the downloaded chart image, or None if failed
    """
    try:
        if not Config.GOOGLE_SHEETS_CREDENTIALS:
            print("No Google Sheets credentials provided.")
            return None

        creds_dict = json.loads(Config.GOOGLE_SHEETS_CREDENTIALS)
        scope = ['https://spreadsheets.google.com/feeds', 
                 'https://www.googleapis.com/auth/drive',
                 'https://www.googleapis.com/auth/spreadsheets']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Open the spreadsheet
        spreadsheet = client.open_by_key(Config.SPREADSHEET_ID)
        sheet = spreadsheet.sheet1
        
        # Get spreadsheet metadata to find charts
        # Note: gspread doesn't directly support chart retrieval, so we'll use the Sheets API
        from googleapiclient.discovery import build
        
        service = build('sheets', 'v4', credentials=creds)
        
        # Get spreadsheet details including charts
        spreadsheet_data = service.spreadsheets().get(
            spreadsheetId=Config.SPREADSHEET_ID,
            fields='sheets(charts(chartId,position))'
        ).execute()
        
        # Find the first chart
        chart_id = None
        for sheet_data in spreadsheet_data.get('sheets', []):
            charts = sheet_data.get('charts', [])
            if charts:
                chart_id = charts[0]['chartId']
                break
        
        if not chart_id:
            print("No chart found in the spreadsheet")
            return None
        
        # Construct the chart export URL
        # Format: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export/chart?id={CHART_ID}&format=image/png
        chart_url = f"https://docs.google.com/spreadsheets/d/{Config.SPREADSHEET_ID}/export/chart?id={chart_id}&format=image/png"
        
        print(f"Fetching chart from: {chart_url}")
        
        # Download the chart image with authentication
        # We need to use the access token from credentials
        creds.get_access_token()  # Refresh if needed
        headers = {
            'Authorization': f'Bearer {creds.access_token}'
        }
        
        response = requests.get(chart_url, headers=headers)
        
        if response.status_code == 200:
            output_path = '/tmp/sheet_chart.png'
            with open(output_path, 'wb') as f:
                f.write(response.content)
            print(f"Chart downloaded successfully to {output_path}")
            return output_path
        else:
            print(f"Failed to download chart. Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"Error fetching chart from sheet: {e}")
        import traceback
        print(traceback.format_exc())
        return None
