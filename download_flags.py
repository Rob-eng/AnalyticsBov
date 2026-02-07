import requests
import os
from PIL import Image, ImageDraw, ImageOps

def download_and_process_flags():
    countries = {
        'Brasil': 'br',
        'Argentina': 'ar',
        'Uruguai': 'uy',
        'Paraguai': 'py',
        'Australia': 'au',
        'Irlanda': 'ie',
        'Estados Unidos': 'us',
        'China': 'cn'
    }
    
    base_dir = 'app/assets/flags'
    os.makedirs(base_dir, exist_ok=True)
    
    print("Downloading and processing flags...")
    
    for name, code in countries.items():
        # Using FlagCDN for standard flags
        url = f"https://flagcdn.com/w160/{code}.png"
        target_path = os.path.join(base_dir, f"{name}.png")
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Save temporary
                temp_path = target_path + ".tmp"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                
                # Make it circular with Pillow
                img = Image.open(temp_path).convert("RGBA")
                size = (128, 128)
                img = ImageOps.fit(img, size, centering=(0.5, 0.5))
                
                mask = Image.new('L', size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0) + size, fill=255)
                
                output = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
                output.putalpha(mask)
                
                output.save(target_path)
                os.remove(temp_path)
                print(f"✅ Flag for {name} processed.")
            else:
                print(f"❌ Failed to download {name} flag ({response.status_code})")
        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

if __name__ == "__main__":
    download_and_process_flags()
