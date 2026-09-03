"""
Composição dos mapas A5 paisagem (antes/depois) da ferramenta PRODES.
Reaproveita o *padrão* de normalização de coordenadas 0-1 já usado em
app/environmental.py (generate_environmental_image), mas como implementação
própria — sem import cruzado, para não acoplar a ferramenta jurídica ao
módulo de NDVI. Ver prompt_ferramenta_prodes_bot.md, seção "OS MAPAS".
"""
import math
import textwrap
from io import BytesIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, ConnectionPatch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from shapely.geometry import shape

A5_LANDSCAPE_INCHES = (210 / 25.4, 148 / 25.4)
MAP_DPI = 300

_NICE_MINUTE_STEPS = [1, 2, 5, 10, 15, 30, 60]


def _extract_rings(geometry):
    """Extrai os anéis de coordenadas de um Polygon ou MultiPolygon GeoJSON."""
    if not geometry:
        return []
    gtype = geometry.get('type', '')
    if gtype == 'Polygon':
        return geometry['coordinates']
    if gtype == 'MultiPolygon':
        return [ring for poly in geometry['coordinates'] for ring in poly]
    return []


def _format_dm(decimal_degrees: float, is_lat: bool) -> str:
    """Ex.: 57°36'W / 18°18'S — grau e minuto, sem casas decimais."""
    abs_deg = abs(decimal_degrees)
    d = int(abs_deg)
    m = round((abs_deg - d) * 60)
    if m == 60:
        d += 1
        m = 0
    if is_lat:
        hemi = 'S' if decimal_degrees < 0 else 'N'
    else:
        hemi = 'W' if decimal_degrees < 0 else 'E'
    return f"{d}°{m:02d}'{hemi}"


def _pick_tick_step_deg(span_deg: float, target_ticks: int = 4) -> float:
    span_minutes = span_deg * 60
    raw_step = max(span_minutes / target_ticks, 0.01)
    for step in _NICE_MINUTE_STEPS:
        if step >= raw_step:
            return step / 60.0
    return _NICE_MINUTE_STEPS[-1] / 60.0


def _generate_ticks(vmin: float, vmax: float, target_ticks: int = 4) -> list:
    step = _pick_tick_step_deg(vmax - vmin, target_ticks)
    start = math.ceil(vmin / step) * step
    ticks = []
    v = start
    while v <= vmax:
        ticks.append(v)
        v += step
    return ticks or [vmin, vmax]


def _draw_zebra_frame(ax, n_segments: int = 20, thickness: float = 0.018):
    """Moldura zebrada preta e branca ao redor do eixo (coordenadas de eixo, fora de [0,1])."""
    seg_w = 1.0 / n_segments
    for i in range(n_segments):
        color = 'black' if i % 2 == 0 else 'white'
        kwargs = dict(transform=ax.transAxes, facecolor=color, edgecolor='black',
                      linewidth=0.3, clip_on=False, zorder=10)
        ax.add_patch(Rectangle((i * seg_w, -thickness), seg_w, thickness, **kwargs))
        ax.add_patch(Rectangle((i * seg_w, 1.0), seg_w, thickness, **kwargs))
        ax.add_patch(Rectangle((-thickness, i * seg_w), thickness, seg_w, **kwargs))
        ax.add_patch(Rectangle((1.0, i * seg_w), thickness, seg_w, **kwargs))


def _draw_ring(ax, ring, minx, miny, w, h, color, linewidth):
    xs = [(x - minx) / w for x, y in ring]
    ys = [(y - miny) / h for x, y in ring]
    ax.plot(xs, ys, color=color, linewidth=linewidth, linestyle='-', zorder=6)


