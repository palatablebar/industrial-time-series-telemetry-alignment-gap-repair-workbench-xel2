"""Signal ownership timeline: registration, overlap checks and ts-based resolution.

Ownership rules (fixed semantics, mirrored by the front-end page):
  - a signal's ownership is a contiguous list of half-open segments
    ``[effective_from, effective_to)``; the last segment is open (``effective_to = NULL``);
  - samples are attributed by collection time: ``ts < effective_from`` stays with the
    previous device, ``ts >= effective_from`` belongs to the new device;
  - registration never rewrites ``raw_telemetry`` rows or stored run snapshots —
    history is never backfilled to the new device;
  - overlapping ownership is rejected with a 409 conflict.
"""
from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.error_codes import AppError, ErrorCode
from src.models import RawTelemetry, Signal, SignalOwnership, User
from src.utils.timeutil import from_epoch, iso, parse_iso, to_epoch

KIND_BASELINE = "baseline"
KIND_REASSIGN = "reassignment"


# --------------------------------------------------------------------------
# queries
# --------------------------------------------------------------------------
def segments_for(db: Session, signal_id: int) -> list[SignalOwnership]:
    return list(
        db.scalars(
            select(SignalOwnership)
            .where(SignalOwnership.signal_id == signal_id)
            .order_by(SignalOwnership.effective_from, SignalOwnership.id)
        )
    )


def _first_sample_ts(db: Session, signal_id: int) -> float | None:
    value = db.scalar(select(func.min(RawTelemetry.ts)).where(RawTelemetry.signal_id == signal_id))
    return float(value) if value is not None else None


def _count_samples(db: Session, signal_id: int, start: float, end: float | None) -> int:
    statement = select(func.count(RawTelemetry.id)).where(
        RawTelemetry.signal_id == signal_id,
        RawTelemetry.ts >= start,
    )
    if end is not None:
        statement = statement.where(RawTelemetry.ts < end)
    return int(db.scalar(statement) or 0)


def resolve_device(
    db: Session,
    signal: Signal,
    ts: float,
    cache: dict[int, list[SignalOwnership]] | None = None,
) -> tuple[str, str]:
    """Device owning ``signal`` at collection time ``ts`` (epoch seconds)."""
    segments = cache.get(signal.id) if cache is not None else None
    if segments is None:
        segments = segments_for(db, signal.id)
        if cache is not None:
            cache[signal.id] = segments
    for segment in reversed(segments):
        if segment.effective_from <= ts and (segment.effective_to is None or ts < segment.effective_to):
            return segment.device_code, segment.device_name
    return signal.device_code, signal.device_name


# --------------------------------------------------------------------------
# projections
# --------------------------------------------------------------------------
def segment_to_dict(db: Session, segment: SignalOwnership, with_count: bool = True) -> dict:
    creator = db.get(User, segment.created_by) if segment.created_by else None
    payload = {
        "id": segment.id,
        "signal_id": segment.signal_id,
        "kind": segment.kind,
        "device_code": segment.device_code,
        "device_name": segment.device_name,
        "effective_from": iso(from_epoch(segment.effective_from)),
        "effective_to": iso(from_epoch(segment.effective_to)) if segment.effective_to is not None else None,
        "note": segment.note or "",
        "created_by_name": creator.display_name if creator else None,
        "created_at": iso(segment.created_at),
    }
    if with_count:
        payload["sample_count"] = _count_samples(
            db, segment.signal_id, segment.effective_from, segment.effective_to
        )
    return payload


def timeline(db: Session, signal: Signal) -> dict:
    segments = segments_for(db, signal.id)
    open_segment = next((seg for seg in segments if seg.effective_to is None), None)
    current_code = open_segment.device_code if open_segment else signal.device_code
    current_name = open_segment.device_name if open_segment else signal.device_name
    return {
        "current": {"device_code": current_code, "device_name": current_name},
        "segments": [segment_to_dict(db, segment) for segment in segments],
    }


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------
def _conflict(message: str, segment: SignalOwnership) -> AppError:
    return AppError(
        ErrorCode.CONFLICT,
        message,
        status_code=409,
        detail={
            "conflict": {
                "segment_id": segment.id,
                "device_code": segment.device_code,
                "device_name": segment.device_name,
                "effective_from": iso(from_epoch(segment.effective_from)),
                "effective_to": iso(from_epoch(segment.effective_to))
                if segment.effective_to is not None
                else None,
            }
        },
    )


def _default_device_name(db: Session, device_code: str) -> str:
    """Reuse the catalogued device name when the tag moves to a known device."""
    return (
        db.scalar(
            select(Signal.device_name)
            .where(Signal.device_code == device_code, Signal.device_name != "")
            .limit(1)
        )
        or ""
    )


