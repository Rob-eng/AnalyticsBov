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
    Inclui grade, norte, escala, quadro de áreas detalhado, legenda e mapa de localização.
    """
    import os
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import OffsetImage, AnnotationBbox
    from io import BytesIO
    import numpy as np
    from datetime import datetime
    
    # 1. Configuração da Figura (A4 vertical proportions)
    fig, ax = plt.subplots(figsize=(10, 13), facecolor='white')
    ax.set_facecolor('#fdfdfd')
    
    # Cores Oficiais SICAR
    COLORS = {
        'imovel': {'edgecolor': '#404040', 'facecolor': 'none', 'linewidth': 3, 'linestyle': '--', 'label': 'Perímetro do Imóvel'},
        'reserva': {'edgecolor': '#1b5e20', 'facecolor': '#4caf50', 'alpha': 0.5, 'label': 'Reserva Legal (RL)'},
        'app': {'edgecolor': '#01579b', 'facecolor': '#03a9f4', 'alpha': 0.6, 'label': 'A.P.P.'},
        'vegetacao': {'edgecolor': '#33691e', 'facecolor': '#689f38', 'alpha': 0.4, 'label': 'Veg. Nativa Remanescente'},
        'agua': {'edgecolor': '#0d47a1', 'color': '#03a9f4', 'linewidth': 1.5, 'label': 'Recursos Hídricos'},
        'consolidada': {'edgecolor': '#e65100', 'facecolor': '#ffb74d', 'alpha': 0.4, 'label': 'Área Consolidada'}
    }
    
    main_gdf = gdfs.get('imovel')
    if main_gdf is None or main_gdf.empty:
        return None
        
    # 2. Cálculos de Áreas (Hectares)
    areas_ha = {}
    try:
        # Usar projeção UTM estimada para cálculo de área preciso
        utm_crs = main_gdf.estimate_utm_crs()
        for key, gdf in gdfs.items():
            if not gdf.empty:
                areas_ha[key] = gdf.to_crs(utm_crs).area.sum() / 10000
    except Exception as ae:
        print(f"Erro no cálculo de áreas: {ae}")
        for key in gdfs: areas_ha[key] = 0

    # 3. Plotagem das camadas
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
                print(f"Erro ao plotar {layer}: {e}")

    # 3.1 AJUSTE CRÍTICO: Zoom focado no imóvel para evitar distorções por pontos errôneos
    bounds = main_gdf.total_bounds # [minx, miny, maxx, maxy]
    padx = max((bounds[2] - bounds[0]) * 0.15, 0.001)
    pady = max((bounds[3] - bounds[1]) * 0.15, 0.001)
    ax.set_xlim(bounds[0] - padx, bounds[2] + padx)
    ax.set_ylim(bounds[1] - pady, bounds[3] + pady)
    ax.set_aspect('equal', adjustable='box')

    # 4. Estética Cartográfica (Removendo emojis para evitar 'quadradinhos' em algumas fontes)
    ax.set_title("RELATORIO AMBIENTAL GEOESTATISTICO", fontsize=18, fontweight='bold', color='#1a1a1a', pad=25)
    ax.grid(True, linestyle=':', color='gray', alpha=0.4, zorder=0)
    ax.set_xlabel('Longitude (decimal)', fontsize=10, color='gray')
    ax.set_ylabel('Latitude (decimal)', fontsize=10, color='gray')
    
    # Norte
    x, y, arrow_length = 0.94, 0.93, 0.06
    ax.annotate('N', xy=(x, y), xytext=(x, y-arrow_length),
                arrowprops=dict(facecolor='black', width=3, headwidth=10),
                ha='center', va='center', fontsize=20, fontweight='bold', xycoords='axes fraction')
    
    # 5. Escala Gráfica (Manual)
    try:
        center = main_gdf.geometry.centroid.iloc[0]
        # Distância aproximada de 1 grau na latitude central
        m_per_deg_lon = 111320 * np.cos(np.radians(center.y))
        total_ha = areas_ha.get('imovel', 0)
        
        if total_ha > 2000: s_m, s_lab = 2000, "2 km"
        elif total_ha > 500: s_m, s_lab = 1000, "1 km"
        elif total_ha > 100: s_m, s_lab = 500, "500 m"
        else: s_m, s_lab = 200, "200 m"
        
        s_deg = s_m / m_per_deg_lon
        ax_xmin, ax_xmax = ax.get_xlim()
        ax_ymin, ax_ymax = ax.get_ylim()
        
        # Posição: inferior esquerda focado no mapa
        bar_x = ax_xmin + (ax_xmax - ax_xmin) * 0.05
        bar_y = ax_ymin + (ax_ymax - ax_ymin) * 0.05
        ax.plot([bar_x, bar_x + s_deg], [bar_y, bar_y], color='black', lw=4, zorder=20)
        ax.text(bar_x + s_deg/2, bar_y + (ax_ymax-ax_ymin)*0.015, s_lab, ha='center', fontsize=10, fontweight='bold')
    except: pass

    # 6. Mapa de Localização (Inset)
    try:
        from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        ax_inset = inset_axes(ax, width="25%", height="20%", loc='upper right', borderpad=2)
        ax_inset.set_facecolor('#fefefe')
        # Zoom out do imóvel
        main_gdf.plot(ax=ax_inset, color='red', zorder=5)
        # Buffer de 15x o tamanho para dar contexto regional
        buffer_val = max(bounds[2]-bounds[0], bounds[3]-bounds[1]) * 15
        ax_inset.set_xlim(bounds[0]-buffer_val, bounds[2]+buffer_val)
        ax_inset.set_ylim(bounds[1]-buffer_val, bounds[3]+buffer_val)
        ax_inset.set_xticks([]); ax_inset.set_yticks([])
        st_code = str(main_gdf.iloc[0].get('COD_IMOVEL') or 'CAR')[:2]
        ax_inset.set_title(f"Regiao ({st_code})", fontsize=9, fontweight='bold')
    except: pass

    # 7. Logo e Quadro de Informações
    prop_name = str(main_gdf.iloc[0].get('NOM_IMOVEL') or main_gdf.iloc[0].get('NOME_IMOVE') or "Propriedade Privada")[:35]
    cod_car = str(main_gdf.iloc[0].get('COD_IMOVEL') or "Nao identificado")
    
    info_text = (
        f"Propriedade: {prop_name}\n"
        f"Codigo CAR:   {cod_car}\n"
        f"Emissao:      {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"Sistema:      WGS 84 / SIRGAS 2000"
    )
    plt.text(0.98, 0.02, info_text, transform=ax.transAxes, fontsize=10, ha='right', va='bottom', fontfamily='monospace',
             zorder=25, bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', alpha=0.9, edgecolor='#ced4da'))

    # 8. Quadro de Áreas (Tabela Lateral)
    areas_text = "QUADRO DE AREAS (ha)\n" + "=" * 22 + "\n"
    areas_text += f"Total Imovel:  {areas_ha.get('imovel', 0):>8.2f}\n"
    if 'reserva' in areas_ha:    areas_text += f"Reserva Legal:  {areas_ha.get('reserva', 0):>8.2f}\n"
    if 'app' in areas_ha:        areas_text += f"A.P.P.:         {areas_ha.get('app', 0):>8.2f}\n"
    if 'vegetacao' in areas_ha:  areas_text += f"Remanescente:   {areas_ha.get('vegetacao', 0):>8.2f}\n"
    if 'consolidada' in areas_ha: areas_text += f"Consolidada:    {areas_ha.get('consolidada', 0):>8.2f}\n"

    plt.text(0.02, 0.98, areas_text, transform=ax.transAxes, fontsize=11, ha='left', va='top', fontfamily='monospace',
             zorder=25, bbox=dict(boxstyle='round,pad=0.8', facecolor='#f1f3f5', alpha=0.9, edgecolor='#adb5bd'))

    # 9. Legenda
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=COLORS[l]['facecolor'], edgecolor=COLORS[l]['edgecolor'], alpha=COLORS[l].get('alpha', 1.0), label=COLORS[l]['label']) 
                       if 'facecolor' in COLORS[l] else Line2D([0], [0], color=COLORS[l]['edgecolor'], lw=2, label=COLORS[l]['label'])
                       for l in order if l in gdfs]
    ax.legend(handles=legend_elements, loc='lower right', bbox_to_anchor=(0.98, 0.12), fontsize=10, 
              frameon=True, facecolor='white', framealpha=1, shadow=True)

    # Finalização
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=200, bbox_inches='tight')
    plt.close()
    buf.seek(0)
    return buf.read()
