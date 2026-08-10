from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineCategory, LogType
from app.schemas import MachineCategoryCreate, MachineCategoryOut, MachineCategoryUpdate
from app.services.auth import get_current_user, require_power_manager
from app.services import logger as log_svc
from app.models import User

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[MachineCategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(
        select(MachineCategory).order_by(MachineCategory.sort_order, MachineCategory.name)
    )
    return result.scalars().all()


@router.post("", response_model=MachineCategoryOut)
async def create_category(
    payload: MachineCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    existing = await db.execute(select(MachineCategory).where(MachineCategory.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Kategorie existiert bereits")
    cat = MachineCategory(**payload.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    await log_svc.log(db, LogType.category_created, f"Kategorie {cat.name} hinzugefügt", user_id=current.id)
    return cat


@router.patch("/{cat_id}", response_model=MachineCategoryOut)
async def update_category(
    cat_id: int,
    payload: MachineCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    cat = await db.get(MachineCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(cat, k, v)
    await db.commit()
    await db.refresh(cat)
    await log_svc.log(db, LogType.category_updated, f"Kategorie {cat.name} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return cat


@router.delete("/{cat_id}")
async def delete_category(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    cat = await db.get(MachineCategory, cat_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    await log_svc.log(db, LogType.category_deleted, f"Kategorie {cat.name} gelöscht", user_id=current.id)
    await db.delete(cat)
    await db.commit()
    return {"ok": True}
