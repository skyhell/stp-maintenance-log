"""Measurements: process values (e.g. NH4) with temperature and counter reading."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
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


def _parameters(db: Session) -> list[str]:
    """Distinct parameter names for the self-building dropdown/datalist."""
    return list(
        db.scalars(
            select(Measurement.parameter).distinct().order_by(Measurement.parameter)
        ).all()
    )


@router.get("")
def list_measurements(
    request: Request,
    parameter: str | None = None,
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
    measurements = list(db.scalars(stmt).all())
    return render(
        request,
        "measurements/list.html",
        {
            "measurements": measurements,
            "parameters": _parameters(db),
            "filter_parameter": parameter or "",
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


@router.post("/new")
def create_measurement(
    request: Request,
    csrf_token: str = Form(...),
    measured_at: str = Form(""),
    parameter: str = Form(...),
    value: str = Form(""),
    temperature: str = Form(""),
    operating_hours: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    parameter = parameter.strip()
    if not parameter:
        return RedirectResponse("/measurements/new", status_code=303)

    db.add(
        Measurement(
            measured_at=_parse_dt(measured_at) or datetime.now(UTC),
            user_id=user.id,
            parameter=parameter,
            value=_parse_float(value),
            temperature=_parse_float(temperature),
            operating_hours=_parse_float(operating_hours),
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
    parameter: str = Form(...),
    value: str = Form(""),
    temperature: str = Form(""),
    operating_hours: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    measurement = db.get(Measurement, measurement_id)
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement not found")

    measurement.measured_at = _parse_dt(measured_at) or measurement.measured_at
    measurement.parameter = parameter.strip() or measurement.parameter
    measurement.value = _parse_float(value)
    measurement.temperature = _parse_float(temperature)
    measurement.operating_hours = _parse_float(operating_hours)
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