def compose_prodes_map(scene_png_bytes: bytes, property_geometry: dict, apontamento_geometry: dict,
                        scene_meta: dict, area_total_ha: float, area_intersect_ha: float,
                        source_info: dict, position: str, footer_notes: list = None) -> BytesIO:
    """
    Monta um mapa A5 paisagem (210x148mm, 300dpi): cena recortada no
    perímetro (metade esquerda), moldura zebrada com coordenadas em grau e
    minuto, perímetro do imóvel em amarelo / apontamento em vermelho (só
    contorno), inset com zoom do apontamento + seta, coluna de texto com
    áreas, data, legenda e procedência. `position` é 'antes' ou 'depois'.
    """
    property_poly = shape(property_geometry)
    minx, miny, maxx, maxy = property_poly.bounds
    w = maxx - minx
    h = maxy - miny

    img = plt.imread(BytesIO(scene_png_bytes), format='png')

    fig = plt.figure(figsize=A5_LANDSCAPE_INCHES, dpi=MAP_DPI)
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 0.65], wspace=0.05)
    ax_main = fig.add_subplot(gs[0, 0])
    ax_text = fig.add_subplot(gs[0, 1])
    ax_text.axis('off')

    ax_main.imshow(img, extent=[0, 1, 0, 1], origin='upper')
    ax_main.set_xlim(0, 1)
    ax_main.set_ylim(0, 1)

    for ring in _extract_rings(property_geometry):
        _draw_ring(ax_main, ring, minx, miny, w, h, 'yellow', 2.0)
    for ring in _extract_rings(apontamento_geometry):
        _draw_ring(ax_main, ring, minx, miny, w, h, 'red', 2.0)

    lon_ticks = _generate_ticks(minx, maxx)
    lat_ticks = _generate_ticks(miny, maxy)
    ax_main.set_xticks([(t - minx) / w for t in lon_ticks])
    ax_main.set_xticklabels([_format_dm(t, is_lat=False) for t in lon_ticks], fontsize=6)
    ax_main.set_yticks([(t - miny) / h for t in lat_ticks])
    # Latitude (eixo Y, borda esquerda) na vertical, paralela à linha lateral do mapa.
    # Precisa ser via set_yticklabels(..., rotation=90) com texto explícito — tick_params
    # (labelrotation) não é respeitado de forma confiável no savefig com esta versão do matplotlib.
    ax_main.set_yticklabels([_format_dm(t, is_lat=True) for t in lat_ticks], fontsize=6,
                             rotation=90, va='center')
    ax_main.tick_params(length=2)
    for spine in ax_main.spines.values():
        spine.set_visible(False)

    _draw_zebra_frame(ax_main)

    # ── Inset com zoom do apontamento + retângulo indicador + seta ──────────
    apon_poly = shape(apontamento_geometry)
    axmin, aymin, axmax, aymax = apon_poly.bounds
    pad_x = (axmax - axmin) * 0.3 or (w * 0.05)
    pad_y = (aymax - aymin) * 0.3 or (h * 0.05)
    inset_minx, inset_maxx = axmin - pad_x, axmax + pad_x
    inset_miny, inset_maxy = aymin - pad_y, aymax + pad_y

    axins = inset_axes(ax_main, width="35%", height="35%", loc='upper right', borderpad=1.2)
    axins.imshow(img, extent=[0, 1, 0, 1], origin='upper')
    ix0 = (inset_minx - minx) / w
    ix1 = (inset_maxx - minx) / w
    iy0 = (inset_miny - miny) / h
    iy1 = (inset_maxy - miny) / h
    axins.set_xlim(ix0, ix1)
    axins.set_ylim(iy0, iy1)
    axins.set_xticks([])
    axins.set_yticks([])
    for spine in axins.spines.values():
        spine.set_edgecolor('black')
        spine.set_linewidth(1.5)

    for ring in _extract_rings(property_geometry):
        _draw_ring(axins, ring, minx, miny, w, h, 'yellow', 1.5)
    for ring in _extract_rings(apontamento_geometry):
        _draw_ring(axins, ring, minx, miny, w, h, 'red', 1.5)

    rect = Rectangle((ix0, iy0), ix1 - ix0, iy1 - iy0, fill=False,
                      edgecolor='black', linewidth=1.0, zorder=7)
    ax_main.add_patch(rect)
    con = ConnectionPatch(
        xyA=((ix0 + ix1) / 2, iy1), coordsA=ax_main.transData,
        xyB=(0.5, 0.0), coordsB=axins.transAxes,
        arrowstyle='-|>', mutation_scale=14,
        color='black', linewidth=1.0, zorder=8,
    )
    fig.add_artist(con)

    # ── Coluna de texto ──────────────────────────────────────────────────────
    date_label = scene_meta['date'].strftime('%d/%m/%Y') if scene_meta.get('date') else 'data desconhecida'
    source_label = (source_info or {}).get('label') or 'TerraBrasilis/INPE'

    blocks = [
        (f"Cena — {position.upper()}", 12, 'bold'),
        (date_label, 14, 'bold'),
        (f"Área do apontamento — {area_total_ha:.2f} ha ({area_intersect_ha:.2f} ha dentro do imóvel)", 9, 'normal'),
        ("Legenda", 9, 'bold'),
        ("— Perímetro do imóvel (amarelo)", 7.5, 'normal'),
        ("— Apontamento PRODES (vermelho)", 7.5, 'normal'),
        ("Procedência da cena", 9, 'bold'),
        (f"ID: {scene_meta.get('system_index', '—')}", 7.5, 'normal'),
        (f"Coleção: {scene_meta.get('collection_id', '—')}", 7.5, 'normal'),
        (f"Nuvem sobre o imóvel: {scene_meta.get('cloud_pct', 0):.1f}%", 7.5, 'normal'),
        (f"Cobertura do imóvel: {scene_meta.get('coverage_pct', 0):.1f}%", 7.5, 'normal'),
        (f"Base PRODES/INPE: {source_label}", 7.5, 'normal'),
    ]

    y = 0.97
    for text_line, fontsize, weight in blocks:
        for wl in (textwrap.wrap(text_line, width=44) or ['']):
            ax_text.text(0.02, y, wl, fontsize=fontsize, fontweight=weight,
                         va='top', ha='left', transform=ax_text.transAxes)
            y -= 0.032
        y -= 0.012

    if footer_notes:
        y -= 0.015
        ax_text.text(0.02, y, "Notas", fontsize=8, fontweight='bold',
                     va='top', transform=ax_text.transAxes)
        y -= 0.03
        for note in footer_notes:
            for wl in textwrap.wrap(note, width=48):
                ax_text.text(0.02, y, wl, fontsize=6.2, va='top',
                             transform=ax_text.transAxes, color='#333333')
                y -= 0.022
            y -= 0.006

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=MAP_DPI, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return buf


