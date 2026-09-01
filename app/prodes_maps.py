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
    ax_main.set_yticklabels([_format_dm(t, is_lat=True) for t in lat_ticks], fontsize=6)
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
