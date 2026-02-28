"""
Maschinenpflege — Wartungsintervalle & Ausführungsdokumentation
"""
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import (
    User, Machine, MaintenanceInterval, MaintenanceRecord, LogType
)
from app.services.auth import get_current_user
from app.services import logger as log_svc
from app.config import APP_TIMEZONE

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _local_iso(dt):
    if dt is None:
        return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()


# ── Pydantic-Schemas ──────────────────────────────────────────────────────────

class IntervalCreate(BaseModel):
    machine_id:     int
    name:           str
    description:    Optional[str] = None
    interval_hours: Optional[float] = None
    interval_days:  Optional[int] = None
    warning_hours:  Optional[float] = None
    warning_days:   Optional[int] = None

class IntervalUpdate(BaseModel):
    name:           Optional[str] = None
    description:    Optional[str] = None
    interval_hours: Optional[float] = None
    interval_days:  Optional[int] = None
    warning_hours:  Optional[float] = None
    warning_days:   Optional[int] = None
    is_active:      Optional[bool] = None

class RecordCreate(BaseModel):
    interval_id:  Optional[int] = None   # None = freie Wartungsdokumentation
    machine_id:   Optional[int] = None   # Pflicht wenn kein interval_id
    name:         Optional[str] = None   # Bezeichnung bei freier Dokumentation
    notes:        Optional[str] = None
    performed_at: Optional[str] = None   # ISO-String, Default: jetzt


# ── Hilfsfunktion: Status eines Intervalls berechnen ─────────────────────────

def _interval_status(
    interval: MaintenanceInterval,
    machine_total_hours: float,
    last_record: Optional[MaintenanceRecord],
) -> dict:
    """
    Gibt den Fälligkeits-Status eines Intervalls zurück.
    Nullpunkt ist immer die letzte Wartung (oder Intervall-Erstellung falls noch keine).
    """
    now = datetime.utcnow()

    # Nullpunkt
    base_hours = last_record.hours_at_execution if last_record else 0.0
    base_time  = last_record.performed_at        if last_record else interval.created_at

    hours_since = (machine_total_hours or 0.0) - (base_hours or 0.0)
    days_since  = (now - base_time).total_seconds() / 86400

    # Fälligkeit berechnen (je aktives Kriterium)
    due_hours = False
    due_days  = False
    warn_hours = False
    warn_days  = False

    if interval.interval_hours:
        remaining_h = interval.interval_hours - hours_since
        due_hours  = remaining_h <= 0
        warn_hours = (not due_hours) and interval.warning_hours is not None and remaining_h <= interval.warning_hours

    if interval.interval_days:
        remaining_d = interval.interval_days - days_since
        due_days  = remaining_d <= 0
        warn_days = (not due_days) and interval.warning_days is not None and remaining_d <= interval.warning_days

    is_due     = due_hours or due_days
    is_warning = (not is_due) and (warn_hours or warn_days)

    # Übersichtliche Restangaben
    remaining_hours_val = None
    remaining_days_val  = None
    if interval.interval_hours:
        remaining_hours_val = round(interval.interval_hours - hours_since, 2)
    if interval.interval_days:
        remaining_days_val = round(interval.interval_days - days_since, 1)

    return {
        "status":              "due" if is_due else ("warning" if is_warning else "ok"),
        "is_due":              is_due,
        "is_warning":          is_warning,
        "hours_since":         round(hours_since, 2),
        "days_since":          round(days_since, 1),
        "remaining_hours":     remaining_hours_val,
        "remaining_days":      remaining_days_val,
        "last_performed_at":   _local_iso(last_record.performed_at) if last_record else None,
        "last_performer_name": None,   # wird im Endpoint befüllt
    }