# Marco temporal de área rural consolidada, Lei 12.651/2012, art. 3º, IV (22/07/2008)
# — mesma referência usada em LEGAL_CONSOLIDATION_MARK (app/prodes_analysis.py).
# Apontamentos até 2008 (inclusive) entram na rampa azul; dali em diante, amarelo->vermelho.
OVERVIEW_LEGAL_MARK_YEAR = 2008


def _year_color(year, cmap_before, norm_before, cmap_after, norm_after):
    if year is None:
        return '#999999'
    if year <= OVERVIEW_LEGAL_MARK_YEAR:
        # desloca pra fora do extremo quase-branco do Blues, senão anos antigos somem no fundo
        return cmap_before(0.35 + 0.65 * norm_before(year))
    return cmap_after(0.25 + 0.75 * norm_after(year))


def compose_prodes_overview_map(property_geometry: dict, apontamentos: list, cod_imovel: str = None) -> BytesIO:
    """
    Mapa-visão-geral: perímetro do imóvel + TODOS os apontamentos PRODES
    encontrados de uma vez — enviado logo após a listagem em texto, antes do
    usuário escolher qual apontamento vai para a análise detalhada (mapas
    antes/depois + PDF, gerados só depois pelo worker). Não usa imagem de
    satélite de fundo nem chama o GEE — só desenha as geometrias já trazidas
    pelo WFS em find_intersecting_apontamentos, então é rápido.

    Cor por ano em duas rampas, separadas pelo marco de área consolidada
    (22/07/2008): azul (claro->escuro) para até 2008, amarelo->vermelho para
    depois — a cor já comunica de longe se o apontamento é anterior ou
    posterior ao marco legal.
    """
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable, get_cmap
    from matplotlib.lines import Line2D

    property_poly = shape(property_geometry)
    bounds_list = [property_poly.bounds]
    for ap in apontamentos:
        if ap.get('geometry'):
            bounds_list.append(shape(ap['geometry']).bounds)

    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    pad_x = (maxx - minx) * 0.06 or 0.005
    pad_y = (maxy - miny) * 0.06 or 0.005
    minx -= pad_x
    maxx += pad_x
    miny -= pad_y
    maxy += pad_y

    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
    ax.set_facecolor('#eef3ea')

    for ring in _extract_rings(property_geometry):
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        ax.plot(xs, ys, color='black', linewidth=2.2, zorder=5)

    years = [ap['year'] for ap in apontamentos if ap.get('year')]
    years_before = [y for y in years if y <= OVERVIEW_LEGAL_MARK_YEAR]
    years_after = [y for y in years if y > OVERVIEW_LEGAL_MARK_YEAR]

    cmap_before = get_cmap('Blues')
    cmap_after = get_cmap('YlOrRd')
    norm_before = Normalize(
        vmin=min(years_before) if years_before else OVERVIEW_LEGAL_MARK_YEAR - 10,
        vmax=OVERVIEW_LEGAL_MARK_YEAR,
    )
    norm_after = Normalize(
        vmin=OVERVIEW_LEGAL_MARK_YEAR,
        vmax=max(years_after) if years_after else OVERVIEW_LEGAL_MARK_YEAR + 10,
    )

    for ap in apontamentos:
        color = _year_color(ap.get('year'), cmap_before, norm_before, cmap_after, norm_after)
        for ring in _extract_rings(ap.get('geometry')):
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            ax.fill(xs, ys, color=color, alpha=0.85, zorder=3, edgecolor='#333333', linewidth=0.4)

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect('equal')
    ax.set_title(
        f"Visão geral — CAR {cod_imovel or '—'} — {len(apontamentos)} apontamento(s) PRODES",
        fontsize=11, fontweight='bold',
    )
    ax.tick_params(labelsize=7)

    # Mesmo estilo de coordenadas (grau/minuto) do mapa antes/depois — e a mesma
    # ressalva se aplica aqui: precisa ser set_xticklabels/set_yticklabels com texto
    # explícito, tick_params(labelrotation) não é respeitado de forma confiável no
    # savefig nesta versão do matplotlib.
    lon_ticks = _generate_ticks(minx, maxx)
    lat_ticks = _generate_ticks(miny, maxy)
    ax.set_xticks(lon_ticks)
    ax.set_xticklabels([_format_dm(t, is_lat=False) for t in lon_ticks], fontsize=7)
    ax.set_yticks(lat_ticks)
    # Latitude (eixo Y, borda esquerda) na vertical, paralela à linha lateral do mapa.
    ax.set_yticklabels([_format_dm(t, is_lat=True) for t in lat_ticks], fontsize=7,
                        rotation=90, va='center')

    # Uma única coluna reservada à direita, dividida em duas metades que se
    # tocam (sem espaço entre elas) — lê como uma linha do tempo contínua:
    # mais recente (vermelho) em cima, mais antigo (azul) embaixo, com a
    # transição bem no marco de 2008. Duas fig.colorbar(ax=ax) lado a lado
    # ficariam horizontais; aqui é um único cax de mplt_toolkits dividido.
    if years_before or years_after:
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.35)
        cax.axis('off')

        if years_before and years_after:
            cax_after = cax.inset_axes([0, 0.5, 1, 0.5])
            cax_before = cax.inset_axes([0, 0.0, 1, 0.5])
        elif years_after:
            cax_after, cax_before = cax.inset_axes([0, 0, 1, 1]), None
        else:
            cax_after, cax_before = None, cax.inset_axes([0, 0, 1, 1])

        if cax_after is not None:
            sm_after = ScalarMappable(cmap=cmap_after, norm=norm_after)
            sm_after.set_array([])
            cbar_after = fig.colorbar(sm_after, cax=cax_after)
            cbar_after.set_label(f'Ano (após {OVERVIEW_LEGAL_MARK_YEAR})', fontsize=8)
            cbar_after.ax.tick_params(labelsize=7)

        if cax_before is not None:
            sm_before = ScalarMappable(cmap=cmap_before, norm=norm_before)
            sm_before.set_array([])
            cbar_before = fig.colorbar(sm_before, cax=cax_before)
            cbar_before.set_label(f'Ano (até {OVERVIEW_LEGAL_MARK_YEAR})', fontsize=8)
            cbar_before.ax.tick_params(labelsize=7)

    ax.legend(handles=[Line2D([0], [0], color='black', lw=2.2, label='Perímetro do imóvel')],
              loc='upper right', fontsize=8, framealpha=0.9)

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return buf
