from datetime import time as Time
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, DeviceSchedule, Machine, LogType
from app.services.auth import require_admin
from app.services import logger as log_svc

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleOut(BaseModel):
    id: int
    machine_id: int
    machine_name: str
    name: str
    days: str
    time_on: str
    time_off: str
    require_room_open: bool
    enabled: bool

    class Config:
        from_attributes = True


class ScheduleCreate(BaseModel):
    machine_id: int
    name: str = ""
    days: str
    time_on: str   # "HH:MM"
    time_off: str  # "HH:MM"
    require_room_open: bool = True
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    days: Optional[str] = None
    time_on: Optional[str] = None
    time_off: Optional[str] = None
    require_room_open: Optional[bool] = None
    enabled: Optional[bool] = None


def _parse_time(s: str) -> Time:
    try:
        parts = s.split(":")
        return Time(int(parts[0]), int(parts[1]))
    except Exception:
        raise HTTPException(400, f"Ungültiges Zeitformat: {s!r} — erwartet HH:MM")


def _time_str(t: Time) -> str:
    return t.strftime("%H:%M")


async def _sched_out(s: DeviceSchedule) -> dict:
    return {
        "id": s.id,
        "machine_id": s.machine_id,
        "machine_name": s.machine.name if s.machine else "?",
        "name": s.name,
        "days": s.days,
        "time_on": _time_str(s.time_on),
        "time_off": _time_str(s.time_off),
        "require_room_open": s.require_room_open,
        "enabled": s.enabled,
    }


@router.get("", response_model=List[dict])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    res = await db.execute(select(DeviceSchedule).order_by(DeviceSchedule.id))
    return [await _sched_out(s) for s in res.scalars().all()]


@router.post("", response_model=dict)
async def create_schedule(
    payload: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    machine = (await db.execute(select(Machine).where(Machine.id == payload.machine_id))).scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    s = DeviceSchedule(
        machine_id=payload.machine_id,
        name=payload.name.strip(),
        days=payload.days,
        time_on=_parse_time(payload.time_on),
        time_off=_parse_time(payload.time_off),
        require_room_open=payload.require_room_open,
        enabled=payload.enabled,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    result = await _sched_out(s)
    await log_svc.log(db, LogType.schedule_created,
                      f"Zeitplan '{s.name or s.id}' für {machine.name} erstellt",
                      user_id=current.id)
    return result


@router.patch("/{schedule_id}", response_model=dict)
async def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    s = (await db.execute(select(DeviceSchedule).where(DeviceSchedule.id == schedule_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Zeitplan nicht gefunden")

    if payload.name is not None:
        s.name = payload.name.strip()
    if payload.days is not None:
        s.days = payload.days
    if payload.time_on is not None:
        s.time_on = _parse_time(payload.time_on)
    if payload.time_off is not None:
        s.time_off = _parse_time(payload.time_off)
    if payload.require_room_open is not None:
        s.require_room_open = payload.require_room_open
    if payload.enabled is not None:
        s.enabled = payload.enabled

    await db.commit()
    await db.refresh(s)
    result = await _sched_out(s)
    await log_svc.log(db, LogType.schedule_updated,
                      f"Zeitplan '{s.name or s.id}' aktualisiert",
                      user_id=current.id)
    return result


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    s = (await db.execute(select(DeviceSchedule).where(DeviceSchedule.id == schedule_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Zeitplan nicht gefunden")

    label = s.name or str(s.id)
    machine_res = await db.execute(select(Machine).where(Machine.id == s.machine_id))
    machine = machine_res.scalar_one_or_none()
    machine_name = machine.name if machine else "?"

    await db.delete(s)
    await db.commit()
    await log_svc.log(db, LogType.schedule_deleted,
                      f"Zeitplan '{label}' für {machine_name} gelöscht",
                      user_id=current.id)
    return {"ok": True}
