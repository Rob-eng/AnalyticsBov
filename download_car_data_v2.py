import requests
import json
import os
import time
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(LegacySSLAdapter, self).init_poolmanager(*args, **kwargs)

def download_car_data_paginated():
    base_url = "https://geoserver.car.gov.br/geoserver/sicar/ows"
    ufs = [
        "ms" 
    ]
    
    output_dir = os.path.dirname(os.path.abspath(__file__))
    chunk_size = 5000 
    
    # Configure Session with Legacy SSL
    session = requests.Session()
    try:
        session.mount('https://', LegacySSLAdapter())
    except Exception as e:
        print(f"Warning: Could not mount LegacySSLAdapter: {e}")

    for uf in ufs:
        filename = f"car_{uf}.geojson"
        filepath = os.path.join(output_dir, filename)
        
        # Remove old file to strictly avoid staleness
        if os.path.exists(filepath):
            os.remove(filepath)
            
        print(f"Downloading data for {uf.upper()}...")
        
        all_features = []
        start_index = 0
        
        while True:
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": f"sicar:sicar_imoveis_{uf}",
                "outputFormat": "application/json",
                "count": chunk_size,
                "startIndex": start_index
            }
            
            try:
                response = session.get(base_url, params=params, timeout=300)
                
                if response.status_code == 200:
                    data = response.json()
                    features = data.get('features', [])
                    
                    if not features:
                        break
                        
                    all_features.extend(features)
                    print(f"  Fetched {len(all_features)} features...")
                    
                    if len(features) < chunk_size:
                        break # Last page
                        
                    start_index += chunk_size
                    time.sleep(0.5) # Throttle 
                else:
                    print(f"  Failed page at {start_index} for {uf.upper()}: {response.status_code}")
                    break
                    
            except Exception as e:
                print(f"  Error at index {start_index} for {uf.upper()}: {e}")
                break
        
        if all_features:
            geojson_data = {
                "type": "FeatureCollection",
                "features": all_features
            }
            
            with open(filepath, 'w') as f:
                json.dump(geojson_data, f)
            
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  Completed {uf.upper()}: {len(all_features)} features, {size_mb:.2f} MB")
        else:
            print(f"  No features found for {uf.upper()}")

if __name__ == "__main__":
    download_car_data_paginated()
