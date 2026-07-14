"""Helpers around measurement parameter configuration (units + thresholds)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.measurement_parameter import MeasurementParameter


def parameter_config_map(db: Session) -> dict[str, MeasurementParameter]:
    """Map parameter name -> its config row (unit / thresholds), if any."""
    return {p.name: p for p in db.scalars(select(MeasurementParameter)).all()}
