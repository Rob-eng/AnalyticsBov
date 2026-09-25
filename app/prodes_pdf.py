"""
Geração do PDF ("laudo") da ferramenta PRODES via reportlab. Um documento por
apontamento analisado. Ver prompt_ferramenta_prodes_bot.md, seção "O PDF".

Estrutura (A4):
  1. Capa-resumo: faixa de título, identificação do imóvel, apontamento
     analisado, resultado NDVI (antes → depois) e metodologia resumida.
  2. Mapas antes/depois (NDVI), como figuras numeradas.
  3. Procedência das cenas, notas técnicas, fontes e responsabilidade.
Cabeçalho/rodapé em todas as páginas com nº do documento e "Página X de Y".

Fonte DejaVu Sans (vem com o matplotlib, a mesma dos mapas): a Helvetica
padrão do reportlab não tem glifos como "−", "∩" e "→".
"""
import os
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, NextPageTemplate, PageBreak, KeepTogether,
    Paragraph, Spacer, Table, TableStyle, Image as RLImage,
)

# ── Identidade visual ─────────────────────────────────────────────────────────
PRIMARY = colors.HexColor('#1f4e3d')   # verde escuro institucional
ACCENT = colors.HexColor('#2e7d5b')
INK = colors.HexColor('#1a1a1a')
MUTED = colors.HexColor('#5f6b66')
RULE = colors.HexColor('#d5ddd9')
SOFT = colors.HexColor('#f2f6f4')
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 24 * mm
MARGIN_BOTTOM = 20 * mm
COVER_BAND_H = 44 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X


