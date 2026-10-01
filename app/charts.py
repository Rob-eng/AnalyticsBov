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
    
    plt.title('Preço da @ em Dólar', fontsize=26, fontweight='bold', 
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
    plt.title(f'Mercado Futuro do Boi Gordo\n{date_info}', 
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
                    
                    # Variação é em R$/@ (ajuste atual − anterior), não em %
                    if val > 0:
                        cell.get_text().set_color('#1a9641')
                        if not text_val.startswith('+'):
                            cell.get_text().set_text(f"+{text_val}")
                    elif val < 0:
                        cell.get_text().set_color('#d7191c')
                    else:
                        cell.get_text().set_color(TEXT_COLOR)
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
    plt.figtext(0.5, 0.05, f"Fonte: {data_dict.get('source') or 'Scot Consultoria'}", 
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
    plt.title(f'{title}', fontsize=20, fontweight='bold', color=TEXT_COLOR, pad=20)
    
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
    import time
    timestamp = int(time.time() * 1000)
    output_path = f'/tmp/precip_history_{timestamp}.png'
    plt.savefig(output_path, dpi=120, facecolor=BG_COLOR, bbox_inches='tight')
    plt.close()
    
    return output_path
LAST_LAYOUT_ISSUES = []  # preenchido por generate_pro_car_map (QA de layout)


def check_map_layout(fig, map_ax, panel_artists):
    """
    Controle de qualidade do layout: elementos do painel não podem se sobrepor,
    invadir o mapa nem sair da figura. Devolve lista de problemas (vazia = OK).
    panel_artists: {nome: artista (Text, Legend, Axes...)}.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_box = fig.bbox
    map_box = map_ax.get_window_extent(renderer)
    boxes = {}
    for name, art in panel_artists.items():
        try:
            boxes[name] = art.get_window_extent(renderer)
        except Exception:
            continue
    issues = []
    # rótulos dos eixos do mapa não podem se atropelar (mapa muito estreito/baixo)
    for axis_name, labels in (("x", map_ax.get_xticklabels()), ("y", map_ax.get_yticklabels())):
        tick_boxes = [t.get_window_extent(renderer) for t in labels if t.get_visible() and t.get_text()]
        for a_box, b_box in zip(tick_boxes, tick_boxes[1:]):
            if a_box.overlaps(b_box):
                issues.append(f"rótulos do eixo {axis_name} sobrepostos")
                break
    names = list(boxes)
    for i, a in enumerate(names):
        b = boxes[a]
        if b.x0 < fig_box.x0 - 1 or b.y0 < fig_box.y0 - 1 or b.x1 > fig_box.x1 + 1 or b.y1 > fig_box.y1 + 1:
            issues.append(f"'{a}' sai da figura")
        if b.overlaps(map_box):
            issues.append(f"'{a}' sobrepõe o mapa")
        for c in names[i + 1:]:
            if b.overlaps(boxes[c]):
                issues.append(f"'{a}' sobrepõe '{c}'")
    return issues


def generate_pro_car_map(gdfs, background_img=None, bg_extent=None, reg_bg_img=None, reg_bg_extent=None):
    """
    Mapa cartográfico profissional do CAR (paisagem): mapa do imóvel à esquerda,
    SEM nada por cima; à direita, painel com mapa regional (perímetro em amarelo),
    quadro de áreas, legenda, escala + norte e dados do imóvel. Os blocos do painel
    são empilhados medindo o tamanho real de cada um, então nada se sobrepõe
    qualquer que seja o formato do imóvel. Ao final, check_map_layout() confere
    o resultado e grava os problemas em LAST_LAYOUT_ISSUES.
    """
    global LAST_LAYOUT_ISSUES
    import math
    import matplotlib.pyplot as plt
    from io import BytesIO
    import numpy as np
    from datetime import datetime
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch, Rectangle, FancyArrow

    fig = plt.figure(figsize=(16, 10), facecolor='white')
    gs = fig.add_gridspec(1, 2, width_ratios=[2.15, 1], wspace=0.04, left=0.06, right=0.98, top=0.90, bottom=0.08)
    ax = fig.add_subplot(gs[0, 0])
    panel = fig.add_subplot(gs[0, 1])
    panel.axis('off')

    # Cores Oficiais SICAR (Ajustadas para máximo contraste sobre fundo Branco)
    COLORS = {
        'imovel': {'edgecolor': '#000000', 'facecolor': 'none', 'linewidth': 3.0, 'linestyle': '--', 'label': 'Perímetro do imóvel'},
        'reserva': {'edgecolor': '#003300', 'facecolor': '#1b5e20', 'alpha': 0.7, 'hatch': '///', 'label': 'Reserva Legal (RL)'},
        'app': {'edgecolor': '#01579b', 'facecolor': '#03a9f4', 'alpha': 0.6, 'label': 'A.P.P.'},
        'vegetacao': {'edgecolor': '#2e7d32', 'facecolor': '#4caf50', 'alpha': 0.5, 'label': 'Remanescente nativo'},
        'agua': {'edgecolor': '#01579b', 'facecolor': '#4fc3f7', 'linewidth': 1.5, 'alpha': 1.0, 'label': 'Corpo d\'água'},
        'uso_restrito': {'edgecolor': '#f57f17', 'facecolor': '#fff59d', 'alpha': 0.8, 'hatch': '\\\\', 'label': 'Uso restrito'},
        'consolidada': {'edgecolor': '#4e342e', 'facecolor': '#ff3d00', 'alpha': 0.7, 'label': 'Área antropizada (consolidada)'},
        'sem_classificacao': {'edgecolor': '#9e9e9e', 'facecolor': '#eeeeee', 'alpha': 0.9, 'hatch': '...',
                              'linewidth': 0.3, 'label': 'Sem classificação no CAR'}
    }
    
    main_gdf = gdfs.get('imovel')
    if main_gdf is None or main_gdf.empty:
        return None

    # Merge de múltiplos polígonos do imóvel para não duplicar áreas/bordas
    main_gdf = main_gdf.dissolve()
    gdfs['imovel'] = main_gdf

    # Área do imóvel que o proprietário não declarou em nenhum tema do CAR:
    # sem isso ela aparecia como "buraco" branco e parecia camada faltante.
    gdfs.pop('sem_classificacao', None)
    try:
        themed = [g for k, g in gdfs.items() if k != 'imovel' and not g.empty]
        if themed:
            import geopandas as gpd
            from shapely.ops import unary_union
            covered = unary_union([g.to_crs(main_gdf.crs).geometry.buffer(0).unary_union for g in themed])
            rest = main_gdf.geometry.buffer(0).unary_union.difference(covered)
            if not rest.is_empty and rest.area > main_gdf.geometry.area.sum() * 0.005:
                gdfs['sem_classificacao'] = gpd.GeoDataFrame(geometry=[rest], crs=main_gdf.crs)
    except Exception as ue:
        print(f"Área sem classificação não calculada: {ue}")

    # Tenta obter nome e código de forma robusta
    row = main_gdf.iloc[0]
    # Campos comuns no SHP do SICAR: NOM_IMOVEL, NOME_IMOVE, NUM_CAR, COD_IMOVEL
    prop_name = str(row.get('NOM_IMOVEL') or row.get('NOME_IMOVE') or row.get('NOME') or "Propriedade Privada")[:35]
    cod_car = str(row.get('COD_IMOVEL') or row.get('NUM_CAR') or row.get('COD_IMOV') or "Nao identificado")
    
    # 1.1 Fundo do Mapa Principal (Sempre Branco como solicitado)
    ax.set_facecolor('white')
    # A imagem de satélite (background_img) será ignorada no mapa principal
    # e usada apenas no Mapa de Contexto (reg_bg_img).

    # 2. Cálculos de Áreas (Hectares)
    areas_ha = {}
    try:
        # Usar projeção UTM estimada para cálculo de área preciso
        utm_crs = main_gdf.estimate_utm_crs()
        for key, gdf in gdfs.items():
            if not gdf.empty:
                # dissolve() previne que feições sobrepostas multipliquem a área
                areas_ha[key] = gdf.dissolve().to_crs(utm_crs).area.sum() / 10000
    except Exception as ae:
        print(f"Erro no cálculo de áreas: {ae}")
        for key in gdfs: areas_ha[key] = 0

    # 3. Plotagem das camadas
    # Ordem base (extras primeiro para ficarem por baixo, imovel por ultimo)
    plot_order = ['sem_classificacao']
    plot_order += [l for l in gdfs.keys() if l not in ['imovel', 'agua', 'reserva', 'app', 'vegetacao', 'uso_restrito', 'consolidada', 'sem_classificacao']]
    plot_order += ['consolidada', 'uso_restrito', 'vegetacao', 'app', 'reserva', 'agua', 'imovel']
    
    for layer in plot_order:
        if layer in gdfs:
            gdf = gdfs[layer]
            if gdf.empty: continue
            # Tentar pegar estilo pré-definido ou usar cinza genérico
            style = COLORS.get(layer, {'edgecolor': '#9e9e9e', 'facecolor': '#eeeeee', 'alpha': 0.4})
            try:
                if layer in ['imovel', 'agua']:
                    gdf.plot(ax=ax, **{k: v for k, v in style.items() if k != 'label'}, zorder=10)
                else:
                    gdf.plot(ax=ax, **{k: v for k, v in style.items() if k != 'label'}, zorder=5)
            except Exception as e:
                print(f"Erro ao plotar {layer}: {e}")

    # 4. Enquadramento: só o imóvel, proporção real (1° lon = cos(lat) × 1° lat)
    bounds = main_gdf.total_bounds  # [minx, miny, maxx, maxy]
    padx = max((bounds[2] - bounds[0]) * 0.08, 0.001)
    pady = max((bounds[3] - bounds[1]) * 0.08, 0.001)
    ax.set_xlim(bounds[0] - padx, bounds[2] + padx)
    ax.set_ylim(bounds[1] - pady, bounds[3] + pady)
    ax.set_aspect(1 / math.cos(math.radians((bounds[1] + bounds[3]) / 2)), adjustable='box')
    ax.set_anchor('C')

    ax.grid(True, linestyle=':', color='gray', alpha=0.4, zorder=0)
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    def deg_min_fmt(v, pos):
        sign = "-" if v < 0 else ""
        v = abs(v)
        deg = int(v)
        mins = (v - deg) * 60
        return f"{sign}{deg}°{mins:04.1f}'".replace('.', ',')

    # Nº de marcações conforme o tamanho real do mapa na figura (mapa estreito → menos rótulos)
    fig.canvas.draw()
    _box = ax.get_window_extent(fig.canvas.get_renderer())
    ax.xaxis.set_major_locator(MaxNLocator(max(2, min(6, int(_box.width / fig.dpi / 1.1)))))
    ax.yaxis.set_major_locator(MaxNLocator(max(2, min(6, int(_box.height / fig.dpi / 1.1)))))
    ax.xaxis.set_major_formatter(FuncFormatter(deg_min_fmt))
    ax.yaxis.set_major_formatter(FuncFormatter(deg_min_fmt))
    ax.tick_params(axis='y', labelrotation=90, labelsize=8)
    ax.tick_params(axis='x', labelsize=8)

    def _ticks_overlap(labels):
        r = fig.canvas.get_renderer()
        bbs = [t.get_window_extent(r) for t in labels if t.get_visible() and t.get_text()]
        return any(a.overlaps(b) for a, b in zip(bbs, bbs[1:]))

    # Rótulos ainda se atropelando (mapa estreito/baixo) → menos marcações; no limite, inclina
    for axis, getter in ((ax.xaxis, ax.get_xticklabels), (ax.yaxis, ax.get_yticklabels)):
        nbins = axis.get_major_locator()._nbins if hasattr(axis.get_major_locator(), '_nbins') else 5
        fig.canvas.draw()
        while _ticks_overlap(getter()) and nbins > 2:
            nbins -= 1
            axis.set_major_locator(MaxNLocator(nbins))
            fig.canvas.draw()
        if axis is ax.xaxis and _ticks_overlap(getter()):
            ax.tick_params(axis='x', labelrotation=35)
            for t in ax.get_xticklabels():
                t.set_ha('right')
    for spine in ax.spines.values():
        spine.set_edgecolor('#424242')

    fig.suptitle("RELATÓRIO AMBIENTAL GEOESTATÍSTICO", fontsize=19, fontweight='bold', color='#1a1a1a', y=0.965)

    # 5. Painel lateral — blocos empilhados de cima para baixo (coordenadas do painel)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    panel_box = panel.get_window_extent(renderer)

    def next_y(artist, gap=0.025):
        bb = artist.get_window_extent(renderer)
        return (bb.y0 - panel_box.y0) / panel_box.height - gap

    artists = {}
    y = 1.0

    # Itens da legenda (definem o espaço do painel)
    display_order = ['consolidada', 'vegetacao', 'app', 'reserva', 'uso_restrito', 'agua', 'sem_classificacao', 'imovel']
    display_order += [k for k in gdfs if k not in display_order]
    handles = []
    for l in display_order:
        if l not in gdfs or gdfs[l].empty:
            continue
        extra_names = {'extra_servidao': 'Servidão administrativa', 'extra_pousio': 'Área de pousio'}
        label_text = COLORS.get(l, {}).get('label') or extra_names.get(l) or l.replace('extra_', '').replace('_', ' ').capitalize()
        style = COLORS.get(l)
        if style and style.get('facecolor') not in (None, 'none'):
            handles.append(Patch(facecolor=style['facecolor'], edgecolor=style['edgecolor'],
                                 alpha=style.get('alpha', 1.0), hatch=style.get('hatch'), label=label_text))
        elif style:
            handles.append(Line2D([0], [0], color=style['edgecolor'], lw=2.2,
                                  linestyle=style.get('linestyle', '-'), label=label_text))
        else:
            handles.append(Patch(facecolor='#9e9e9e', edgecolor='#424242', alpha=0.5, label=label_text))
    # Muitas camadas → legenda em 2 colunas e mapa regional menor, para caber tudo
    long_legend = len(handles) > 6

    # 5.1 Mapa regional (Sentinel-2) com o perímetro em amarelo
    st_code = str(main_gdf.iloc[0].get('COD_IMOVEL') or 'CAR')[:2]
    inset_h = 0.28 if long_legend else 0.36
    ax_inset = panel.inset_axes([0.0, y - inset_h, 1.0, inset_h])
    ax_inset.set_facecolor('#ffffff')
    try:
        from PIL import Image as _PILImage
        import io as _io
        if reg_bg_img and reg_bg_extent:
            ax_inset.imshow(np.asarray(_PILImage.open(_io.BytesIO(reg_bg_img)).convert('RGB')), extent=reg_bg_extent, zorder=0)
            ax_inset.set_xlim(reg_bg_extent[0], reg_bg_extent[1]); ax_inset.set_ylim(reg_bg_extent[2], reg_bg_extent[3])
        elif background_img and bg_extent:
            ax_inset.imshow(np.asarray(_PILImage.open(_io.BytesIO(background_img)).convert('RGB')), extent=bg_extent, zorder=0)
            ax_inset.set_xlim(bg_extent[0], bg_extent[1]); ax_inset.set_ylim(bg_extent[2], bg_extent[3])
        else:
            rb = main_gdf.buffer(0.08).total_bounds
            ax_inset.set_xlim(rb[0], rb[2]); ax_inset.set_ylim(rb[1], rb[3])
    except Exception as e:
        print(f"Erro no mapa de contexto: {e}")
    main_gdf.boundary.plot(ax=ax_inset, color='#ffeb3b', linewidth=1.4, zorder=9)
    main_gdf.centroid.plot(ax=ax_inset, color='red', edgecolor='white', markersize=25, zorder=10)
    # adjustable='box': a caixa segue a proporção da imagem (sem faixas brancas)
    ax_inset.set_aspect(1 / math.cos(math.radians((bounds[1] + bounds[3]) / 2)), adjustable='box')
    ax_inset.set_anchor('N')
    ax_inset.set_xticks([]); ax_inset.set_yticks([])
    for spine in ax_inset.spines.values():
        spine.set_edgecolor('black'); spine.set_linewidth(1.2)
    fig.canvas.draw()
    inset_box = ax_inset.get_window_extent(renderer)
    reg_label = panel.text(0.5, (inset_box.y0 - panel_box.y0) / panel_box.height - 0.008,
                           f"Localização regional ({st_code})", ha='center', va='top',
                           fontsize=10, fontweight='bold', transform=panel.transAxes)
    artists['mapa regional'] = ax_inset
    artists['título regional'] = reg_label
    y = next_y(reg_label)

    # 5.2 Quadro de áreas
    labels_friendly = {
        'imovel': 'Total do imóvel', 'reserva': 'Reserva Legal', 'app': 'A.P.P.',
        'vegetacao': 'Remanescente nativo', 'uso_restrito': 'Uso restrito', 'consolidada': 'Área antropizada',
        'sem_classificacao': 'Sem classificação',
    }
    rows = [f"{name:<20}{areas_ha[k]:>10.2f}".replace(f"{areas_ha[k]:.2f}", f"{areas_ha[k]:.2f}".replace('.', ','))
            for k, name in labels_friendly.items() if areas_ha.get(k, 0) > 0]
    areas_box = panel.text(0.0, y, "QUADRO DE ÁREAS (ha)\n" + "\n".join(rows), transform=panel.transAxes,
                           fontsize=9.5, ha='left', va='top', fontfamily='monospace',
                           bbox=dict(boxstyle='round,pad=0.6', facecolor='#f1f3f5', edgecolor='#adb5bd'))
    artists['quadro de áreas'] = areas_box
    y = next_y(areas_box, gap=0.035)

    # 5.3 Legenda (só camadas presentes; itens montados antes do painel)
    legend = panel.legend(handles=handles, loc='upper left', bbox_to_anchor=(0.0, y),
                          ncol=2 if long_legend else 1, fontsize=8.5 if long_legend else 9.5, frameon=True, facecolor='white', edgecolor='#ced4da',
                          title="Legenda", title_fontsize=10, alignment='left')
    artists['legenda'] = legend
    fig.canvas.draw()
    y = next_y(legend, gap=0.04)

    # 5.4 Escala gráfica (mesmo comprimento que teria no mapa) + Norte
    center = main_gdf.geometry.centroid.iloc[0]
    m_per_deg_lon = 111320 * np.cos(np.radians(center.y))
    map_box = ax.get_window_extent(renderer)
    x0, x1 = ax.get_xlim()
    px_per_m = map_box.width / ((x1 - x0) * m_per_deg_lon)
    for s_m, s_lab in ((10000, "10 km"), (5000, "5 km"), (2000, "2 km"), (1000, "1 km"),
                       (500, "500 m"), (200, "200 m"), (100, "100 m")):
        if s_m * px_per_m <= panel_box.width * 0.62:
            break
    bar_frac = s_m * px_per_m / panel_box.width
    bar_h = 0.012
    divs = 4
    for i in range(divs):
        panel.add_patch(Rectangle((i * bar_frac / divs, y - bar_h), bar_frac / divs, bar_h,
                                  transform=panel.transAxes, facecolor='black' if i % 2 == 0 else 'white',
                                  edgecolor='black', lw=1, clip_on=False))
    scale_title = panel.text(0.0, y + 0.006, "Escala", transform=panel.transAxes, fontsize=9, fontweight='bold', va='bottom')
    scale_0 = panel.text(0.0, y - bar_h - 0.006, "0", transform=panel.transAxes, fontsize=8, ha='center', va='top')
    scale_end = panel.text(bar_frac, y - bar_h - 0.006, s_lab, transform=panel.transAxes, fontsize=8, ha='center', va='top')
    north = panel.annotate('N', xy=(0.93, y + 0.005), xytext=(0.93, y - 0.055), xycoords='axes fraction',
                           ha='center', va='center', fontsize=15, fontweight='bold',
                           arrowprops=dict(facecolor='black', width=3, headwidth=10))
    artists['escala'] = scale_end
    artists['norte'] = north
    fig.canvas.draw()
    y = min(next_y(scale_end, gap=0.045), next_y(north, gap=0.045))

    # 5.5 Dados do imóvel
    info = panel.text(
        0.0, y,
        f"Propriedade: {prop_name}\nCódigo CAR:\n{cod_car}\n"
        f"Emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}\nSistema: SIRGAS 2000",
        transform=panel.transAxes, fontsize=9, ha='left', va='top', fontfamily='monospace',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#ced4da'))
    artists['dados do imóvel'] = info

    footer = fig.text(0.5, 0.02, "Processado com Agro Analytics Bot · Fonte: Consulta Pública do CAR (consulta.car.gov.br)",
                      ha='center', va='bottom', fontsize=8.5, color='gray')
    artists['rodapé'] = footer

    # 6. Controle de qualidade do layout
    LAST_LAYOUT_ISSUES = check_map_layout(fig, ax, artists)
    if not ax_inset.images:
        LAST_LAYOUT_ISSUES.append("mapa regional sem imagem de satélite")
    if LAST_LAYOUT_ISSUES:
        print(f"[MAPA CAR] ⚠️ Layout com problemas: {LAST_LAYOUT_ISSUES}", flush=True)

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=120, facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def generate_cda_summary_card(summary: dict):
    """
    Gera um card visual (PNG) com a tabela de preços do último leilão CDA
    e a comparação com o benchmark Scot.
    Returns: bytes PNG ou None se sem dados.
    """
    from io import BytesIO
    from datetime import datetime as _dt
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as _plt
    from app.exchange_rate import get_usd_brl_rate

    rows = summary.get('rows', [])
    if not rows:
        return None

    usd_brl = get_usd_brl_rate()

    event_name   = (summary.get('event_name') or 'Leilão CDA')[:55]
    event_date   = summary.get('event_date')
    location     = (summary.get('event_location') or '')[:45]
    total_heads  = summary.get('total_heads')
    total_volume = summary.get('total_volume_brl')
    date_str     = event_date.strftime('%d/%m/%Y') if event_date else '--'

    BG      = '#FFFFFF'
    HDR_BG  = '#EFF2F5'
    ROW_A   = '#FFFFFF'
    ROW_B   = '#F6F8FA'
    BORDER  = '#D0D7DE'
    TEXT    = '#1C2A3A'
    SUBTEXT = '#57606A'
    GREEN   = '#1A7F37'
    YELLOW  = '#B07C00'
    RED     = '#CF222E'
    ACCENT  = '#0969DA'

    n_rows   = min(len(rows), 12)
    has_scot = any(r.get('scot_price_usd') for r in rows[:n_rows])

    if has_scot:
        col_labels = ['Categoria', 'R$/kg', 'Cab.', 'Scot US$/@', 'vs. Scot']
    else:
        col_labels = ['Categoria', 'R$/kg', 'Lotes', 'Cab.']
    ncols = len(col_labels)

    def _br(v, dec=2):
        s = f"{v:,.{dec}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    table_data = []
    for row in rows[:n_rows]:
        race     = (row.get('race') or 'Outros').title()[:22]
        price_kg = row.get('avg_price_kg') or (row.get('avg_price_arroba', 0) / 30)
        price    = f"R$ {_br(price_kg)}"
        lots     = str(row.get('lots_count', 0))
        heads    = str(row.get('heads_count') or '-')
        scot_usd = row.get('scot_price_usd')
        scot     = f"US$ {scot_usd:.0f}" if scot_usd else "-"
        # Ratio correto: CDA R$/@ ÷ Scot R$/@ (ambos base carcaça, câmbio ao vivo)
        vs = "-"
        if price_kg and scot_usd and usd_brl:
            cda_arroba = price_kg * 30
            scot_arroba_brl = scot_usd * usd_brl
            pct = (cda_arroba / scot_arroba_brl) * 100
            vs = f"{pct:.1f}%"
        if has_scot:
            table_data.append([race, price, heads, scot, vs])
        else:
            table_data.append([race, price, lots, heads])

    stats_parts = []
    if total_heads and total_volume:
        media = total_volume / total_heads
        stats_parts.append(f"R\\$ {_br(media, 0)}/animal")
    if total_heads:
        stats_parts.append(f"{int(total_heads):,} cabeças".replace(",", "."))
    if total_volume:
        stats_parts.append(f"R\\$ {int(total_volume):,} em vendas".replace(",", "."))

    fig_h = 2.6 + n_rows * 0.58
    fig, ax = _plt.subplots(figsize=(10, fig_h), facecolor=BG)
    ax.set_facecolor(BG)
    ax.axis('off')

    # Reserva topo para o cabeçalho
    header_lines = 2 + (1 if stats_parts else 0)
    header_frac  = max(0.12, (header_lines * 0.38) / fig_h)
    fig.subplots_adjust(top=1.0 - header_frac - 0.01, bottom=0.07,
                        left=0.01, right=0.99)

    # Cabeçalho (fig coords)
    y = 0.97
    fig.text(0.5, y, event_name, ha='center', va='top',
             color=TEXT, fontsize=14, fontweight='bold')
    y -= max(0.055, 0.32 / fig_h)

    subtitle = date_str + (f'  •  {location}' if location else '')
    fig.text(0.5, y, subtitle, ha='center', va='top', color=SUBTEXT, fontsize=9.5)

    if stats_parts:
        y -= max(0.045, 0.26 / fig_h)
        fig.text(0.5, y, '   |   '.join(stats_parts),
                 ha='center', va='top', color=ACCENT, fontsize=9.5, fontweight='bold')

    # Tabela (preenche o axes)
    tbl = ax.table(
        cellText=table_data,
        colLabels=col_labels,
        cellLoc='center',
        loc='center',
        bbox=[0.0, 0.0, 1.0, 1.0]
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10.5)

    vs_col = ncols - 1
    for (ri, ci), cell in tbl.get_celld().items():
        cell.set_linewidth(0.4)
        cell.set_edgecolor(BORDER)
        if ri == 0:
            cell.set_facecolor(HDR_BG)
            cell.get_text().set_color(TEXT)
            cell.get_text().set_fontweight('bold')
            cell.get_text().set_fontsize(9.5)
        else:
            cell.set_facecolor(ROW_B if ri % 2 == 0 else ROW_A)
            tv = cell.get_text().get_text()
            if ci == vs_col and tv not in ('-', ''):
                try:
                    pv = float(tv.replace('%', ''))
                    c = GREEN if pv >= 100 else (YELLOW if pv >= 90 else RED)
                    cell.get_text().set_color(c)
                    cell.get_text().set_fontweight('bold')
                except Exception:
                    cell.get_text().set_color(SUBTEXT)
            elif ci == 1:
                cell.get_text().set_color(TEXT)
                cell.get_text().set_fontweight('bold')
            elif ci == 0:
                cell.get_text().set_color(TEXT)
            else:
                cell.get_text().set_color(SUBTEXT)

    # Rodapé
    fig.text(0.5, 0.012,
             f"Correa da Costa Agropecuaria  |  {_dt.now().strftime('%d/%m/%Y')}  |  Agro Analytics Bot",
             ha='center', va='bottom', color=SUBTEXT, fontsize=7.5, style='italic')

    buf = BytesIO()
    _plt.savefig(buf, format='png', dpi=140, facecolor=BG, bbox_inches='tight',
                 edgecolor='none')
    _plt.close()
    buf.seek(0)
    return buf.read()


def generate_cda_price_chart(days=365):
    """
    Gera um gráfico premium de evolução de preços do Leilão Correa da Costa.

    Painel superior: preço médio/@BRL por categoria de raça ao longo do tempo.
    Painel inferior: número de lotes negociados por semana (volume de mercado).
    Sobrepõe a cotação Scot Brasil (USD) como benchmark de referência.

    Returns: path do arquivo PNG ou None se sem dados.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as mticker
    from matplotlib.lines import Line2D
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta
    from app.models import SessionLocal, CdaMarketComparison, PriceHistory
    from sqlalchemy import func

    # ── 1. Carregar dados ────────────────────────────────────────────────────
    session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        rows = (
            session.query(CdaMarketComparison)
            .filter(CdaMarketComparison.reference_date >= cutoff)
            .order_by(CdaMarketComparison.reference_date.asc())
            .all()
        )

        scot_rows = (
            session.query(PriceHistory)
            .filter(
                PriceHistory.country == 'Brasil',
                PriceHistory.date >= cutoff
            )
            .order_by(PriceHistory.date.asc())
            .all()
        )
    finally:
        session.close()

    if not rows:
        return None

    # ── 2. Montar DataFrames ─────────────────────────────────────────────────
    df = pd.DataFrame([{
        'date': r.reference_date,
        'race': r.race_norm or 'Outros',
        # R$/kg como métrica primária; fallback p/ legados com só R$/@
        'price_kg': r.avg_cda_price_per_kg_brl or (
            (r.avg_cda_price_per_arroba_brl / 15) if r.avg_cda_price_per_arroba_brl else None
        ),
        'lots': r.lots_count or 0,
    } for r in rows])
    df['date'] = pd.to_datetime(df['date'])
    df = df.dropna(subset=['price_kg'])

    df_scot = pd.DataFrame([{
        'date': r.date,
        'price_usd': r.price,
    } for r in scot_rows])
    if not df_scot.empty:
        df_scot['date'] = pd.to_datetime(df_scot['date'])
        df_scot = df_scot.groupby('date')['price_usd'].mean().reset_index()
        df_scot = df_scot.sort_values('date')

    # Agrupar volume semanal
    df_vol = df.copy()
    df_vol = df_vol.set_index('date').resample('W')['lots'].sum().reset_index()

    # Escolher as 5 raças mais frequentes para a legenda
    top_races = (
        df.groupby('race')['lots'].sum()
        .nlargest(5)
        .index.tolist()
    )
    df_top = df[df['race'].isin(top_races)].copy()

    # Suavização: média móvel de 4 semanas por raça
    def smooth_series(sub):
        sub = sub.set_index('date').resample('W')['price_kg'].mean().reset_index()
        sub['price_kg'] = sub['price_kg'].rolling(4, min_periods=1).mean()
        return sub

    # ── 3. Paleta e tema ─────────────────────────────────────────────────────
    BG        = '#FFFFFF'
    PANEL_BG  = '#FAFBFC'
    GRID      = '#D8DEE4'
    TEXT      = '#1C2A3A'
    SUBTEXT   = '#57606A'
    ACCENT    = '#0969DA'
    VOLUME    = '#0550AE'

    RACE_PALETTE = [
        '#CF222E',  # vermelho
        '#116329',  # verde escuro
        '#7A43B6',  # roxo
        '#B45309',  # âmbar
        '#0550AE',  # azul escuro
    ]

    # ── 4. Figura com 2 painéis ──────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 10), facecolor=BG)
    gs  = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.06)
    ax_price  = fig.add_subplot(gs[0])
    ax_volume = fig.add_subplot(gs[1], sharex=ax_price)

    for ax in (ax_price, ax_volume):
        ax.set_facecolor(PANEL_BG)
        ax.spines[:].set_color(GRID)
        ax.tick_params(colors=SUBTEXT, labelsize=10)
        ax.yaxis.grid(True, color=GRID, linewidth=0.7, linestyle='--')
        ax.xaxis.grid(True, color=GRID, linewidth=0.5, linestyle=':')
        ax.set_axisbelow(True)

    # ── 5. Painel superior: preço/@ por raça ────────────────────────────────
    legend_handles = []
    for i, race in enumerate(top_races):
        color = RACE_PALETTE[i % len(RACE_PALETTE)]
        sub = df_top[df_top['race'] == race]
        sub_smooth = smooth_series(sub[['date', 'price_kg']].copy())

        ax_price.plot(
            sub_smooth['date'], sub_smooth['price_kg'],
            color=color, linewidth=2.4, alpha=0.92, zorder=5
        )
        # Marcador no último valor
        last = sub_smooth.dropna().iloc[-1] if not sub_smooth.dropna().empty else None
        if last is not None:
            ax_price.scatter(last['date'], last['price_kg'],
                             color=color, s=55, zorder=8, edgecolors=BG, linewidth=0.8)
            ax_price.annotate(
                f"R$ {last['price_kg']:,.2f}/kg",
                xy=(last['date'], last['price_kg']),
                xytext=(8, 0), textcoords='offset points',
                fontsize=9, color=color, va='center', fontweight='bold'
            )

        # Área sombreada suave
        ax_price.fill_between(
            sub_smooth['date'], sub_smooth['price_kg'],
            alpha=0.06, color=color, zorder=2
        )
        label = race.title() if race else 'Outros'
        legend_handles.append(Line2D([0], [0], color=color, linewidth=2.2, label=label))

    # Eixo secundário: Scot USD — ylim começa em 0 para não distorcer a posição vertical
    if not df_scot.empty:
        ax2 = ax_price.twinx()
        ax2.set_facecolor(PANEL_BG)
        ax2.spines[:].set_color(GRID)
        scot_smooth = df_scot.set_index('date')['price_usd'].rolling(4, min_periods=1).mean()
        ax2.plot(
            scot_smooth.index, scot_smooth.values,
            color=ACCENT, linewidth=1.6, linestyle='--', alpha=0.7, zorder=4
        )
        scot_max = scot_smooth.max() * 1.15
        ax2.set_ylim(bottom=0, top=scot_max)
        ax2.set_ylabel('Cotação Scot Brasil (US$/@)', color=ACCENT, fontsize=10, labelpad=10)
        ax2.tick_params(colors=ACCENT, labelsize=9)
        ax2.yaxis.label.set_color(ACCENT)
        ax2.tick_params(axis='y', colors=ACCENT)
        legend_handles.append(
            Line2D([0], [0], color=ACCENT, linewidth=1.6, linestyle='--', label='Scot Brasil (US$)')
        )

    ax_price.set_ylabel('Preço Médio R$/kg vivo (Leilão CDA)', color=TEXT, fontsize=11, labelpad=12)
    ax_price.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'R$ {x:,.2f}'))
    ax_price.tick_params(axis='x', labelbottom=False)

    ax_price.legend(
        handles=legend_handles,
        loc='upper left',
        frameon=True, facecolor=PANEL_BG, edgecolor=GRID,
        labelcolor=TEXT, fontsize=10,
    )

    # ── 6. Painel inferior: volume (lotes/semana) ───────────────────────────
    ax_volume.bar(
        df_vol['date'], df_vol['lots'],
        width=6, color=VOLUME, alpha=0.75, zorder=3
    )
    ax_volume.set_ylabel('Lotes / semana', color=SUBTEXT, fontsize=9, labelpad=8)
    ax_volume.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))
    ax_volume.tick_params(axis='y', colors=SUBTEXT, labelsize=9)

    # ── 7. Eixo X compartilhado ──────────────────────────────────────────────
    locator = mdates.MonthLocator(interval=2) if days <= 365 else mdates.MonthLocator(interval=4)
    ax_volume.xaxis.set_major_locator(locator)
    ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%b/%y'))
    plt.setp(ax_volume.xaxis.get_majorticklabels(), rotation=30, ha='right', color=SUBTEXT)

    # ── 8. Título e rodapé ──────────────────────────────────────────────────
    period_label = f'Últimos {days} dias' if days < 3650 else 'Histórico completo'
    fig.suptitle(
        f'Evolução de Preços — Leilão Correa da Costa (CDA)\n{period_label}',
        fontsize=17, fontweight='bold', color=TEXT,
        y=0.97
    )
    fig.text(
        0.5, 0.01,
        f'Fonte: Correa da Costa Agropecuária  •  Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}  •  Agro Analytics Bot',
        ha='center', fontsize=8.5, color=SUBTEXT, style='italic'
    )

    # Watermark logo
    logo_path = 'app/assets/logo.jpg'
    if os.path.exists(logo_path):
        try:
            logo_img = plt.imread(logo_path)
            newax = fig.add_axes([0.35, 0.25, 0.30, 0.30], zorder=0)
            newax.imshow(logo_img, alpha=0.04)
            newax.axis('off')
        except Exception:
            pass

    plt.subplots_adjust(left=0.08, right=0.88, top=0.91, bottom=0.10)

    import time
    output_path = f'/tmp/cda_price_chart_{int(time.time())}.png'
    plt.savefig(output_path, dpi=150, facecolor=BG, edgecolor='none', bbox_inches='tight')
    plt.close()
    return output_path

