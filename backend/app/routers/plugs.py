from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models import Plug, Machine, User, PlugType
from app.schemas import PlugCreate, PlugUpdate, PlugOut
from app.services.auth import get_current_user
from app.services.plug import switch_plug

router = APIRouter(prefix="/plugs", tags=["plugs"])

VALID_TYPES = {"mystrom", "shelly", "shelly_gen2"}


async def _plug_out(plug: Plug, db: AsyncSession) -> dict:
    res = await db.execute(
        select(Machine.id, Machine.name).where(Machine.plug_id == plug.id)
    )
    row = res.first()
    return {
        "id": plug.id,
        "name": plug.name,
        "plug_type": plug.plug_type,
        "plug_ip": plug.plug_ip,
        "plug_token": plug.plug_token,
        "notes": plug.notes,
        "created_at": plug.created_at,
        "machine_id": row[0] if row else None,
        "machine_name": row[1] if row else None,
    }


@router.get("", response_model=List[PlugOut])
async def list_plugs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).order_by(Plug.created_at.desc()))
    plugs = result.scalars().all()
    return [await _plug_out(p, db) for p in plugs]


@router.post("", response_model=PlugOut)
async def create_plug(
    payload: PlugCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if payload.plug_type not in VALID_TYPES:
        raise HTTPException(400, f"plug_type muss einer von {sorted(VALID_TYPES)} sein")
    plug = Plug(**payload.model_dump())
    db.add(plug)
    await db.commit()
    await db.refresh(plug)
    return await _plug_out(plug, db)


@router.patch("/{plug_id}", response_model=PlugOut)
async def update_plug(
    plug_id: int,
    payload: PlugUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    if "plug_type" in changes and changes["plug_type"] not in VALID_TYPES:
        raise HTTPException(400, f"plug_type muss einer von {sorted(VALID_TYPES)} sein")
    for field, value in changes.items():
        setattr(plug, field, value)
    await db.commit()
    await db.refresh(plug)
    return await _plug_out(plug, db)


@router.delete("/{plug_id}")
async def delete_plug(
    plug_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")
    assigned = await db.execute(select(Machine.id).where(Machine.plug_id == plug_id))
    if assigned.scalar_one_or_none():
        raise HTTPException(400, "Plug ist noch einer Maschine zugewiesen — zuerst Zuweisung aufheben")
    await db.delete(plug)
    await db.commit()
    return {"ok": True}


@router.post("/{plug_id}/assign")
async def assign_plug(
    plug_id: int,
    machine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    mres = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = mres.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    # Remove plug from previously assigned machine
    prev_res = await db.execute(select(Machine).where(Machine.plug_id == plug_id))
    for prev_machine in prev_res.scalars().all():
        prev_machine.plug_id = None

    machine.plug_id = plug_id
    machine.plug_type = PlugType(plug.plug_type)
    machine.plug_ip = plug.plug_ip
    machine.plug_token = plug.plug_token

    await db.commit()
    return {"ok": True}


@router.post("/{plug_id}/unassign")
async def unassign_plug(
    plug_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    mres = await db.execute(select(Machine).where(Machine.plug_id == plug_id))
    machine = mres.scalar_one_or_none()
    if machine:
        machine.plug_id = None
        machine.plug_type = PlugType.none
        machine.plug_ip = None
        machine.plug_token = None

    await db.commit()
    return {"ok": True}


@router.post("/{plug_id}/switch")
async def test_switch_plug(
    plug_id: int,
    action: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Schaltet einen freien Plug zum Test — nur wenn noch keiner Maschine zugewiesen."""
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    assigned = await db.execute(select(Machine.id).where(Machine.plug_id == plug_id))
    if assigned.scalar_one_or_none():
        raise HTTPException(400, "Plug ist einer Maschine zugewiesen — Test nur für freie Plugs")

    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    proxy = SimpleNamespace(
        plug_type=plug.plug_type,
        plug_ip=plug.plug_ip,
        plug_token=plug.plug_token,
    )
    ok, msg = await switch_plug(proxy, action)
    return {"ok": ok, "message": msg}