def _register_fonts():
    """DejaVu Sans do matplotlib; cai para Helvetica se não achar."""
    try:
        import matplotlib
        base = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf')
        pdfmetrics.registerFont(TTFont('DejaVu', os.path.join(base, 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', os.path.join(base, 'DejaVuSans-Bold.ttf')))
        # família: faz <b>…</b> dentro de Paragraph usar a variante negrito
        pdfmetrics.registerFontFamily('DejaVu', normal='DejaVu', bold='DejaVu-Bold',
                                      italic='DejaVu', boldItalic='DejaVu-Bold')
        return 'DejaVu', 'DejaVu-Bold'
    except Exception:
        return 'Helvetica', 'Helvetica-Bold'


FONT, FONT_BOLD = _register_fonts()


def _style(name, size, leading=None, bold=False, color=INK, **kw):
    return ParagraphStyle(name, fontName=FONT_BOLD if bold else FONT, fontSize=size,
                          leading=leading or size * 1.35, textColor=color, **kw)


S_H1 = _style('h1', 12, bold=True, color=PRIMARY, spaceBefore=4, spaceAfter=6)
S_BODY = _style('body', 9, leading=13)
S_SMALL = _style('small', 7.5, leading=10.5, color=MUTED)
S_LABEL = _style('label', 7, leading=9, color=MUTED)
S_VALUE = _style('value', 9.5, leading=12.5, bold=True)
S_KPI_LABEL = _style('kpil', 7, leading=9, color=MUTED, alignment=TA_CENTER)
S_KPI_VALUE = _style('kpiv', 15, leading=18, bold=True, color=PRIMARY, alignment=TA_CENTER)
S_KPI_SUB = _style('kpis', 7, leading=9, color=MUTED, alignment=TA_CENTER)
S_CAPTION = _style('cap', 8, leading=11, color=MUTED, alignment=TA_LEFT)
S_TH = _style('th', 8, leading=10, bold=True, color=WHITE)
S_TD = _style('td', 8, leading=10.5)


# ── Formatação pt-BR ──────────────────────────────────────────────────────────

def _num(value, decimals=2):
    if value is None:
        return '—'
    return f"{value:,.{decimals}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _date(d):
    return d.strftime('%d/%m/%Y') if d else '—'


def _dms(value, is_lat):
    if value is None:
        return '—'
    hemi = ('S' if value < 0 else 'N') if is_lat else ('W' if value < 0 else 'E')
    v = abs(value)
    deg = int(v)
    minutes = int((v - deg) * 60)
    seconds = (v - deg - minutes / 60) * 3600
    return f"{deg}°{minutes:02d}'{seconds:04.1f}\"{hemi}".replace('.', ',')


def _scene(scene, field, fmt='{}'):
    if not scene or scene.get(field) is None:
        return '—'
    return fmt.format(scene[field])


# ── Página: cabeçalho, rodapé, numeração ─────────────────────────────────────

class _NumberedCanvas(rl_canvas.Canvas):
    """Adia o desenho do rodapé até saber o total de páginas ("Página X de Y")."""

    def __init__(self, *args, doc_meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []
        self._meta = doc_meta or {}

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total):
        m = self._meta
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, 13 * mm, PAGE_W - MARGIN_X, 13 * mm)
        self.setFont(FONT, 7)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_X, 9 * mm, f"Documento {m.get('doc_no', '—')} · gerado em {m.get('generated', '—')}")
        self.drawRightString(PAGE_W - MARGIN_X, 9 * mm, f"Página {self._pageNumber} de {total}")


def _draw_cover(canv, doc):
    m = doc.meta
    canv.saveState()
    canv.setFillColor(PRIMARY)
    canv.rect(0, PAGE_H - COVER_BAND_H, PAGE_W, COVER_BAND_H, stroke=0, fill=1)
    canv.setFillColor(ACCENT)
    canv.rect(0, PAGE_H - COVER_BAND_H - 1.6 * mm, PAGE_W, 1.6 * mm, stroke=0, fill=1)

    canv.setFillColor(colors.HexColor('#b9d8ca'))
    canv.setFont(FONT_BOLD, 8)
    canv.drawString(MARGIN_X, PAGE_H - 14 * mm, "LAUDO TÉCNICO")
    canv.setFillColor(WHITE)
    canv.setFont(FONT_BOLD, 19)
    canv.drawString(MARGIN_X, PAGE_H - 24 * mm, "Análise de Desmatamento — PRODES/INPE")
    canv.setFont(FONT, 9.5)
    canv.drawString(MARGIN_X, PAGE_H - 31.5 * mm,
                    "Cruzamento do perímetro do CAR com a base PRODES e evidência por NDVI (antes × depois)")

    canv.setFont(FONT, 8)
    canv.setFillColor(colors.HexColor('#dcebe4'))
    canv.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14 * mm,
                         f"Documento {m['doc_no']}  ·  emitido em {m['generated']}")
    canv.restoreState()


def _draw_header(canv, doc):
    m = doc.meta
    canv.saveState()
    canv.setFillColor(PRIMARY)
    canv.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
    canv.setFont(FONT_BOLD, 7.5)
    canv.setFillColor(PRIMARY)
    canv.drawString(MARGIN_X, PAGE_H - 12 * mm, "LAUDO TÉCNICO · ANÁLISE PRODES/INPE")
    canv.setFont(FONT, 7.5)
    canv.setFillColor(MUTED)
    canv.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 12 * mm, f"CAR {m['cod_imovel']}")
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.6)
    canv.line(MARGIN_X, PAGE_H - 14.5 * mm, PAGE_W - MARGIN_X, PAGE_H - 14.5 * mm)
    canv.restoreState()


# ── Blocos de conteúdo ────────────────────────────────────────────────────────

def _section(number, title):
    return Paragraph(f"{number}. {title}", S_H1)


def _kv_grid(pairs, cols=2):
    """Grade de rótulo/valor em caixa suave (pares preenchidos em linhas de `cols`)."""
    cells = [[Paragraph(label.upper(), S_LABEL), Paragraph(value, S_VALUE)] for label, value in pairs]
    rows = []
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols]
        chunk += [[Paragraph('', S_LABEL), Paragraph('', S_VALUE)]] * (cols - len(chunk))
        rows.append([c for c in chunk])
    col_w = CONTENT_W / cols
    table = Table([[_stack(c) for c in row] for row in rows], colWidths=[col_w] * cols)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SOFT),
        ('BOX', (0, 0), (-1, -1), 0.6, RULE),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return table


