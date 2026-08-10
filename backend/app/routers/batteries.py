from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Battery, User, LogType
from app.schemas import BatteryCreate, BatteryOut, BatteryUpdate
from app.services.auth import get_current_user, require_power_manager
from app.services import logger as log_svc

router = APIRouter(prefix="/batteries", tags=["batteries"])


@router.get("", response_model=list[BatteryOut])
async def list_batteries(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Battery).order_by(Battery.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=BatteryOut)
async def create_battery(
    payload: BatteryCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    battery = Battery(**payload.model_dump())
    db.add(battery)
    await db.commit()
    await db.refresh(battery)
    label = battery.name or f"{battery.manufacturer} {battery.model}".strip()
    await log_svc.log(db, LogType.battery_created, f"Akku {label} hinzugefügt", user_id=current.id)
    return battery


@router.patch("/{battery_id}", response_model=BatteryOut)
async def update_battery(
    battery_id: int,
    payload: BatteryUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    battery = await db.get(Battery, battery_id)
    if not battery:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(battery, k, v)
    await db.commit()
    await db.refresh(battery)
    label = battery.name or f"{battery.manufacturer} {battery.model}".strip()
    await log_svc.log(db, LogType.battery_updated, f"Akku {label} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return battery


@router.delete("/{battery_id}")
async def delete_battery(
    battery_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    battery = await db.get(Battery, battery_id)
    if not battery:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    label = battery.name or f"{battery.manufacturer} {battery.model}".strip()
    await log_svc.log(db, LogType.battery_deleted, f"Akku {label} gelöscht", user_id=current.id)
    await db.delete(battery)
    await db.commit()
    return {"ok": True}
