"""Full plant report: entries, measurements and asset changes as one PDF."""

from __future__ import annotations

import io
import json
from datetime import datetime

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

from app.models.asset_event import AssetEvent
from app.models.maintenance import MaintenanceEntry
from app.models.measurement import Measurement
from app.services.i18n import Translator


def _p(text: str, style) -> Paragraph:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe.replace("\n", "<br/>"), style)


def _entry_details(e: MaintenanceEntry, t: Translator) -> str:
    lines = []
    head = []
    if e.activity:
        head.append(e.activity.name)
    if e.asset:
        head.append(f"{e.asset.name} ({e.asset.uid})")
    if head:
        lines.append(" · ".join(head))
    if e.description:
        lines.append(e.description)
    if e.notes:
        lines.append(f"{t('entry.notes')}: {e.notes}")
    if e.comment:
        lines.append(f"{t('entry.comment')}: {e.comment}")
    if e.operating_hours is not None:
        lines.append(f"{t('entry.operating_hours')}: {e.operating_hours} h")
    if e.images:
        lines.append(f"{t('entry.images')}: {len(e.images)}")
    return "\n".join(lines) or "—"


def _measurement_details(m: Measurement, t: Translator) -> str:
    parts = [f"{m.parameter}: {m.value}"]
    if m.temperature is not None:
        parts.append(f"{t('measure.temperature')}: {m.temperature}")
    if m.operating_hours is not None:
        parts.append(f"{t('measure.operating_hours')}: {m.operating_hours} h")
    return " · ".join(parts)


def _event_details(ev: AssetEvent, t: Translator) -> str:
    lines = [
        f"{ev.asset_name} ({ev.asset_uid}) — {t('report.action.' + ev.action.value)}"
    ]
    if ev.changes:
        for label_key, old, new in json.loads(ev.changes):
            lines.append(f"{t(label_key)}: {old} → {new}")
    return "\n".join(lines)


def build_plant_report(
    plant_name: str,
    entries: list[MaintenanceEntry],
    measurements: list[Measurement],
    events: list[AssetEvent],
    t: Translator,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=t("report.title"),
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

    # One chronological stream (oldest first) across all three sources.
    rows: list[tuple[datetime, str, str, str]] = []
    for e in entries:
        rows.append(
            (
                e.occurred_at,
                t("report.type.entry"),
                e.user.username if e.user else "—",
                _entry_details(e, t),
            )
        )
    for m in measurements:
        rows.append(
            (
                m.measured_at,
                t("report.type.measurement"),
                m.user.username if m.user else "—",
                _measurement_details(m, t),
            )
        )
    for ev in events:
        rows.append(
            (
                ev.occurred_at,
                t("report.type.asset"),
                ev.user.username if ev.user else "—",
                _event_details(ev, t),
            )
        )
    rows.sort(key=lambda r: (r[0].replace(tzinfo=None) if r[0].tzinfo else r[0]))

    story = [Paragraph(f"{t('report.title')} — {plant_name}", title_style)]
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(
        Paragraph(
            f"{t('report.generated')}: {generated} &nbsp;·&nbsp; "
            f"{t('report.events')}: {len(rows)}",
            sub_style,
        )
    )
    story.append(Spacer(1, 8))

    data = [
        [
            _p(t("entry.datetime"), head),
            _p(t("report.type"), head),
            _p(t("report.user"), head),
            _p(t("report.details"), head),
        ]
    ]
    for occurred, type_label, username, details in rows:
        data.append(
            [
                _p(occurred.strftime("%d/%m/%Y %H:%M"), cell),
                _p(type_label, cell),
                _p(username, cell),
                _p(details, cell),
            ]
        )

    col_widths = [28 * mm, 24 * mm, 28 * mm, 170 * mm]
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

    if not rows:
        story.append(Spacer(1, 20))
        story.append(Paragraph(t("report.empty"), sub_style))

    doc.build(story)
    return buf.getvalue()