def _stack(pair):
    inner = Table([[pair[0]], [pair[1]]], colWidths=[None])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return inner


def _kpi_row(items):
    """Cartões de indicador: [(rótulo, valor, subtítulo), ...]."""
    cells = [[Paragraph(label.upper(), S_KPI_LABEL), Paragraph(value, S_KPI_VALUE),
              Paragraph(sub or '&nbsp;', S_KPI_SUB)] for label, value, sub in items]
    col_w = CONTENT_W / len(items)
    table = Table([[_stack3(c) for c in cells]], colWidths=[col_w] * len(items))
    style = [
        ('BOX', (0, 0), (-1, -1), 0.6, RULE),
        ('LINEBEFORE', (1, 0), (-1, 0), 0.6, RULE),
        ('LINEABOVE', (0, 0), (-1, 0), 2.2, ACCENT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]
    table.setStyle(TableStyle(style))
    return table


def _stack3(items):
    inner = Table([[i] for i in items])
    inner.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return inner


def _data_table(header, rows, col_widths):
    data = [[Paragraph(h, S_TH) for h in header]] + [[Paragraph(str(c), S_TD) for c in r] for r in rows]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, RULE),
        ('BOX', (0, 0), (-1, -1), 0.6, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    for i in range(2, len(data), 2):
        style.append(('BACKGROUND', (0, i), (-1, i), SOFT))
    table.setStyle(TableStyle(style))
    return table


FIGURE_W = 152 * mm  # dois mapas A5 paisagem + legendas cabem numa página A4


def _figure(png_bytes, number, caption):
    width = FIGURE_W
    height = width * (148 / 210)  # mapas A5 paisagem
    img = RLImage(BytesIO(png_bytes), width=width, height=height)
    frame = Table([[img]], colWidths=[width])
    frame.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, RULE),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    frame.hAlign = 'CENTER'
    cap = Paragraph(f"<font name='{FONT_BOLD}' color='#1f4e3d'>Figura {number}</font> — {caption}", S_CAPTION)
    cap_box = Table([[cap]], colWidths=[width])
    cap_box.hAlign = 'CENTER'
    cap_box.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 3)]))
    return KeepTogether([frame, cap_box])


