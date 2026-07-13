"""Measurements: process values (e.g. NH4) with temperature and counter reading."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.measurement import Measurement
from app.models.user import User
from app.services.security import get_current_user, verify_csrf
from app.services.templating import flash, render

router = APIRouter(prefix="/measurements")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _combine_dt(raw: str, date_part: str, time_part: str) -> str:
    """Join separate date + time inputs; a full datetime string wins."""
    if raw:
        return raw
    if not date_part:
        return ""
    return f"{date_part}T{time_part}" if time_part else date_part


def _parameters(db: Session) -> list[str]:
    """Self-building parameter list, most recently used first (like activities)."""
    return list(
        db.scalars(
            select(Measurement.parameter)
            .group_by(Measurement.parameter)
            .order_by(func.max(Measurement.measured_at).desc())
        ).all()
    )


def _data_years(db: Session) -> list[int]:
    """Years covered by measurements, newest first, for the quick select."""
    first_dt = db.scalar(select(func.min(Measurement.measured_at)))
    first = first_dt.year if first_dt is not None else date.today().year
    return list(range(date.today().year, first - 1, -1))


@router.get("")
def list_measurements(
    request: Request,
    parameter: str | None = None,
    year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(Measurement)
        .options(selectinload(Measurement.user))
        .order_by(Measurement.measured_at.desc())
    )
    if parameter:
        stmt = stmt.where(Measurement.parameter == parameter)

    # Quick-select year wins over an explicit from/to range (like the report).
    selected_year = year if year and year.isdigit() else ""
    if selected_year:
        y = int(selected_year)
        df, dt_ = date(y, 1, 1), date(y, 12, 31)
    else:
        df, dt_ = _parse_date(date_from), _parse_date(date_to)
    if df:
        stmt = stmt.where(Measurement.measured_at >= datetime.combine(df, time.min, UTC))
    if dt_:
        stmt = stmt.where(Measurement.measured_at <= datetime.combine(dt_, time.max, UTC))

    measurements = list(db.scalars(stmt).all())
    return render(
        request,
        "measurements/list.html",
        {
            "measurements": measurements,
            "parameters": _parameters(db),
            "years": _data_years(db),
            "filters": {
                "parameter": parameter or "",
                "year": selected_year,
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
        db=db,
        user=user,
    )


@router.get("/new")
def new_measurement(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render(
        request,
        "measurements/form.html",
        {
            "measurement": None,
            "parameters": _parameters(db),
            "now": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        },
        db=db,
        user=user,
    )


def _render_form_error(
    request: Request,
    db: Session,
    user: User,
    measurement: Measurement | None,
    measured_at: str,
    form: dict,
):
    """Re-render the form with an error, keeping what the user typed."""
    return render(
        request,
        "measurements/form.html",
        {
            "measurement": measurement,
            "parameters": _parameters(db),
            "now": measured_at or datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "error": "measure.values_required",
            "form": form,
        },
        db=db,
        user=user,
        status_code=400,
    )


@router.post("/new")
def create_measurement(
    request: Request,
    csrf_token: str = Form(...),
    measured_at: str = Form(""),
    measured_date: str = Form(""),
    measured_time: str = Form(""),
    parameter: str = Form(...),
    value: str = Form(""),
    temperature: str = Form(""),
    operating_hours: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    measured_at = _combine_dt(measured_at, measured_date, measured_time)
    parameter = parameter.strip()
    value_f = _parse_float(value)
    temperature_f = _parse_float(temperature)
    operating_hours_f = _parse_float(operating_hours)
    if not parameter or value_f is None or temperature_f is None or operating_hours_f is None:
        form = {
            "parameter": parameter,
            "value": value,
            "temperature": temperature,
            "operating_hours": operating_hours,
        }
        return _render_form_error(request, db, user, None, measured_at, form)

    db.add(
        Measurement(
            measured_at=_parse_dt(measured_at) or datetime.now(UTC),
            user_id=user.id,
            parameter=parameter,
            value=value_f,
            temperature=temperature_f,
            operating_hours=operating_hours_f,
        )
    )
    db.commit()
    flash(request, "measure.saved")
    return RedirectResponse("/measurements", status_code=303)


@router.get("/{measurement_id}/edit")
def edit_measurement(
    measurement_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    measurement = db.get(Measurement, measurement_id)
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return render(
        request,
        "measurements/form.html",
        {
            "measurement": measurement,
            "parameters": _parameters(db),
            "now": measurement.measured_at.strftime("%Y-%m-%dT%H:%M"),
        },
        db=db,
        user=user,
    )


@router.post("/{measurement_id}/edit")
def update_measurement(
    measurement_id: int,
    request: Request,
    csrf_token: str = Form(...),
    measured_at: str = Form(""),
    measured_date: str = Form(""),
    measured_time: str = Form(""),
    parameter: str = Form(...),
    value: str = Form(""),
    temperature: str = Form(""),
    operating_hours: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    measured_at = _combine_dt(measured_at, measured_date, measured_time)
    measurement = db.get(Measurement, measurement_id)
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")

    parameter = parameter.strip()
    value_f = _parse_float(value)
    temperature_f = _parse_float(temperature)
    operating_hours_f = _parse_float(operating_hours)
    if not parameter or value_f is None or temperature_f is None or operating_hours_f is None:
        form = {
            "parameter": parameter,
            "value": value,
            "temperature": temperature,
            "operating_hours": operating_hours,
        }
        return _render_form_error(request, db, user, measurement, measured_at, form)

    measurement.measured_at = _parse_dt(measured_at) or measurement.measured_at
    measurement.parameter = parameter
    measurement.value = value_f
    measurement.temperature = temperature_f
    measurement.operating_hours = operating_hours_f
    db.commit()
    flash(request, "measure.saved")
    return RedirectResponse("/measurements", status_code=303)


@router.post("/{measurement_id}/delete")
def delete_measurement(
    measurement_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    measurement = db.get(Measurement, measurement_id)
    if measurement:
        db.delete(measurement)
        db.commit()
        flash(request, "measure.deleted")
    return RedirectResponse("/measurements", status_code=303)
