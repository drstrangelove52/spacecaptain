from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import MachineAutomation, Machine, User
from app.schemas import AutomationCreate, AutomationUpdate, AutomationOut
from app.services.auth import get_current_user
from app.services.automation_watcher import get_automation_states
from app.services import logger as log_svc

router = APIRouter(prefix="/automations", tags=["automations"])


async def _auto_out(a: MachineAutomation) -> dict:
    return {
        "id":                  a.id,
        "source_machine_id":   a.source_machine_id,
        "target_machine_id":   a.target_machine_id,
        "source_machine_name": a.source_machine.name if a.source_machine else "",
        "target_machine_name": a.target_machine.name if a.target_machine else "",
        "on_threshold_w":      a.on_threshold_w,
        "off_threshold_w":     a.off_threshold_w,
        "off_delay_sec":       a.off_delay_sec,
        "enabled":             a.enabled,
        "created_at":          a.created_at,
    }


async def _load(auto_id: int, db: AsyncSession) -> MachineAutomation:
    res = await db.execute(select(MachineAutomation).where(MachineAutomation.id == auto_id))
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Automation nicht gefunden")
    return a


@router.get("", response_model=List[AutomationOut])
async def list_automations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    res = await db.execute(select(MachineAutomation).order_by(MachineAutomation.id))
    autos = res.scalars().all()
    # Eager-load machine names
    for a in autos:
        await db.refresh(a, ["source_machine", "target_machine"])
    return [await _auto_out(a) for a in autos]


@router.post("", response_model=AutomationOut)
async def create_automation(
    payload: AutomationCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Maschinen prüfen
    for mid, label in [(payload.source_machine_id, "Quell"), (payload.target_machine_id, "Ziel")]:
        m = (await db.execute(select(Machine).where(Machine.id == mid))).scalar_one_or_none()
        if not m:
            raise HTTPException(404, f"{label}-Maschine nicht gefunden")
    if payload.source_machine_id == payload.target_machine_id:
        raise HTTPException(400, "Quell- und Ziel-Maschine dürfen nicht identisch sein")
    if payload.on_threshold_w <= payload.off_threshold_w:
        raise HTTPException(400, "Einschaltschwelle muss höher sein als Ausschaltschwelle")

    a = MachineAutomation(**payload.model_dump())
    db.add(a)
    await db.commit()
    await db.refresh(a)
    await db.refresh(a, ["source_machine", "target_machine"])
    await log_svc.log(
        db, LogType.automation_created,
        f"Automation erstellt: {a.source_machine.name} → {a.target_machine.name} "
        f"(EIN ≥ {a.on_threshold_w} W, AUS < {a.off_threshold_w} W, Nachlauf {a.off_delay_sec} s)",
        user_id=current.id,
    )
    return await _auto_out(a)


@router.patch("/{auto_id}", response_model=AutomationOut)
async def update_automation(
    auto_id: int,
    payload: AutomationUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    a = await _load(auto_id, db)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(a, field, value)
    if a.on_threshold_w <= a.off_threshold_w:
        raise HTTPException(400, "Einschaltschwelle muss höher sein als Ausschaltschwelle")
    await db.commit()
    await db.refresh(a)
    await db.refresh(a, ["source_machine", "target_machine"])
    await log_svc.log(
        db, LogType.automation_updated,
        f"Automation geändert: {a.source_machine.name} → {a.target_machine.name} "
        f"({', '.join(changes.keys())})",
        user_id=current.id,
    )
    return await _auto_out(a)


@router.get("/states")
async def automation_states(
    _: User = Depends(get_current_user),
):
    """Aktueller Watcher-Zustand pro Automation (idle/on/countdown)."""
    return get_automation_states()


@router.delete("/{auto_id}")
async def delete_automation(
    auto_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    a = await _load(auto_id, db)
    await db.refresh(a, ["source_machine", "target_machine"])
    label = f"{a.source_machine.name} → {a.target_machine.name}"
    await db.delete(a)
    await db.commit()
    await log_svc.log(
        db, LogType.automation_deleted,
        f"Automation gelöscht: {label}",
        user_id=current.id,
    )
    return {"ok": True}