def _callout(text):
    box = Table([[Paragraph(text, S_BODY)]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SOFT),
        ('LINEBEFORE', (0, 0), (0, -1), 3, ACCENT),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return box


# ── Documento ─────────────────────────────────────────────────────────────────

def build_prodes_report(job, apontamento: dict, property_info: dict,
                         scene_before: dict, scene_after: dict,
                         map_before_png: bytes, map_after_png: bytes,
                         source_info: dict, footer_notes: list, ndvi: dict = None) -> bytes:
    """
    job: ProdesJob (ou objeto com atributo .id)
    apontamento: {class_name, year, area_total_ha, area_intersect_ha, image_date?}
    property_info: {cod_imovel, nome?, municipio, uf, area_ha, lat?, lon?}
    scene_before/scene_after: dicts de app.prodes_analysis (system_index, date,
        collection_id, cloud_pct, coverage_pct, label?, resolution_m?)
    source_info: {'label', 'queried_at'} — fonte PRODES/INPE consultada ao vivo (WFS)
    footer_notes: lista de strings (build_footer_notes)
    ndvi: {'before': float|None, 'after': float|None} — NDVI médio no apontamento
    """
    ndvi = ndvi or {}
    job_id = getattr(job, 'id', None)
    generated = datetime.utcnow()
    meta = {
        'doc_no': f"PRODES-{job_id:06d}" if isinstance(job_id, int) else 'PRODES-—',
        'generated': generated.strftime('%d/%m/%Y %H:%M UTC'),
        'cod_imovel': property_info.get('cod_imovel') or '—',
    }

    buf = BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, title="Laudo Técnico — Análise PRODES/INPE",
        author="AnalyticsBov", subject=f"CAR {meta['cod_imovel']}",
        leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
    )
    doc.meta = meta
    cover_frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W,
                        PAGE_H - COVER_BAND_H - 8 * mm - MARGIN_BOTTOM, id='cover')
    body_frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id='body')
    doc.addPageTemplates([
        PageTemplate(id='Cover', frames=[cover_frame], onPage=_draw_cover),
        PageTemplate(id='Body', frames=[body_frame], onPage=_draw_header),
    ])

    date_before = scene_before.get('date') if scene_before else None
    date_after = scene_after.get('date') if scene_after else None
    sensor_before = _scene(scene_before, 'label') if scene_before and scene_before.get('label') else _scene(scene_before, 'collection_id')
    sensor_after = _scene(scene_after, 'label') if scene_after and scene_after.get('label') else _scene(scene_after, 'collection_id')
    queried_at = (source_info or {}).get('queried_at')

    story = [NextPageTemplate('Body')]

    # 1. Identificação
    lat, lon = property_info.get('lat'), property_info.get('lon')
    coord = f"{_dms(lat, True)}  {_dms(lon, False)}<br/><font size='7' color='#5f6b66'>({_num(lat, 6)}, {_num(lon, 6)})</font>" \
        if lat is not None and lon is not None else '—'
    municipio = property_info.get('municipio')
    uf = property_info.get('uf')
    story += [
        _section(1, "Identificação do imóvel"),
        _kv_grid([
            ("Denominação informada", property_info.get('nome') or '—'),
            ("Código do CAR", meta['cod_imovel']),
            ("Município / UF", f"{municipio or '—'} / {uf or '—'}"),
            ("Área do imóvel (perímetro CAR)",
             f"{_num(property_info.get('area_ha'))} ha" if property_info.get('area_ha') else '—'),
            ("Coordenada de referência", coord),
            ("Status do perímetro", "Oficial (SICAR)"),
        ]),
        Spacer(1, 10),
    ]

    # 2. Apontamento
    story += [
        _section(2, "Apontamento PRODES analisado"),
        _kpi_row([
            ("Classe", apontamento.get('class_name') or '—', "base PRODES/INPE"),
            ("Ano", str(apontamento.get('year') or '—'),
             f"imagem INPE {_date(apontamento.get('image_date'))}" if apontamento.get('image_date') else None),
            ("Área total", f"{_num(apontamento.get('area_total_ha'))} ha", "polígono do apontamento"),
            ("Área no imóvel", f"{_num(apontamento.get('area_intersect_ha'))} ha", "interseção com o CAR"),
        ]),
        Spacer(1, 10),
    ]

    # 3. Resultado NDVI
    nb, na = ndvi.get('before'), ndvi.get('after')
    if nb is not None and na is not None and nb > 0:
        change = (na - nb) / nb * 100
        change_txt = f"{'+' if change >= 0 else '−'}{_num(abs(change), 0)}%"
        summary = (
            f"O NDVI médio dentro do apontamento (porção no imóvel) passou de <b>{_num(nb)}</b> "
            f"em {_date(date_before)} para <b>{_num(na)}</b> em {_date(date_after)}, "
            f"variação de <b>{change_txt}</b>. Valores próximos de 0 indicam solo exposto; "
            "valores acima de ~0,6 indicam vegetação densa."
        )
    else:
        change_txt = '—'
        summary = "O NDVI médio do apontamento não pôde ser calculado para uma das datas."
    story += [
        _section(3, "Evidência por NDVI"),
        _kpi_row([
            ("NDVI antes", _num(nb), _date(date_before)),
            ("NDVI depois", _num(na), _date(date_after)),
            ("Variação", change_txt, "depois × antes"),
        ]),
        Spacer(1, 6),
        _callout(summary),
        Spacer(1, 10),
    ]

    # 4. Metodologia
    story += [
        _section(4, "Metodologia"),
        Paragraph(
            "<b>Base de desmatamento.</b> Apontamentos PRODES consultados ao vivo no serviço WFS do "
            "TerraBrasilis/INPE (camadas de todos os biomas), em "
            f"{queried_at.strftime('%d/%m/%Y %H:%M UTC') if queried_at else '—'}, "
            "e cruzados com o perímetro oficial do imóvel no CAR. Áreas calculadas por método geodésico.",
            S_BODY),
        Spacer(1, 4),
        Paragraph(
            "<b>Seleção das cenas.</b> “Antes”: melhor cena na janela de 12 meses anterior a "
            "(data da imagem INPE − 12 meses). “Depois”: melhor cena nos 12 meses seguintes à data da "
            "imagem INPE. Prioridade para nuvem ≤ 5% sobre o imóvel (tolerância até 25%) e para a "
            "estação seca (jun–set), reduzindo o efeito sazonal na comparação.",
            S_BODY),
        Spacer(1, 4),
        Paragraph(
            "<b>NDVI.</b> Índice de vegetação por diferença normalizada, (NIR − Vermelho) / (NIR + Vermelho), "
            "sobre reflectância de superfície (Landsat Collection 2 nível 2 / Sentinel-2 nível 2A), "
            "com a mesma escala de cores fixa nas duas datas.",
            S_BODY),
        PageBreak(),
    ]

    # 5. Mapas
    story += [
        _section(5, "Mapas — antes e depois (NDVI)"),
        _figure(map_before_png, 1, f"Cena NDVI anterior ao apontamento — {_date(date_before)} ({sensor_before})."),
        Spacer(1, 8),
        _figure(map_after_png, 2, f"Cena NDVI posterior ao apontamento — {_date(date_after)} ({sensor_after})."),
        PageBreak(),
    ]

    # 6. Procedência
    def _res(scene):
        return f"{scene['resolution_m']} m" if scene and scene.get('resolution_m') else '—'
    story += [
        _section(6, "Procedência das cenas"),
        _data_table(
            ["", "Antes", "Depois"],
            [
                ["Data da cena", _date(date_before), _date(date_after)],
                ["Sensor", sensor_before, sensor_after],
                ["Resolução espacial", _res(scene_before), _res(scene_after)],
                ["Coleção (Google Earth Engine)", _scene(scene_before, 'collection_id'), _scene(scene_after, 'collection_id')],
                ["ID da cena", _scene(scene_before, 'system_index'), _scene(scene_after, 'system_index')],
                ["Nuvem sobre o imóvel", _scene(scene_before, 'cloud_pct', '{:.1f}%').replace('.', ','),
                 _scene(scene_after, 'cloud_pct', '{:.1f}%').replace('.', ',')],
                ["Cobertura do imóvel", _scene(scene_before, 'coverage_pct', '{:.1f}%').replace('.', ','),
                 _scene(scene_after, 'coverage_pct', '{:.1f}%').replace('.', ',')],
                ["NDVI médio no apontamento", _num(nb), _num(na)],
            ],
            [CONTENT_W * 0.32, CONTENT_W * 0.34, CONTENT_W * 0.34],
        ),
        Spacer(1, 12),
    ]

    # 7. Notas técnicas
    if footer_notes:
        story.append(_section(7, "Notas técnicas"))
        for i, note in enumerate(footer_notes, 1):
            story.append(Paragraph(f"<font name='{FONT_BOLD}' color='#1f4e3d'>{i}.</font> {note}", S_BODY))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 10))

    # 8. Fontes e responsabilidade
    story += [
        _section(8 if footer_notes else 7, "Fontes e responsabilidade"),
        _callout(
            "<b>Fontes:</b> PRODES/INPE (TerraBrasilis) · SICAR (perímetro do CAR) · USGS/NASA (Landsat) · "
            "Copernicus/ESA (Sentinel-2) · processamento via Google Earth Engine.<br/><br/>"
            "Este documento apresenta fatos técnicos verificáveis — datas e procedência das cenas, "
            "áreas medidas e índices de vegetação — e <b>não contém conclusão jurídica</b>. "
            "A interpretação para fins de defesa administrativa ou judicial cabe a profissional habilitado."
        ),
    ]

    doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(*a, doc_meta=meta, **kw))
    buf.seek(0)
    return buf.getvalue()
