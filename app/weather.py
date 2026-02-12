import requests
import re
from datetime import datetime, timedelta

def parse_coordinates(text):
    """
    Parses various coordinate formats.
    Supported:
    - -20.94, -48.48
    - 20.94S, 48.48W
    - 20° 56' S, 48° 29' W
    Returns: (lat, lon) or None
    """
    # Try decimal format first: -20.94, -48.48
    decimal_match = re.match(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$", text)
    if decimal_match:
        return float(decimal_match.group(1)), float(decimal_match.group(2))

    # Try format with N/S/E/W: 20.94S, 48.48W
    nsew_match = re.match(r"^\s*(\d+\.?\d*)\s*([NSns])\s*,\s*(\d+\.?\d*)\s*([EWewOo])\s*$", text)
    if nsew_match:
        lat = float(nsew_match.group(1))
        if nsew_match.group(2).upper() == 'S':
            lat = -lat
        lon = float(nsew_match.group(3))
        if nsew_match.group(4).upper() in ['W', 'O']:
            lon = -lon
        return lat, lon

    # Try DMS format roughly: 20° 56' S, 48° 29' W
    dms_match = re.match(r"(\d+)[°\s]+(\d+)?['\s]*([NSns])\s*,\s*(\d+)[°\s]+(\d+)?['\s]*([EWewOo])", text)
    if dms_match:
        lat_d = float(dms_match.group(1))
        lat_m = float(dms_match.group(2)) if dms_match.group(2) else 0
        lat = lat_d + (lat_m / 60.0)
        if dms_match.group(3).upper() == 'S':
            lat = -lat
            
        lon_d = float(dms_match.group(4))
        lon_m = float(dms_match.group(5)) if dms_match.group(5) else 0
        lon = lon_d + (lon_m / 60.0)
        if dms_match.group(6).upper() in ['W', 'O']:
            lon = -lon
        return lat, lon

    return None

def geocode_location(query):
    """
    Geocodes a municipality/location name using Open-Meteo Geocoding API.
    Returns: { 'name': str, 'lat': float, 'lon': float, 'admin1': str } or None
    """
    # Clean query: "Bebedouro - SP" -> "Bebedouro"
    clean_query = query.split('-')[0].split(',')[0].strip()
    
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": clean_query,
        "count": 5, # Get more to find best match if needed
        "language": "pt"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            # Try to find a match in Brazil if multiple results
            results = data["results"]
            res = results[0]
            for r in results:
                if r.get("country") == "Brasil":
                    res = r
                    break
            
            return {
                "name": res.get("name"),
                "lat": res.get("latitude"),
                "lon": res.get("longitude"),
                "admin1": res.get("admin1"), # State/Region
                "country": res.get("country")
            }

    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

def get_precipitation_data(lat, lon):
    """
    Fetches precipitation data using Open-Meteo Weather API.
    Returns: { 'last_24h': float, 'daily_7d': list of (date, value) } or None
    """
    # Endpoints
    # 1. Forecast for last 24h (current coverage)
    # 2. Archive/Forecast for history
    
    # We'll use the combined forecast endpoint which includes 2 days of past data
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
            
        # Last 24h: Sum of last 24 hourly records
        # Wait, 'past_days=7' means it includes the last 7 days + today.
        # Find the index for the last 24 hours.
        # The hourly data starts from 7 days ago.
        hourly_precip = data["hourly"]["precipitation"]
        # Last 24 values
        last_24h_sum = sum(hourly_precip[-24:])
        
        # Daily 7d: last 7 days (excluding today if needed, but we'll show last 7 including today's current sum)
        daily_dates = data["daily"]["time"]
        daily_sums = data["daily"]["precipitation_sum"]
        
        # Zip them and take the last 7
        daily_history = list(zip(daily_dates, daily_sums))[-8:] # 7 past + today
        
        return {
            "last_24h": last_24h_sum,
            "daily_history": daily_history
        }
    except Exception as e:
        print(f"Weather data error: {e}")
        return None

def get_static_map_url(lat, lon):
    """
    Generates a Yandex Static Map URL.
    """
    return f"https://static-maps.yandex.ru/1.x/?ll={lon},{lat}&z=11&l=map&pt={lon},{lat},pm2rdm&size=600,400"
