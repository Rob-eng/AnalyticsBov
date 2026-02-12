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
    
    # Normalize country names to prevent duplicates (e.g., Australia vs Austrália)
    df['country'] = df['country'].replace({'Australia': 'Austrália'})
    
    # Group by date and country to avoid duplicates before pivoting
    df = df.groupby(['date', 'country'])['price'].mean().reset_index()
    
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
    
    # Brand / Theme Colors - NAVY THEME
    BG_COLOR = '#001F3F' # Classic Navy Blue or #0a0e1c for more modern
    TEXT_COLOR = '#FFFFFF'
    CYAN_BRAND = '#00B4FF'
    GRID_COLOR = '#112D4E'
    
    # Adjust specific colors for dark mode visibility
    for c, col in country_colors.items():
        if col == '#000000':
            country_colors[c] = '#E0E0E0' # Light grey instead of black
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    
    # --- WATERMARK ---
    logo_path = 'app/assets/logo.jpg'
    if os.path.exists(logo_path):
        try:
            logo_img = plt.imread(logo_path)
            newax = fig.add_axes([0.25, 0.2, 0.5, 0.5], zorder=0)
            newax.imshow(logo_img, alpha=0.12) # More visible on dark
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
                         linewidth=2.8, # Thicker for dark background
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
    
    # Sorting and Legend info gathering
    for country in df_pivot.columns:
        series = df_pivot[country].dropna()
        if not series.empty:
            legend_info.append({
                'country': country, 
                'color': country_colors.get(country, '#7f7f7f'), 
                'last_price': series.iloc[-1]
            })
    
    legend_info = sorted(legend_info, key=lambda x: x['last_price'], reverse=True)
    
    # --- STYLING ---
    
    plt.title('🐂 Preço da @ em Dólar 📊', fontsize=26, fontweight='bold', 
              color='#FFFFFF', loc='center', pad=50) # TITLE TO WHITE
    
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_color('#112D4E')
    ax.spines['bottom'].set_color('#112D4E')
    
    # X-Axis: Years as major ticks
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    
    # Tick Styles - ALL TO WHITE
    ax.tick_params(axis='x', which='major', length=10, width=1.5, color='#FFFFFF', labelsize=11, labelcolor='#FFFFFF')
    ax.tick_params(axis='x', which='minor', length=4, width=0.8, color='#444444')
    
    # Y-Axis Ticks: Every 10 units - ALL TO WHITE
    max_val = df['price'].max()
    plt.yticks(np.arange(0, max_val + 20, 10), fontsize=11, color='#FFFFFF')
    ax.tick_params(axis='y', colors='#FFFFFF')
    ax.set_ylim(0, max_val + 10)
    
    # Grid: Subtle horizontal at 10 units, sutil dotted at each year
    ax.yaxis.grid(True, linestyle='-', color='#0a192f', alpha=0.5, zorder=1)
    ax.xaxis.grid(True, which='major', linestyle=':', color='#0a192f', alpha=0.5, zorder=1)
    ax.xaxis.grid(False, which='minor') # Don't grid quarters
    
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
        # Normalize country name for filename (remove accents for file safety)
        filename = country.replace('á', 'a').replace('ã', 'a').replace('é', 'e').replace('ú', 'u')
        flag_path = os.path.join(flags_dir, f"{filename}.png")
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

def generate_future_table(data_dict):
    """
    Generates a beautiful Matplotlib table image from the scraped future market data.
    """
    if not data_dict or not data_dict.get('rows'):
        return None
        
    BG_COLOR = '#001F3F'
    TEXT_COLOR = '#FFFFFF'
    HEADER_COLOR = '#00B4FF' # Cyan brand
    BORDER_COLOR = '#112D4E'
    
    rows = data_dict['rows']
    headers = data_dict['headers']
    date_info = data_dict.get('date_raw', '')
    
    # Create figure
    # Adjust height based on number of rows
    fig_height = 1.5 + (len(rows) * 0.6)
    fig, ax = plt.subplots(figsize=(12, fig_height), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis('off')
    
    # Title
    plt.title(f'🔮 Mercado Futuro do Boi Gordo 🐂\n{date_info}', 
              fontsize=20, fontweight='bold', color=TEXT_COLOR, pad=20)
    
    # Create Table
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc='center',
        loc='center',
        cellColours=[[BG_COLOR]*len(headers)]*len(rows),
        colColours=[HEADER_COLOR]*len(headers)
    )
    
    # Styling Table
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1.2, 2.5) # Scale width and height
    
    # Iterate through cells to style them
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor(BORDER_COLOR)
        if row == 0: # Header
            cell.set_text_props(weight='bold', color=BG_COLOR) # Black on cyan
        else:
            cell.set_text_props(color=TEXT_COLOR)
            # Alternate row coloring for readability
            if row % 2 == 0:
                cell.set_facecolor('#002b55')
            
    # Watermark (Smaller logo)
    logo_path = 'app/assets/logo.jpg'
    if os.path.exists(logo_path):
        try:
            logo_img = plt.imread(logo_path)
            # Add small logo at the bottom right
            logo_ax = fig.add_axes([0.8, 0.02, 0.15, 0.15], zorder=10)
            logo_ax.imshow(logo_img, alpha=0.15)
            logo_ax.axis('off')
        except:
            pass
            
    # Source Footnote
    plt.figtext(0.5, 0.05, "Fonte: Scot Consultoria", 
                ha='center', fontsize=10, color='#AAAAAA', style='italic')

    output_path = '/tmp/future_table.png'
    plt.savefig(output_path, dpi=140, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    
    return output_path
