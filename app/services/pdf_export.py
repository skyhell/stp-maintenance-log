"""PDF export of the maintenance history for a date range (ReportLab)."""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.maintenance import MaintenanceEntry
from app.services.i18n import Translator


def _p(text: str, style) -> Paragraph:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe.replace("\n", "<br/>"), style)


def build_history_pdf(
    entries: list[MaintenanceEntry],
    t: Translator,
    date_from: date | None,
    date_to: date | None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=t("app.title"),
    )

    styles = getSampleStyleSheet()
    cell = ParagraphStyle(
        "cell", parent=styles["Normal"], fontSize=8, leading=10, alignment=TA_LEFT
    )
    head = ParagraphStyle("head", parent=cell, textColor=colors.white, fontSize=8)
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=16, spaceAfter=4
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey
    )

    story = []
    story.append(Paragraph(t("app.title"), title_style))

    rng = []
    if date_from:
        rng.append(f"{t('entry.filter_from')}: {date_from.isoformat()}")
    if date_to:
        rng.append(f"{t('entry.filter_to')}: {date_to.isoformat()}")
    rng.append(f"{t('dashboard.total_entries')}: {len(entries)}")
    story.append(Paragraph(" &nbsp;·&nbsp; ".join(rng), sub_style))
    story.append(Spacer(1, 8))

    header = [
        _p(t("entry.datetime"), head),
        _p(t("entry.user"), head),
        _p(t("entry.activity"), head),
        _p(t("entry.asset"), head),
        _p(t("entry.description"), head),
        _p(t("entry.images"), head),
    ]
    data = [header]

    for e in entries:
        details = []
        if e.description:
            details.append(e.description)
        if e.notes:
            details.append(f"📝 {e.notes}")
        if e.comment:
            details.append(f"💬 {e.comment}")
        asset_txt = ""
        if e.asset:
            asset_txt = f"{e.asset.name} ({e.asset.uid})"
        data.append(
            [
                _p(e.occurred_at.strftime("%Y-%m-%d %H:%M"), cell),
                _p(e.user.username if e.user else "—", cell),
                _p(e.activity.name if e.activity else "—", cell),
                _p(asset_txt or "—", cell),
                _p("\n".join(details) or "—", cell),
                _p(str(len(e.images)) if e.images else "—", cell),
            ]
        )

    # Column widths tuned for landscape A4 (~269mm usable).
    col_widths = [26 * mm, 24 * mm, 34 * mm, 42 * mm, 110 * mm, 14 * mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0071e3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d0d5")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f7")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)

    if not entries:
        story.append(Spacer(1, 20))
        story.append(Paragraph(t("entry.no_entries"), sub_style))

    doc.build(story)
    return buf.getvalue()
