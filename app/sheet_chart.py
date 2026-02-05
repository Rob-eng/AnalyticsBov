import requests
from app.config import Config

def get_chart_from_sheet():
    """
    Fetch the chart image from Google Sheets using the published chart URL.
    
    The chart URL should be set in the CHART_URL environment variable.
    Format: https://docs.google.com/spreadsheets/d/e/{PUBLISH_ID}/pubchart?oid={CHART_ID}&format=image
    
    Returns:
        str: Path to the downloaded chart image, or None if failed
    """
    try:
        # Check if CHART_URL is configured
        if not Config.CHART_URL:
            print("CHART_URL not configured, cannot fetch chart from sheet")
            return None
        
        # Convert the URL to PNG format if it's interactive
        chart_url = Config.CHART_URL
        if 'format=interactive' in chart_url:
            chart_url = chart_url.replace('format=interactive', 'format=image')
        elif 'format=' not in chart_url:
            # Add format parameter if not present
            chart_url += '&format=image' if '?' in chart_url else '?format=image'
        
        # Add width parameter for higher resolution (Google Sheets supports up to 2048px)
        # Default is around 600px, we'll use 1600px for much better quality
        if 'w=' not in chart_url and 'width=' not in chart_url:
            chart_url += '&w=1600'
        
        print(f"Fetching chart from: {chart_url}")
        
        # Download the chart image (no authentication needed for published charts)
        response = requests.get(chart_url, timeout=10)
        
        if response.status_code == 200:
            output_path = '/tmp/sheet_chart.png'
            with open(output_path, 'wb') as f:
                f.write(response.content)
            print(f"Chart downloaded successfully to {output_path}")
            return output_path
        else:
            print(f"Failed to download chart. Status code: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Error fetching chart from sheet: {e}")
        import traceback
        print(traceback.format_exc())
        return None
