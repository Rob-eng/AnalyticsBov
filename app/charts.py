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
    
    # Brand / Theme Colors - WHITE THEME
    BG_COLOR = '#FFFFFF' 
    TEXT_COLOR = '#000000'
    GRID_COLOR = '#E0E0E0'
    
    # Adjust specific colors for dark mode visibility (removed since background is white now)
    
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
              color=TEXT_COLOR, loc='center', pad=50) # TITLE
    
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_color(GRID_COLOR)
    ax.spines['bottom'].set_color(GRID_COLOR)
    
    # X-Axis: Years as major ticks
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    
    # Tick Styles 
    ax.tick_params(axis='x', which='major', length=10, width=1.5, color=TEXT_COLOR, labelsize=11, labelcolor=TEXT_COLOR)
    ax.tick_params(axis='x', which='minor', length=4, width=0.8, color='#888888')
    
    # Y-Axis Ticks: Every 10 units 
    max_val = df['price'].max()
    plt.yticks(np.arange(0, max_val + 20, 10), fontsize=11, color=TEXT_COLOR)
    ax.tick_params(axis='y', colors=TEXT_COLOR)
    ax.set_ylim(0, max_val + 10)
    
    # Grid: Subtle horizontal at 10 units, sutil dotted at each year
    ax.yaxis.grid(True, linestyle='-', color=GRID_COLOR, alpha=0.9, zorder=1)
    ax.xaxis.grid(True, which='major', linestyle=':', color=GRID_COLOR, alpha=0.9, zorder=1)
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
        
    BG_COLOR = '#FFFFFF'
    TEXT_COLOR = '#000000'
    HEADER_COLOR = '#00B4FF'
    BORDER_COLOR = '#E0E0E0'
    
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
    
    # Find index of the variation column
    var_col_idx = -1
    for i, h in enumerate(headers):
        if 'VAR' in h.upper():
            var_col_idx = i
            break

    # Iterate through cells to style them
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor(BORDER_COLOR)
        if row == 0: # Header
            cell.set_text_props(weight='bold', color=BG_COLOR) # Black on cyan
        else:
            # Alternate row coloring for readability
            if row % 2 == 0:
                cell.set_facecolor('#F8F8F8')
            
            # Special handling for variation column
            if col == var_col_idx:
                text_val = cell.get_text().get_text()
                try:
                    # Clean and parse value
                    clean_val = text_val.replace(',', '.').replace('%', '').strip()
                    val = float(clean_val)
                    
                    if val > 0:
                        cell.get_text().set_color('#00FF00') # Vibrant Green
                        if '%' not in text_val:
                            cell.get_text().set_text(f"+{text_val}%")
                    elif val < 0:
                        cell.get_text().set_color('#FF4444') # Vibrant Red
                        if '%' not in text_val:
                            cell.get_text().set_text(f"{text_val}%")
                    else:
                        cell.get_text().set_color(TEXT_COLOR)
                        if '%' not in text_val:
                            cell.get_text().set_text(f"{text_val}%")
                except:
                    cell.get_text().set_color(TEXT_COLOR)
            else:
                cell.get_text().set_color(TEXT_COLOR)

            
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

