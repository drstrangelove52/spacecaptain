from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, User
from app.schemas import MachineLocationCreate, MachineLocationOut, MachineLocationUpdate
from app.services.auth import get_current_user, require_power_manager

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[MachineLocationOut])
async def list_locations(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(
        select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name)
    )
    return result.scalars().all()


@router.post("", response_model=MachineLocationOut)
async def create_location(
    payload: MachineLocationCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    existing = await db.execute(select(MachineLocation).where(MachineLocation.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Standort existiert bereits")
    loc = MachineLocation(**payload.model_dump())
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@router.patch("/{loc_id}", response_model=MachineLocationOut)
async def update_location(
    loc_id: int,
    payload: MachineLocationUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    loc = await db.get(MachineLocation, loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(loc, k, v)
    await db.commit()
    await db.refresh(loc)
    return loc


@router.delete("/{loc_id}")
async def delete_location(
    loc_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    loc = await db.get(MachineLocation, loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    await db.delete(loc)
    await db.commit()
    return {"ok": True}
