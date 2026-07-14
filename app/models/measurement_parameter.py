"""Per-parameter configuration: display unit and warning thresholds.

The parameter name mirrors ``Measurement.parameter`` (the self-building list);
a config row is optional and only exists once a unit or threshold is set.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MeasurementParameter(Base):
    __tablename__ = "measurement_parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Inclusive warning band: a value below min or above max is "out of range".
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    def out_of_range(self, value: float | None) -> bool:
        if value is None:
            return False
        if self.min_value is not None and value < self.min_value:
            return True
        if self.max_value is not None and value > self.max_value:
            return True
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MeasurementParameter {self.name} [{self.min_value},{self.max_value}]>"
