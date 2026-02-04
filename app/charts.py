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
    countries = df['country'].unique()
    
    # Define a set of colors similar to the user's example if possible, or use default tab10
    # The example has explicit colors but default cycle is fine for now
    
    for country in countries:
        country_data = df[df['country'] == country]
        # Plot line
        # Plot line with markers to ensure visibility even with few data points
        plt.plot(country_data['date'], country_data['price'], label=country, linewidth=2, marker='o', markersize=4)
        
        # Add label at the end of the line (optional, but requested style has usage of space)
        # For now, standard legend is safer because lines might overlap
    
    plt.title('Preço da @ em Dólar', fontsize=16, loc='left', pad=20)
    
    # Y-Axis formatting
    plt.grid(axis='y', linestyle='-', alpha=0.3)
    
    # X-Axis formatting
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45)
    
    # Remove top and right spines
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    
    # Legend outside or best fit
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0., frameon=False)
    
    plt.tight_layout()
    
    output_path = '/tmp/chart.png'
    plt.savefig(output_path, dpi=100, bbox_inches='tight')
    plt.close()
    
    return output_path
