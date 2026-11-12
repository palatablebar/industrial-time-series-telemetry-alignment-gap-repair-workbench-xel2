"""Gap-event queries and analyst annotations."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.error_codes import AppError, ErrorCode
from src.models import AlignmentRun, GapEvent
from src.services import ownership_service
from src.utils.timeutil import iso, to_epoch


def _to_dict(db: Session, gap: GapEvent, run: AlignmentRun | None, ownership_cache: dict) -> dict:
    signal = gap.signal
    device_code = signal.device_code if signal else ""
    device_name = signal.device_name if signal else ""
    if signal is not None:
        # ownership is resolved at the gap's collection time: a tag re-wired to
        # another device keeps its historical gaps under the original device
        device_code, device_name = ownership_service.resolve_device(
            db, signal, to_epoch(gap.start_ts), ownership_cache
        )
    return {
        "id": gap.id,
        "run_id": gap.run_id,
        "run_name": run.job.name if run and run.job else "",
        "signal_code": signal.code if signal else "",
        "device_code": device_code,
        "device_name": device_name,
        "measure_name": signal.measure_name if signal else "",
        "unit": signal.unit if signal else "",
        "start_ts": iso(gap.start_ts),
        "end_ts": iso(gap.end_ts),
        "duration_s": gap.duration_s,
        "bucket_length": gap.bucket_length,
        "fill_strategy": gap.fill_strategy,
        "confidence": gap.confidence,
        "severity": gap.severity,
        "annotated": gap.annotated,
        "annotation": gap.annotation or "",
    }


def list_gaps(
    db: Session,
    run_id: int | None = None,
    severity: str | None = None,
    device_code: str | None = None,
) -> list[dict]:
    statement = select(GapEvent).order_by(GapEvent.start_ts, GapEvent.id)
    if run_id:
        statement = statement.where(GapEvent.run_id == run_id)
    if severity:
        statement = statement.where(GapEvent.severity == severity)
    gaps = list(db.scalars(statement))
    runs = {run.id: run for run in db.scalars(select(AlignmentRun))}
    ownership_cache: dict[int, list] = {}
    items = [_to_dict(db, gap, runs.get(gap.run_id), ownership_cache) for gap in gaps]
    if device_code:
        items = [item for item in items if item["device_code"] == device_code]
    return items


def annotate(db: Session, gap_id: int, text: str) -> GapEvent:
    gap = db.get(GapEvent, gap_id)
    if gap is None:
        raise AppError(ErrorCode.NOT_FOUND, "缺口事件不存在", status_code=404)
    gap.annotation = text.strip()
    gap.annotated = True
    db.commit()
    db.refresh(gap)
    return gap