def _interval_out(
    interval: MaintenanceInterval,
    machine_total_hours: float,
    last_record: Optional[MaintenanceRecord],
    performer_name: Optional[str],
) -> dict:
    status = _interval_status(interval, machine_total_hours, last_record)
    status["last_performer_name"] = performer_name
    return {
        "id":             interval.id,
        "machine_id":     interval.machine_id,
        "name":           interval.name,
        "description":    interval.description,
        "interval_hours": interval.interval_hours,
        "interval_days":  interval.interval_days,
        "warning_hours":  interval.warning_hours,
        "warning_days":   interval.warning_days,
        "is_active":      interval.is_active,
        "created_at":     _local_iso(interval.created_at),
        **status,
    }


# ── Endpoints: Intervalle ─────────────────────────────────────────────────────

@router.get("/intervals")
async def list_intervals(
    machine_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Alle Intervalle, optional nach Maschine gefiltert."""
    q = select(MaintenanceInterval)
    if machine_id:
        q = q.where(MaintenanceInterval.machine_id == machine_id)
    q = q.order_by(MaintenanceInterval.machine_id, MaintenanceInterval.name)
    intervals = (await db.execute(q)).scalars().all()

    # Maschinen + letzter Record + Ausführender laden
    machines  = {m.id: m for m in (await db.execute(select(Machine))).scalars().all()}
    users     = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    result = []
    for iv in intervals:
        machine = machines.get(iv.machine_id)
        total_h = machine.total_hours if machine else 0.0

        last = (await db.execute(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.interval_id == iv.id)
            .order_by(MaintenanceRecord.performed_at.desc())
            .limit(1)
        )).scalars().first()

        performer = users.get(last.performed_by) if last and last.performed_by else None
        out = _interval_out(iv, total_h, last, performer)
        out["machine_name"] = machine.name if machine else "?"
        result.append(out)

    return result


@router.post("/intervals")
async def create_interval(
    payload: IntervalCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not payload.interval_hours and not payload.interval_days:
        raise HTTPException(400, "Mindestens interval_hours oder interval_days muss angegeben sein")

    machine = await db.get(Machine, payload.machine_id)
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    iv = MaintenanceInterval(**payload.model_dump())
    db.add(iv)
    await db.commit()
    await db.refresh(iv)

    await log_svc.log(
        db, LogType.maintenance_done,
        f"Wartungsintervall erstellt: «{iv.name}» für {machine.name}",
        machine_id=machine.id, user_id=current.id,
    )

    return _interval_out(iv, machine.total_hours, None, None)


@router.patch("/intervals/{interval_id}")
async def update_interval(
    interval_id: int,
    payload: IntervalUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    iv = await db.get(MaintenanceInterval, interval_id)
    if not iv:
        raise HTTPException(404, "Intervall nicht gefunden")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(iv, field, value)
    await db.commit()
    await db.refresh(iv)

    machine = await db.get(Machine, iv.machine_id)
    last = (await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.interval_id == iv.id)
        .order_by(MaintenanceRecord.performed_at.desc()).limit(1)
    )).scalars().first()

    return _interval_out(iv, machine.total_hours if machine else 0.0, last, None)


@router.delete("/intervals/{interval_id}")
async def delete_interval(
    interval_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    iv = await db.get(MaintenanceInterval, interval_id)
    if not iv:
        raise HTTPException(404, "Intervall nicht gefunden")
    machine = await db.get(Machine, iv.machine_id)
    await db.delete(iv)
    await db.commit()
    await log_svc.log(
        db, LogType.maintenance_done,
        f"Wartungsintervall gelöscht: «{iv.name}»" + (f" von {machine.name}" if machine else ""),
        machine_id=iv.machine_id, user_id=current.id,
    )
    return {"ok": True}


# ── Endpoints: Ausführungen ───────────────────────────────────────────────────

@router.post("/records")
async def create_record(
    payload: RecordCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Wartung dokumentieren — mit oder ohne Intervall-Referenz."""
    iv = None
    if payload.interval_id:
        iv = await db.get(MaintenanceInterval, payload.interval_id)
        if not iv:
            raise HTTPException(404, "Intervall nicht gefunden")
        machine = await db.get(Machine, iv.machine_id)
    else:
        # Freie Dokumentation: machine_id und name Pflicht
        if not payload.machine_id:
            raise HTTPException(400, "machine_id erforderlich wenn kein interval_id angegeben")
        if not payload.name:
            raise HTTPException(400, "name erforderlich wenn kein interval_id angegeben")
        machine = await db.get(Machine, payload.machine_id)

    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    performed_at = datetime.utcnow()
    if payload.performed_at:
        try:
            performed_at = datetime.fromisoformat(payload.performed_at)
        except ValueError:
            raise HTTPException(400, "Ungültiges Datum (ISO-Format erwartet)")

    record_name = iv.name if iv else payload.name
    record = MaintenanceRecord(
        interval_id=iv.id if iv else None,
        machine_id=machine.id,
        performed_by=current.id,
        performed_at=performed_at,
        hours_at_execution=machine.total_hours,
        notes=payload.notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    await log_svc.log(
        db, LogType.maintenance_done,
        f"Wartung dokumentiert: «{record_name}» an {machine.name} — {machine.total_hours:.1f} h",
        machine_id=machine.id, user_id=current.id,
        meta={"interval_id": iv.id if iv else None, "hours": machine.total_hours, "notes": payload.notes},
    )

    return {
        "id":                 record.id,
        "interval_id":        record.interval_id,
        "interval_name":      record_name,
        "machine_id":         record.machine_id,
        "performed_by":       record.performed_by,
        "performer_name":     current.name,
        "performed_at":       _local_iso(record.performed_at),
        "hours_at_execution": record.hours_at_execution,
        "notes":              record.notes,
    }


@router.get("/records")
async def list_records(
    interval_id: Optional[int] = None,
    machine_id:  Optional[int] = None,
    limit:       int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Wartungshistorie — nach Intervall oder Maschine filterbar."""
    q = select(MaintenanceRecord).order_by(MaintenanceRecord.performed_at.desc()).limit(limit)
    if interval_id:
        q = q.where(MaintenanceRecord.interval_id == interval_id)
    if machine_id:
        q = q.where(MaintenanceRecord.machine_id == machine_id)

    records = (await db.execute(q)).scalars().all()
    users    = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}
    machines = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    intervals = {iv.id: iv.name for iv in (await db.execute(select(MaintenanceInterval))).scalars().all()}

    return [{
        "id":                 r.id,
        "interval_id":        r.interval_id,
        "interval_name":      intervals.get(r.interval_id, "Freie Wartung"),
        "machine_id":         r.machine_id,
        "machine_name":       machines.get(r.machine_id, "?"),
        "performed_by":       r.performed_by,
        "performer_name":     users.get(r.performed_by, "?") if r.performed_by else "—",
        "performed_at":       _local_iso(r.performed_at),
        "hours_at_execution": r.hours_at_execution,
        "notes":              r.notes,
    } for r in records]


# ── Dashboard-Übersicht: alle fälligen/warnenden Intervalle ──────────────────

@router.get("/overview")
async def maintenance_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Gibt alle aktiven Intervalle zurück, sortiert nach Dringlichkeit:
    due → warning → ok
    """
    intervals = (await db.execute(
        select(MaintenanceInterval).where(MaintenanceInterval.is_active == True)
    )).scalars().all()

    machines  = {m.id: m for m in (await db.execute(select(Machine))).scalars().all()}
    users     = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    result = []
    for iv in intervals:
        machine = machines.get(iv.machine_id)
        if not machine:
            continue
        last = (await db.execute(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.interval_id == iv.id)
            .order_by(MaintenanceRecord.performed_at.desc()).limit(1)
        )).scalars().first()

        performer = users.get(last.performed_by) if last and last.performed_by else None
        out = _interval_out(iv, machine.total_hours, last, performer)
        out["machine_name"] = machine.name
        result.append(out)

    order = {"due": 0, "warning": 1, "ok": 2}
    result.sort(key=lambda x: order.get(x["status"], 9))
    return result
