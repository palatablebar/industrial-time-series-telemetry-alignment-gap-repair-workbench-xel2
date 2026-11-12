from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config.database import Base


class SignalOwnership(Base):
    """Time-bounded ownership of a signal (which device a tag belongs to).

    Intervals are half-open ``[effective_from, effective_to)`` in epoch seconds;
    a NULL ``effective_to`` marks the currently open segment. Ownership is
    resolved by collection time, so historical samples keep their original
    device and raw rows are never rewritten.
    """

    __tablename__ = "signal_ownership"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal.id"), nullable=False, index=True)
    device_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(80), default="")
    effective_from: Mapped[float] = mapped_column(Float, nullable=False)
    effective_to: Mapped[float | None] = mapped_column(Float, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="reassignment")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    signal = relationship("Signal", lazy="joined")
