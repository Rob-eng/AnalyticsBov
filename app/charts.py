import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import os

def generate_chart(data):
    if not data:
        return None
        
    df = pd.DataFrame(data)
    
    # Ensure date is datetime
    df['date'] = pd.to_datetime(df['date'])
    
    # Sort by date
    df = df.sort_values('date')
    
    plt.figure(figsize=(10, 6))
    
    # Plot each country
    # Define colors based on user's spreadsheet reference
    country_colors = {
        'Brasil': '#2ca02c',       # Green
        'Argentina': '#00ffff',    # Cyan
        'Uruguai': '#ff7f0e',      # Orange
        'Paraguai': '#d62728',     # Red
        'Australia': '#000000',    # Black
        'Austrália': '#000000',    # Black (Normalization)
        'Irlanda': '#9467bd',      # Purple
        'Estados Unidos': '#ffff00', # Yellow
        'China': '#fa8072'         # Salmon
    }
    
    # Use fallback color cycle for others
    default_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    
    for i, country in enumerate(countries):
        country_data = df[df['country'] == country]
        
        # Determine color
        color = country_colors.get(country, default_colors[i % len(default_colors)])
        
        # Plot line (smooth style, no markers, thicker lines)
        plt.plot(country_data['date'], country_data['price'], 
                 label=country, 
                 linewidth=2.5, 
                 color=color,
                 alpha=0.9)
    
    plt.title('Preço da @ em Dólar', fontsize=18, loc='left', pad=20, color='#555555')
    
    # Y-Axis formatting
    plt.grid(axis='y', linestyle='-', alpha=0.5, color='#e0e0e0')
    
    # X-Axis formatting
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45, fontsize=10)
    plt.yticks(fontsize=10)
    
    # Remove top, right AND left spines (keep tick labels but remove box border)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['left'].set_visible(True) # Keep Y axis line if preferred, or False
    
    # Move legend to the LEFT to match spreadsheet
    # Spreadsheet has legend listed vertically on the side or inside top-left.
    # Looking at the image, it's on the left, outside the chart area? 
    # Actually, the user's reference image 1 has legend on the LEFT side of the canvas.
    plt.legend(bbox_to_anchor=(-0.05, 1), loc='upper right', borderaxespad=0., frameon=False, fontsize=11)
    
    # Adjust layout to make room for legend on the left if necessary, 
    # but standard bbox_to_anchor with 'upper right' relative to a negative x puts it on the left.
    # Alternatively, use layout='constrained' or tight_layout with rect
    
    plt.tight_layout()
    
    output_path = '/tmp/chart.png'
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close()
    
    return output_path
