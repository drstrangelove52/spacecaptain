from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineCategory
from app.schemas import MachineCategoryCreate, MachineCategoryOut, MachineCategoryUpdate
from app.routers.auth import get_current_user
from app.services.auth import require_power_manager
from app.models import User

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[MachineCategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    await db.commit()
    await db.refresh(cat)
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
    await db.delete(cat)
    await db.commit()
    return {"ok": True}
