"""
Geração do PDF ("laudo") da ferramenta PRODES via reportlab — não existia
biblioteca de PDF no projeto antes disso. Um documento por apontamento
analisado, com identificação do imóvel, quadro de áreas, os dois mapas
(antes/depois) e a procedência das cenas. Ver prompt_ferramenta_prodes_bot.md,
seção "O PDF".
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
)


def _fmt_scene_field(scene: dict, field: str, fmt: str = '{}') -> str:
    if not scene:
        return '—'
    value = scene.get(field)
    if value is None:
        return '—'
    return fmt.format(value)


def build_prodes_report(job, apontamento: dict, property_info: dict,
                         scene_before: dict, scene_after: dict,
                         map_before_png: bytes, map_after_png: bytes,
                         source_info: dict, footer_notes: list) -> bytes:
    """
    job: ProdesJob (ou objeto com atributo .id)
    apontamento: {class_name, year, area_total_ha, area_intersect_ha}
    property_info: {cod_imovel, municipio, uf, area_ha}
    scene_before/scene_after: dicts de app.prodes_analysis (system_index, date,
        collection_id, cloud_pct, coverage_pct)
    source_info: {'label', 'queried_at'} — fonte PRODES/INPE consultada ao vivo (WFS)
    footer_notes: lista de strings (build_footer_notes)
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('PRODESTitle', parent=styles['Title'], fontSize=15)
    h2_style = ParagraphStyle('PRODESH2', parent=styles['Heading2'], fontSize=11,
                               spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle('PRODESBody', parent=styles['BodyText'], fontSize=9, leading=12)
    note_style = ParagraphStyle('PRODESNote', parent=styles['BodyText'], fontSize=7.5, leading=10,
                                 textColor=colors.HexColor('#444444'))

    source_label = (source_info or {}).get('label') or 'TerraBrasilis/INPE'
    queried_at = (source_info or {}).get('queried_at')
    queried_str = queried_at.strftime('%d/%m/%Y %H:%M UTC') if queried_at else '—'

    story = []
    story.append(Paragraph("Relatório de Análise PRODES", title_style))
    story.append(Paragraph(
        f"Job #{getattr(job, 'id', '—')} &nbsp;|&nbsp; Fonte: {source_label} "
        f"&nbsp;|&nbsp; Consultado em {queried_str} &nbsp;|&nbsp; Gerado em "
        f"{datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}",
        body_style,
    ))
    story.append(Spacer(1, 8))

    # ── Identificação do imóvel ──────────────────────────────────────────────
    story.append(Paragraph("Identificação do imóvel", h2_style))
    area_ha = property_info.get('area_ha')
    id_rows = [
        ["CAR", property_info.get('cod_imovel') or '—'],
        ["Município/UF", f"{property_info.get('municipio') or '—'} / {property_info.get('uf') or '—'}"],
        ["Área do imóvel", f"{area_ha:.2f} ha" if area_ha else '—'],
    ]
    id_table = Table(id_rows, colWidths=[110, 300])
    id_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
    ]))
    story.append(id_table)

    # ── Quadro de áreas ──────────────────────────────────────────────────────
    story.append(Paragraph("Quadro de áreas do apontamento", h2_style))
    area_rows = [
        ["Classe", "Ano", "Área total (ha)", "Área no imóvel (ha)"],
        [
            apontamento.get('class_name', '—'), str(apontamento.get('year', '—')),
            f"{apontamento.get('area_total_ha', 0):.2f}", f"{apontamento.get('area_intersect_ha', 0):.2f}",
        ],
    ]
    area_table = Table(area_rows, colWidths=[100, 60, 130, 130])
    area_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(area_table)
    story.append(Spacer(1, 10))

    # ── Mapas ────────────────────────────────────────────────────────────────
    map_width = 165 * mm
    map_height = map_width * (148 / 210)
    story.append(Paragraph("Mapa — cena ANTES", h2_style))
    story.append(RLImage(BytesIO(map_before_png), width=map_width, height=map_height))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Mapa — cena DEPOIS", h2_style))
    story.append(RLImage(BytesIO(map_after_png), width=map_width, height=map_height))
    story.append(Spacer(1, 10))

    # ── Procedência das cenas ───────────────────────────────────────────────
    story.append(Paragraph("Procedência das cenas", h2_style))
    date_before = scene_before['date'].strftime('%d/%m/%Y') if scene_before and scene_before.get('date') else '—'
    date_after = scene_after['date'].strftime('%d/%m/%Y') if scene_after and scene_after.get('date') else '—'
    prov_rows = [
        ["", "Antes", "Depois"],
        ["ID da cena", _fmt_scene_field(scene_before, 'system_index'), _fmt_scene_field(scene_after, 'system_index')],
        ["Data", date_before, date_after],
        ["Coleção", _fmt_scene_field(scene_before, 'collection_id'), _fmt_scene_field(scene_after, 'collection_id')],
        ["Nuvem sobre o imóvel", _fmt_scene_field(scene_before, 'cloud_pct', '{:.1f}%'),
         _fmt_scene_field(scene_after, 'cloud_pct', '{:.1f}%')],
        ["Cobertura do imóvel", _fmt_scene_field(scene_before, 'coverage_pct', '{:.1f}%'),
         _fmt_scene_field(scene_after, 'coverage_pct', '{:.1f}%')],
    ]
    prov_table = Table(prov_rows, colWidths=[130, 140, 140])
    prov_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
    ]))
    story.append(prov_table)
    story.append(Spacer(1, 10))

    # ── Notas ────────────────────────────────────────────────────────────────
    if footer_notes:
        story.append(Paragraph("Notas", h2_style))
        for note in footer_notes:
            story.append(Paragraph(note, note_style))
        story.append(Spacer(1, 8))

    story.append(Paragraph(
        "Fontes: PRODES/INPE · USGS/NASA (Landsat) · Copernicus/ESA (Sentinel-2). "
        "Este documento apresenta fatos técnicos (datas de cena, procedência, áreas medidas) "
        "e não contém conclusão jurídica.",
        note_style,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
