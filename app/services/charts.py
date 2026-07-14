"""Server-rendered SVG line charts for measurement trends.

One chart per parameter (single series), styled via the app's CSS variables so
light and dark mode both work; each point carries a native tooltip and the
data table below the charts is the accessible view.
"""

from __future__ import annotations

from datetime import datetime

_W, _H = 560, 200
_M_LEFT, _M_RIGHT, _M_TOP, _M_BOTTOM = 46, 14, 14, 26


def _esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def line_chart_svg(
    points: list[tuple[datetime, float]],
    label: str,
    unit: str | None = None,
    lo: float | None = None,
    hi: float | None = None,
) -> str:
    """Render a single-series line chart; expects >= 2 points sorted by time.

    ``unit`` is shown on the y-axis; ``lo``/``hi`` draw dashed warning-threshold
    reference lines and any point outside [lo, hi] is coloured as a breach.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    # Include thresholds in the y-domain so their reference lines are visible.
    domain = list(ys)
    for ref in (lo, hi):
        if ref is not None:
            domain.append(ref)
    y_min, y_max = min(domain), max(domain)
    if y_min == y_max:  # flat series: give the line room
        y_min -= 1.0
        y_max += 1.0
    pad = (y_max - y_min) * 0.1
    y_min -= pad
    y_max += pad

    def _breach(v: float) -> bool:
        return (lo is not None and v < lo) or (hi is not None and v > hi)

    t0, t1 = xs[0], xs[-1]
    span = (t1 - t0).total_seconds() or 1.0
    plot_w = _W - _M_LEFT - _M_RIGHT
    plot_h = _H - _M_TOP - _M_BOTTOM

    def sx(t: datetime) -> float:
        return _M_LEFT + plot_w * ((t - t0).total_seconds() / span)

    def sy(v: float) -> float:
        return _M_TOP + plot_h * (1 - (v - y_min) / (y_max - y_min))

    parts = [
        f'<svg viewBox="0 0 {_W} {_H}" role="img" aria-label="{_esc(label)}" '
        f'data-axis-x="{_M_LEFT}" data-axis-y="{_H - _M_BOTTOM}" '
        f'style="width:100%; height:auto; display:block;">'
    ]

    # Recessive horizontal gridlines with y tick labels.
    for i in range(4):
        v = y_min + (y_max - y_min) * i / 3
        y = sy(v)
        parts.append(
            f'<line x1="{_M_LEFT}" y1="{y:.1f}" x2="{_W - _M_RIGHT}" y2="{y:.1f}" '
            f'stroke="var(--border)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_M_LEFT - 6}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'fill="var(--text-muted)" font-size="10">{_fmt_num(v)}</text>'
        )

    # Unit label in the top-left corner of the y-axis.
    if unit:
        parts.append(
            f'<text x="4" y="{_M_TOP - 2:.1f}" text-anchor="start" '
            f'fill="var(--text-muted)" font-size="10">{_esc(unit)}</text>'
        )

    # Dashed warning-threshold reference lines.
    for ref, name in ((lo, "min"), (hi, "max")):
        if ref is None:
            continue
        y = sy(ref)
        parts.append(
            f'<line x1="{_M_LEFT}" y1="{y:.1f}" x2="{_W - _M_RIGHT}" y2="{y:.1f}" '
            f'stroke="var(--danger)" stroke-width="1" stroke-dasharray="4 3" '
            f'opacity="0.7"/>'
        )
        parts.append(
            f'<text x="{_W - _M_RIGHT}" y="{y - 3:.1f}" text-anchor="end" '
            f'fill="var(--danger)" font-size="9">{name} {_fmt_num(ref)}</text>'
        )

    # X labels: first and last date.
    for t, anchor in ((t0, "start"), (t1, "end")):
        x = sx(t)
        parts.append(
            f'<text x="{x:.1f}" y="{_H - 8}" text-anchor="{anchor}" '
            f'fill="var(--text-muted)" font-size="10">{t.strftime("%d/%m/%Y")}</text>'
        )

    # The line itself.
    coords = " ".join(f"{sx(t):.1f},{sy(v):.1f}" for t, v in points)
    parts.append(
        f'<polyline points="{coords}" fill="none" stroke="var(--accent)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # Points with native tooltips (large invisible hit target behind each dot);
    # points outside the threshold band are coloured as a breach.
    for t, v in points:
        x, y = sx(t), sy(v)
        colour = "var(--danger)" if _breach(v) else "var(--accent)"
        date_label = t.strftime("%d/%m/%Y %H:%M")
        val_label = f"{_fmt_num(v)}{(' ' + unit) if unit else ''}"
        tip = f"{date_label} · {val_label}"
        parts.append(
            f'<g class="pt" data-cx="{x:.1f}" data-cy="{y:.1f}" '
            f'data-date="{_esc(date_label)}" data-value="{_esc(val_label)}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="transparent"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colour}"/>'
            f"<title>{_esc(tip)}</title></g>"
        )

    # Direct label on the last value only.
    lx, ly = sx(t1), sy(ys[-1])
    last_colour = "var(--danger)" if _breach(ys[-1]) else "var(--text)"
    parts.append(
        f'<text x="{min(lx, _W - _M_RIGHT - 2):.1f}" y="{max(ly - 8, 10):.1f}" '
        f'text-anchor="end" fill="{last_colour}" font-size="11" font-weight="600">'
        f"{_fmt_num(ys[-1])}</text>"
    )

    parts.append("</svg>")
    return "".join(parts)
