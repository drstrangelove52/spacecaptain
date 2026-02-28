from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models import User, LogType
from app.schemas import UserCreate, UserUpdate, UserOut
from app.services.auth import get_current_user, require_admin, hash_password
from app.services import logger as log_svc

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=List[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=UserOut)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    exists = await db.execute(select(User).where(User.email == payload.email))
    if exists.scalar_one_or_none():
        raise HTTPException(400, "Email bereits vergeben")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        phone=payload.phone,
        area=payload.area,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await log_svc.log(db, LogType.guest_created, f"Lab Manager {user.name} erstellt", user_id=current.id)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Manager darf nur sich selbst bearbeiten; Admin darf alle
    if current.role != "admin" and current.id != user_id:
        raise HTTPException(403, "Keine Berechtigung")

    # Manager darf Rolle und is_active nicht ändern
    restricted = {"role", "is_active"}
    if current.role != "admin" and restricted & payload.model_dump(exclude_unset=True).keys():
        raise HTTPException(403, "Keine Berechtigung")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Benutzer nicht gefunden")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "password":
            setattr(user, "password_hash", hash_password(value))
        else:
            # Leere Strings → None
            setattr(user, field, None if value == '' else value)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    if current.id == user_id:
        raise HTTPException(400, "Eigenen Account nicht löschbar")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Nicht gefunden")
    await db.delete(user)
    await db.commit()
    return {"ok": True}
