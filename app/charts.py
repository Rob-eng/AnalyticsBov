import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from scipy.interpolate import make_interp_spline
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from scipy.interpolate import make_interp_spline
import os

from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import os

def generate_chart(data):
    if not data or len(data) == 0:
        return None
        
    # Convert to DataFrame and prepare data
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    
    # Pivot the data
    df_pivot = df.pivot(index='date', columns='country', values='price')
    df_pivot = df_pivot.sort_index()
    
    # Colors matching the Google Sheet exactly
    country_colors = {
        'Brasil': '#2ca02c',       # Green
        'Argentina': '#00ffff',    # Cyan
        'Uruguai': '#ff7f0e',      # Orange
        'Paraguai': '#d62728',     # Red
        'Australia': '#000000',    # Black
        'Austrália': '#000000',    # Black
        'Irlanda': '#9467bd',      # Purple
        'Estados Unidos': '#ffff00', # Yellow
        'China': '#fa8072'         # Salmon
    }
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='white')
    ax.set_facecolor('white')
    
    # Store line colors and country names for the legend
    legend_info = []
    
    # Iterate through countries
    for country in df_pivot.columns:
        series = df_pivot[country].dropna()
        if len(series) < 2:
            continue
            
        color = country_colors.get(country, '#7f7f7f')
        
        # Prepare for smoothing
        x = mdates.date2num(series.index)
        y = series.values
        
        line = None
        if len(x) > 3:
            x_new = np.linspace(x.min(), x.max(), 500)
            try:
                spl = make_interp_spline(x, y, k=3)
                y_smooth = spl(x_new)
                line, = ax.plot(mdates.num2date(x_new), y_smooth, 
                         linewidth=2.2, 
                         color=color,
                         alpha=0.9)
            except:
                line, = ax.plot(series.index, series.values, 
                         linewidth=2.2, 
                         color=color,
                         alpha=0.9)
        else:
            line, = ax.plot(series.index, series.values, 
                     linewidth=2.2, 
                     color=color,
                     alpha=0.9)
            
        if not series.empty:
            legend_info.append({
                'country': country, 
                'color': color, 
                'last_price': series.iloc[-1]
            })
    
    # Sort legend_info by last_price (descending)
    legend_info = sorted(legend_info, key=lambda x: x['last_price'], reverse=True)
    
    # --- STYLING ---
    
    plt.title('Preço da @ em Dólar', fontsize=20, color='#666666', loc='left', pad=40)
    
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_color('#dddddd')
    ax.spines['bottom'].set_color('#dddddd')
    
    ax.yaxis.grid(True, linestyle='-', color='#e5e5e5', alpha=0.8)
    ax.xaxis.grid(False)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%y'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=14))
    plt.xticks(rotation=45, ha='right', fontsize=10, color='#444444')
    
    max_val = df['price'].max()
    plt.yticks(np.arange(0, max_val + 20, 10), fontsize=11, color='#444444')
    ax.set_ylim(0, max_val + 10)
    
    # --- CUSTOM LEGEND WITH FLAGS ---
    # We'll place the flags vertically on the left side
    
    flags_dir = 'app/assets/flags'
    start_y = 0.85 # Vertical position starting from top
    step_y = 0.08  # Distance between legends
    
    for i, info in enumerate(legend_info):
        country = info['country']
        color = info['color']
        
        y_pos = start_y - (i * step_y)
        
        # 1. Draw the color bar (marker)
        ax.plot([-0.18, -0.15], [y_pos, y_pos], transform=ax.transAxes, 
                color=color, linewidth=4, clip_on=False)
        
        # 2. Add the flag icon with a colored border
        flag_path = os.path.join(flags_dir, f"{country}.png")
        if os.path.exists(flag_path):
            try:
                # Add a circular background/border with the country's color
                border_circle = plt.Circle((-0.11, y_pos), 0.022, transform=ax.transAxes, 
                                          color=color, zorder=3, clip_on=False)
                ax.add_patch(border_circle)
                
                flag_img = plt.imread(flag_path)
                imagebox = OffsetImage(flag_img, zoom=0.13) # Slightly smaller zoom to show border
                ab = AnnotationBbox(imagebox, (-0.11, y_pos), 
                                    xycoords='axes fraction',
                                    frameon=False,
                                    box_alignment=(0.5, 0.5),
                                    zorder=4)
                ax.add_artist(ab)
            except Exception as e:
                # Fallback to text if image fails
                ax.text(-0.11, y_pos, country, transform=ax.transAxes, 
                        fontsize=11, color='#333333', verticalalignment='center')
        else:
            # Fallback to text if flag missing
            ax.text(-0.11, y_pos, country, transform=ax.transAxes, 
                    fontsize=11, color='#333333', verticalalignment='center')
    
    # Adjust margins to leave space for legend on the left
    plt.subplots_adjust(left=0.22, right=0.93, top=0.85, bottom=0.15)
    
    output_path = '/tmp/chart.png'
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close()
    
    return output_path
