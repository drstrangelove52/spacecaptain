from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineOwner, User, LogType
from app.schemas import MachineOwnerCreate, MachineOwnerOut, MachineOwnerUpdate
from app.services.auth import get_current_user, require_power_manager
from app.services import logger as log_svc

router = APIRouter(prefix="/owners", tags=["owners"])


@router.get("", response_model=list[MachineOwnerOut])
async def list_owners(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(
        select(MachineOwner).order_by(MachineOwner.sort_order, MachineOwner.name)
    )
    return result.scalars().all()


@router.post("", response_model=MachineOwnerOut)
async def create_owner(
    payload: MachineOwnerCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    existing = await db.execute(select(MachineOwner).where(MachineOwner.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Eigentümer existiert bereits")
    owner = MachineOwner(**payload.model_dump())
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    await log_svc.log(db, LogType.owner_created, f"Eigentümer {owner.name} hinzugefügt", user_id=current.id)
    return owner


@router.patch("/{owner_id}", response_model=MachineOwnerOut)
async def update_owner(
    owner_id: int,
    payload: MachineOwnerUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    owner = await db.get(MachineOwner, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(owner, k, v)
    await db.commit()
    await db.refresh(owner)
    await log_svc.log(db, LogType.owner_updated, f"Eigentümer {owner.name} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return owner


@router.delete("/{owner_id}")
async def delete_owner(
    owner_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    owner = await db.get(MachineOwner, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    await log_svc.log(db, LogType.owner_deleted, f"Eigentümer {owner.name} gelöscht", user_id=current.id)
    await db.delete(owner)
    await db.commit()
    return {"ok": True}