def generate_precipitation_chart(daily_history, title="Histórico de Chuva (7 dias)"):
    if not daily_history:
        return None
        
    BG_COLOR = '#FFFFFF'
    TEXT_COLOR = '#000000'
    BAR_COLOR = '#00B4FF'
    GRID_COLOR = '#E0E0E0'
    
    # Sort history by date ascending for the chart
    sorted_history = sorted(daily_history, key=lambda x: x[0])
    
    dates = []
    values = []
    
    from datetime import datetime
    for date_str, val in sorted_history:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        dates.append(dt.strftime('%d/%m'))
        values.append(float(val))
        
    fig, ax = plt.subplots(figsize=(10, 6), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    
    # Title
    plt.title(f'🌧️ {title}', fontsize=20, fontweight='bold', color=TEXT_COLOR, pad=20)
    
    # Bars
    bars = ax.bar(dates, values, color=BAR_COLOR, alpha=0.9, width=0.6, edgecolor='white', linewidth=1, zorder=3)
    
    # Styling
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(GRID_COLOR)
    ax.spines['bottom'].set_color(GRID_COLOR)
    
    ax.tick_params(axis='x', colors=TEXT_COLOR, labelsize=12)
    ax.tick_params(axis='y', colors=TEXT_COLOR, labelsize=12)
    
    ax.yaxis.grid(True, linestyle='--', color=GRID_COLOR, alpha=0.9, zorder=0)
    ax.set_ylabel('Precipitação (mm)', color=TEXT_COLOR, fontsize=14, labelpad=15)
    
    # Values on top of bars
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax.annotate(f'{height:.1f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 5),  
                        textcoords="offset points",
                        ha='center', va='bottom', color=TEXT_COLOR, fontweight='bold')
    
    plt.tight_layout()
    output_path = '/tmp/precip_history.png'
    plt.savefig(output_path, dpi=120, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    
    return output_path
def generate_pro_car_map(gdfs):
    """
    Gera um mapa cartográfico profissional a partir dos GeoDataFrames extraídos do ZIP.
    Inclui grade, norte, escala (estimada), legenda e logo.
    """
    import os
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import OffsetImage, AnnotationBbox
    from io import BytesIO
    import numpy as np
    from datetime import datetime
    
    # 1. Configuração da Figura
    fig, ax = plt.subplots(figsize=(10, 12), facecolor='white')
    ax.set_facecolor('#fdfdfd')
    
    # Definição de Cores e Estilos SICAR
    COLORS = {
        'imovel': {'edgecolor': '#404040', 'facecolor': 'none', 'linewidth': 2.5, 'linestyle': '--', 'label': 'Perímetro do Imóvel'},
        'reserva': {'edgecolor': '#2e7d32', 'facecolor': '#4caf50', 'alpha': 0.5, 'label': 'Reserva Legal (RL)'},
        'app': {'edgecolor': '#0277bd', 'facecolor': '#03a9f4', 'alpha': 0.6, 'label': 'A.P.P.'},
        'vegetacao': {'edgecolor': '#1b5e20', 'facecolor': '#2e7d32', 'alpha': 0.3, 'label': 'Veg. Nativa Remanescente'},
        'agua': {'edgecolor': '#0d47l1', 'color': '#03a9f4', 'linewidth': 1.2, 'label': 'Recursos Hídricos'},
        'consolidada': {'edgecolor': '#ef6c00', 'facecolor': '#ffb74d', 'alpha': 0.3, 'label': 'Área Consolidada'}
    }
    
    main_gdf = gdfs.get('imovel')
    if main_gdf is None or main_gdf.empty:
        return None
        
    # 2. Plotagem das camadas na ordem correta
    order = ['consolidada', 'vegetacao', 'app', 'reserva', 'agua', 'imovel']
    for layer in order:
        if layer in gdfs:
            gdf = gdfs[layer]
            if gdf.empty: continue
            
            style = COLORS.get(layer, {})
            try:
                if layer in ['imovel', 'agua']:
                    gdf.plot(ax=ax, **style, zorder=10)
                else:
                    gdf.plot(ax=ax, **style, zorder=5)
            except Exception as e:
                print(f"Erro ao plotar camada {layer}: {e}")

    # 3. Estética Cartográfica
    ax.set_title("🗺️ RELATÓRIO AMBIENTAL GEOESTATÍSTICO", fontsize=18, fontweight='bold', color='#1a1a1a', pad=25)
    
    # Grade de Coordenadas
    ax.grid(True, linestyle=':', color='gray', alpha=0.4, zorder=0)
    ax.set_xlabel('Longitude (decimal)', fontsize=10, color='gray')
    ax.set_ylabel('Latitude (decimal)', fontsize=10, color='gray')
    
    # Rosa dos Ventos (Norte)
    x, y, arrow_length = 0.94, 0.94, 0.07
    ax.annotate('N', xy=(x, y), xytext=(x, y-arrow_length),
                arrowprops=dict(facecolor='black', width=3, headwidth=12),
                ha='center', va='center', fontsize=22, fontweight='bold', xycoords='axes fraction')
    
    # Logo Agro Analytics
    try:
        logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo.jpg")
        if os.path.exists(logo_path):
            from matplotlib.image import imread
            logo = imread(logo_path)
            ib = OffsetImage(logo, zoom=0.07)
            ab = AnnotationBbox(ib, (0.08, 0.93), xycoords='axes fraction', frameon=False)
            ax.add_artist(ab)
    except Exception as e:
        print(f"Erro ao carregar logo: {e}")

    # 4. Cálculos e Quadro de Informações
    try:
        # Estimar área em Hectares usando projeção UTM local
        utm_gdf = main_gdf.to_crs(main_gdf.estimate_utm_crs())
        total_area_ha = utm_gdf.area.sum() / 10000
    except:
        total_area_ha = 0
        
    prop_name = str(main_gdf.iloc[0].get('NOM_IMOVEL') or main_gdf.iloc[0].get('NOME_IMOVE') or "Fazenda Selecionada")
    cod_car = str(main_gdf.iloc[0].get('COD_IMOVEL') or "Não identificado")
    
    info_text = (
        f"📍 Propriedade: {prop_name}\n"
        f"🆔 Código CAR: {cod_car}\n"
        f"📏 Área Total: {total_area_ha:.2f} ha\n"
        f"📅 Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"🌐 Datum: WGS 84 (SIRGAS 2000)"
    )
    
    plt.text(0.98, 0.02, info_text, transform=ax.transAxes, 
             fontsize=10, ha='right', va='bottom', fontfamily='monospace',
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#f8f9fa', alpha=0.9, edgecolor='#ced4da'))

    # 5. Legenda Customizada
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    legend_elements = []
    for layer in order:
        if layer in gdfs:
            cfg = COLORS[layer]
            if 'facecolor' in cfg:
                legend_elements.append(Patch(facecolor=cfg['facecolor'], edgecolor=cfg['edgecolor'], alpha=cfg.get('alpha', 1.0), label=cfg['label']))
            else:
                legend_elements.append(Line2D([0], [0], color=cfg.get('edgecolor', 'black'), lw=cfg.get('linewidth', 1), linestyle=cfg.get('linestyle', '-'), label=cfg['label']))
    
    ax.legend(handles=legend_elements, loc='lower left', fontsize=9, frameon=True, facecolor='white', shadow=True)

    # Finalização
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=200, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return buf.read()