def register_reassignment(db: Session, signal: Signal, payload, user: User | None) -> dict:
    device_code = payload.device_code.strip()
    device_name = (payload.device_name or "").strip() or _default_device_name(db, payload.device_code.strip())
    note = (payload.note or "").strip()
    if not device_code:
        raise AppError(ErrorCode.VALIDATION_FAILED, "新设备编码不能为空", status_code=422)
    try:
        moment = to_epoch(parse_iso(payload.effective_from))
    except (ValueError, TypeError) as exc:
        raise AppError(ErrorCode.VALIDATION_FAILED, "生效时刻格式不合法", status_code=422) from exc

    segments = segments_for(db, signal.id)
    closed: SignalOwnership
    if not segments:
        # First registration: seal the pre-switch ownership as a baseline segment so
        # historical samples keep resolving to the original device.
        baseline_start = _first_sample_ts(db, signal.id)
        if baseline_start is None:
            baseline_start = to_epoch(signal.created_at) if signal.created_at else moment
        if moment <= baseline_start:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "生效时刻不晚于该测点首个已归档样本，登记会把全部历史样本划给新设备（历史数据不得回填）",
                status_code=422,
                detail={"first_sample_at": iso(from_epoch(baseline_start))},
            )
        if signal.device_code == device_code:
            raise AppError(
                ErrorCode.VALIDATION_FAILED, "新归属设备与当前归属相同，无需切换", status_code=422
            )
        closed = SignalOwnership(
            signal_id=signal.id,
            device_code=signal.device_code,
            device_name=signal.device_name,
            effective_from=baseline_start,
            effective_to=moment,
            kind=KIND_BASELINE,
            note="登记切换时自动封存的原始归属",
            created_by=user.id if user else None,
        )
        db.add(closed)
        db.flush()
    else:
        containing: SignalOwnership | None = None
        for segment in segments:
            if segment.effective_from == moment:
                raise _conflict(
                    f"该时刻已是归属切换点（{segment.device_code} 起生效），登记会造成归属重叠",
                    segment,
                )
            if segment.effective_from < moment and (
                segment.effective_to is None or moment < segment.effective_to
            ):
                containing = segment
                break
        if containing is None:
            earliest = segments[0]
            raise _conflict(
                "生效时刻不在任何既有归属区间内，无法与现有归属时间线衔接",
                earliest,
            )
        if containing.effective_to is not None:
            raise _conflict(
                f"生效时刻落在已封存的历史归属区间（{containing.device_code}）内，登记会造成归属重叠",
                containing,
            )
        if containing.device_code == device_code:
            raise AppError(
                ErrorCode.VALIDATION_FAILED, "新归属设备与当前归属相同，无需切换", status_code=422
            )
        containing.effective_to = moment
        closed = containing
        db.flush()

    # invariant guard: the new open segment [moment, +inf) must not overlap anything
    for segment in segments_for(db, signal.id):
        segment_to = segment.effective_to if segment.effective_to is not None else math.inf
        if segment_to > moment:
            raise _conflict(
                f"归属区间重叠：与既有区间（{segment.device_code}）冲突，登记已拒绝",
                segment,
            )

    segment = SignalOwnership(
        signal_id=signal.id,
        device_code=device_code,
        device_name=device_name,
        effective_from=moment,
        effective_to=None,
        kind=KIND_REASSIGN,
        note=note,
        created_by=user.id if user else None,
    )
    db.add(segment)
    # the signal row always reflects the *current* (open-segment) ownership
    signal.device_code = device_code
    signal.device_name = device_name
    db.commit()
    db.refresh(segment)

    return {
        "segment": segment_to_dict(db, segment),
        "closed_segment": segment_to_dict(db, closed),
        "affected_samples": _count_samples(db, signal.id, moment, None),
        "signal_id": signal.id,
    }


# --------------------------------------------------------------------------
# alignment integration: attribute already-loaded points by collection time
# --------------------------------------------------------------------------
def attribute_points(
    db: Session,
    signal: Signal,
    points: list[tuple[float, float, int]],
) -> list[tuple[str, str, list[tuple[float, float, int]]]]:
    """Split raw points into ``(device_code, device_name, points)`` chunks by ownership.

    Signals without any registered ownership keep their catalogued device; empty
    chunks are dropped so the alignment engine never sees a point-less input.
    """
    if not points:
        return []
    segments = segments_for(db, signal.id)
    if not segments:
        return [(signal.device_code, signal.device_name, points)]
    chunks: list[tuple[str, str, list[tuple[float, float, int]]]] = []
    assigned: list[bool] = [False] * len(points)
    for segment in segments:
        owned: list[tuple[float, float, int]] = []
        for index, point in enumerate(points):
            if segment.effective_from <= point[0] and (
                segment.effective_to is None or point[0] < segment.effective_to
            ):
                owned.append(point)
                assigned[index] = True
        if owned:
            chunks.append((segment.device_code, segment.device_name, owned))
    leftover = [point for index, point in enumerate(points) if not assigned[index]]
    if leftover:
        # points outside every segment (e.g. before the baseline start) keep the
        # signal's current device — they are never re-attributed to a new device
        chunks.insert(0, (signal.device_code, signal.device_name, leftover))
    return chunks
