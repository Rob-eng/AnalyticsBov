import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from scipy.interpolate import make_interp_spline
import os
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

def generate_chart(data):
    if not data or len(data) == 0:
        return None
        
    # Convert to DataFrame and prepare data
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    
    # Pivot the data
    df_pivot = df.pivot(index='date', columns='country', values='price')
    df_pivot = df_pivot.sort_index()
    
    # Colors matching the Google Sheet exactly (PRESERVED as requested)
    country_colors = {
        'Brasil': '#2ca02c',       # Green
        'Argentina': '#00ffff',    # Cyan
        'Uruguai': '#ff7f0e',      # Orange
        'Paraguai': '#d62728',     # Red
        'Australia': '#000000',    # Black (In dark mode, maybe change to light grey if needed, but keeping as requested)
        'Austrália': '#000000',    # Black
        'Irlanda': '#9467bd',      # Purple
        'Estados Unidos': '#ffff00', # Yellow
        'China': '#fa8072'         # Salmon
    }
    
    # Brand Colors from Logo
    BG_COLOR = '#0B0D0F'
    TEXT_COLOR = '#FFFFFF'
    CYAN_BRAND = '#00B4FF'
    GREEN_BRAND = '#2ECC71'
    GRID_COLOR = '#1A1D21'
    
    # Adjust specific colors for dark mode visibility if they are too dark
    for c, col in country_colors.items():
        if col == '#000000':
            country_colors[c] = '#E0E0E0' # Light grey instead of black for visibility
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    
    # --- WATERMARK ---
    logo_path = 'app/assets/logo.jpg'
    if os.path.exists(logo_path):
        try:
            logo_img = plt.imread(logo_path)
            # Create a large, semi-transparent watermark in the background
            # We use fig.figimage or add an axis
            newax = fig.add_axes([0.25, 0.2, 0.5, 0.5], zorder=0)
            newax.imshow(logo_img, alpha=0.15)
            newax.axis('off')
        except Exception as e:
            print(f"Error adding watermark: {e}")
    
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
                         linewidth=2.8, # Thicker lines for dark mode POP
                         color=color,
                         alpha=0.95,
                         zorder=5)
            except:
                line, = ax.plot(series.index, series.values, 
                         linewidth=2.8, 
                         color=color,
                         alpha=0.95,
                         zorder=5)
        else:
            line, = ax.plot(series.index, series.values, 
                     linewidth=2.8, 
                     color=color,
                     alpha=0.95,
                     zorder=5)
            
        if not series.empty:
            legend_info.append({
                'country': country, 
                'color': color, 
                'last_price': series.iloc[-1]
            })
    
    # Sort legend_info by last_price (descending)
    legend_info = sorted(legend_info, key=lambda x: x['last_price'], reverse=True)
    
    # --- STYLING ---
    
    # Centered Title with Logo Colors
    plt.title('PREÇO DA @ EM DÓLAR', fontsize=26, fontweight='bold', 
              color=CYAN_BRAND, loc='center', pad=50, family='sans-serif')
    
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    
    # Ax Spines
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    
    # X-Axis formatting
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_minor_formatter(plt.NullFormatter())
    
    # Tick Styles: Major (Years) are larger
    ax.tick_params(axis='x', which='major', length=12, width=2, color=CYAN_BRAND, labelsize=12, labelcolor=TEXT_COLOR)
    ax.tick_params(axis='x', which='minor', length=6, width=1, color='#444444')
    
    # Y-Axis Ticks
    max_val = df['price'].max()
    plt.yticks(np.arange(0, max_val + 20, 10), fontsize=12, color=TEXT_COLOR)
    ax.tick_params(axis='y', colors='#666666')
    ax.set_ylim(0, max_val + 10)
    
    # Grid: Horizontal lines ONLY
    ax.yaxis.grid(True, linestyle='-', color=GRID_COLOR, alpha=0.5, zorder=1)
    ax.xaxis.grid(False)
    
    plt.xticks(rotation=0, ha='center')
    
    # --- CUSTOM LEGEND WITH FLAGS ---
    flags_dir = 'app/assets/flags'
    start_y = 0.88 
    step_y = 0.08  
    
    for i, info in enumerate(legend_info):
        country = info['country']
        color = info['color']
        y_pos = start_y - (i * step_y)
        
        # 1. Color Bar
        ax.plot([-0.18, -0.15], [y_pos, y_pos], transform=ax.transAxes, 
                color=color, linewidth=5, clip_on=False, zorder=10)
        
        # 2. Flag with Border
        flag_path = os.path.join(flags_dir, f"{country}.png")
        if os.path.exists(flag_path):
            try:
                border_circle = plt.Circle((-0.11, y_pos), 0.024, transform=ax.transAxes, 
                                          color=color, zorder=11, clip_on=False)
                ax.add_patch(border_circle)
                
                flag_img = plt.imread(flag_path)
                imagebox = OffsetImage(flag_img, zoom=0.14)
                ab = AnnotationBbox(imagebox, (-0.11, y_pos), 
                                    xycoords='axes fraction',
                                    frameon=False,
                                    box_alignment=(0.5, 0.5),
                                    zorder=12)
                ax.add_artist(ab)
            except:
                ax.text(-0.11, y_pos, country, transform=ax.transAxes, 
                        fontsize=11, color=TEXT_COLOR, verticalalignment='center')
        else:
            ax.text(-0.11, y_pos, country, transform=ax.transAxes, 
                    fontsize=11, color=TEXT_COLOR, verticalalignment='center')
    
    plt.subplots_adjust(left=0.22, right=0.93, top=0.82, bottom=0.15)
    
    output_path = '/tmp/chart.png'
    plt.savefig(output_path, dpi=140, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    
    return output_path
