import requests
import re
from datetime import datetime

def parse_coordinates(text):
    """
    Parses various coordinate formats.
    Supported:
    - -20.94, -48.48
    - 20.94S, 48.48W
    - 20° 56' 58" S, 48° 28' 45" W (Full DMS)
    - 20 56 S, 48 28 W (Simple space/letter)
    Returns: (lat, lon) or None
    """
    text = text.strip()
    
    # 1. Decimal format: -20.94, -48.48
    decimal_match = re.match(r"^\s*(-?\d+\.?\d*)\s*[,;\s]\s*(-?\d+\.?\d*)\s*$", text)
    if decimal_match:
        try:
            return float(decimal_match.group(1)), float(decimal_match.group(2))
        except ValueError:
            pass

    # 2. DMS/Letter format variations
    # Regex to find two sets of numbers + directions
    # Example: 20° 56' 58" S or 20 56 S
    part_regex = r"(\d+\.?\d*)\s*[°\s]*\s*(\d+\.?\d*)?[\'\s]*\s*(\d+\.?\d*)?[\"\s]*\s*([NSnsEWewOo])"
    matches = re.findall(part_regex, text)
    
    if len(matches) == 2:
        results = []
        for m in matches:
            d = float(m[0])
            m_val = float(m[1]) if m[1] else 0
            s = float(m[2]) if m[2] else 0
            dir = m[3].upper()
            
            val = d + (m_val / 60.0) + (s / 3600.0)
            if dir in ['S', 'W', 'O']:
                val = -val
            results.append(val)
        return results[0], results[1]

    return None

def extract_coords_from_url(text):
    """
    Extracts coordinates from Google Maps URLs.
    Supports:
    - Long URLs: .../@-20.9481604,-48.4815467,15z...
    - Short URLs: https://maps.app.goo.gl/XXXX via redirect
    Returns: (lat, lon) or None
    """
    # 1. Check for long URL patterns
    # Pattern A: @lat,lon,
    # Pattern B: q=lat,lon
    patterns = [
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)"
    ]
    for p in patterns:
        match = re.search(p, text)
        if match:
            return float(match.group(1)), float(match.group(2))

    
    # 2. Check for shortened maps.app.goo.gl URL
    if "maps.app.goo.gl" in text or "goo.gl/maps" in text:
        url_match = re.search(r"(https?://[^\s,]+)", text)
        if url_match:
            try:
                # Follow redirect
                response = requests.head(url_match.group(1), allow_redirects=True, timeout=5)
                # Check resolved URL
                return extract_coords_from_url(response.url)
            except:
                pass
                
    return None

def geocode_location(query):
    """
    Geocodes a municipality/location name using Open-Meteo Geocoding API.
    Returns: { 'name': str, 'lat': float, 'lon': float, 'admin1': str } or None
    """
    # Clean query: "Bebedouro - SP" -> "Bebedouro"
    # We still keep the original to try if cleaning fails
    clean_query = query.split('-')[0].split(',')[0].strip()
    
    def fetch(q):
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": q,
            "count": 10,
            "language": "pt",
            "format": "json"
        }
        # Add country code restriction if searching in Brazil
        params["countrycode"] = "BR"

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if "results" in data and len(data["results"]) > 0:
                results = data["results"]
                # Heuristic: 
                # 1. Exact name match in Brazil
                # 2. Any match in Brazil
                # 3. First result
                
                # Priority 1: Brazil match
                brazil_results = [r for r in results if r.get("country_code") == "BR" or r.get("country") == "Brasil"]
                if brazil_results:
                    return brazil_results[0]
                
                return results[0]
        except:
            pass
        return None

    # Try clean query first, then original
    res = fetch(clean_query)
    if not res and clean_query != query:
        res = fetch(query)
    
    # Final fallback for "Campo Grande MS" -> "Campo Grande"
    if not res and " " in clean_query:
        fallback_query = " ".join(clean_query.split()[:-1])
        if len(fallback_query) >= 3:
            res = fetch(fallback_query)
        
    if res:

        return {
            "name": res.get("name"),
            "lat": res.get("latitude"),
            "lon": res.get("longitude"),
            "admin1": res.get("admin1"),
            "country": res.get("country")
        }
    return None

def get_precipitation_data(lat, lon):
    """
    Fetches precipitation data using Open-Meteo Weather API.
    Returns: { 'last_24h': float, 'daily_history': list of (date, value) } or None
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation",
        "daily": "precipitation_sum",
        "timezone": "America/Sao_Paulo",
        "past_days": 7,
        "forecast_days": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if "hourly" not in data or "daily" not in data:
            return None
            
        hourly_precip = data["hourly"]["precipitation"]
        # Filter out None values and sum last 24 records
        last_24_records = hourly_precip[-24:]
        last_24h_sum = sum(v for v in last_24_records if v is not None)

        
        daily_dates = data["daily"]["time"]
        daily_sums = data["daily"]["precipitation_sum"]
        
        # We want the last 7 completed days + today, latest first
        daily_history = list(zip(daily_dates, daily_sums))
        daily_history.reverse()
        
        return {
            "last_24h": last_24h_sum,
            "daily_history": daily_history
        }
    except Exception as e:
        print(f"Weather data error: {e}")
        return None

def get_static_map_url(lat, lon):
    """
    Generates a Yandex Static Map URL (Hybrid style: Satellite + Streets).
    """
    return f"https://static-maps.yandex.ru/1.x/?ll={lon},{lat}&z=13&l=sat,skl&pt={lon},{lat},pm2rdm&size=600,400"

def generate_weather_map_with_title(lat, lon, title=None):
    """
    Downloads static map and adds a title using Matplotlib.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from io import BytesIO
    
    map_url = get_static_map_url(lat, lon)
    try:
        resp = requests.get(map_url, timeout=15)
        if resp.status_code != 200:
            return None
        img = plt.imread(BytesIO(resp.content), format='png')
        
        fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
        ax.imshow(img)
        
        if title:
            ax.set_title(title, fontsize=14, fontweight='bold', pad=10)
            
        ax.axis('off')
        
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1)
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print(f"Error generating weather map with title: {e}")
        return None

