from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional

from app.database import get_db
from app.models import User, Guest, Machine, Permission, ActivityLog, LogType
from app.schemas import PermissionOut
from app.services.auth import get_current_user
from app.services import logger as log_svc

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=List[PermissionOut])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Permission))
    return result.scalars().all()


@router.post("/grant")
async def grant_permission(
    guest_id: int,
    machine_id: int,
    comment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Prüfen ob Gast und Maschine existieren
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    machine = (await db.execute(select(Machine).where(Machine.id == machine_id))).scalar_one_or_none()
    if not guest or not machine:
        raise HTTPException(404, "Gast oder Maschine nicht gefunden")

    # Bereits vorhanden?
    existing = (await db.execute(
        select(Permission).where(Permission.guest_id == guest_id, Permission.machine_id == machine_id)
    )).scalar_one_or_none()
    if existing:
        return {"ok": True, "message": "Berechtigung bereits vorhanden"}

    perm = Permission(guest_id=guest_id, machine_id=machine_id, granted_by=current.id)
    db.add(perm)
    await db.commit()
    msg = f"Berechtigung erteilt: {guest.name} → {machine.name}"
    if comment:
        msg += f" — {comment}"
    await log_svc.log(
        db, LogType.permission_granted, msg,
        guest_id=guest_id, machine_id=machine_id, user_id=current.id,
        meta={"comment": comment} if comment else None,
    )
    return {"ok": True}


@router.post("/revoke")
async def revoke_permission(
    guest_id: int,
    machine_id: int,
    comment: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(Permission.guest_id == guest_id, Permission.machine_id == machine_id)
    )
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(404, "Berechtigung nicht gefunden")

    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    machine = (await db.execute(select(Machine).where(Machine.id == machine_id))).scalar_one_or_none()

    await db.delete(perm)
    await db.commit()
    msg = f"Berechtigung entzogen: {guest.name if guest else guest_id} → {machine.name if machine else machine_id}"
    if comment:
        msg += f" — {comment}"
    await log_svc.log(
        db, LogType.permission_revoked, msg,
        guest_id=guest_id, machine_id=machine_id, user_id=current.id,
        meta={"comment": comment} if comment else None,
    )
    return {"ok": True}


@router.post("/bulk")
async def bulk_set_permissions(
    guest_id: int,
    machine_ids: List[int],
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Setzt alle Berechtigungen eines Gastes auf einmal (Matrix-Speichern)."""
    guest = (await db.execute(select(Guest).where(Guest.id == guest_id))).scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")

    # Alle alten löschen
    await db.execute(delete(Permission).where(Permission.guest_id == guest_id))

    # Neue anlegen
    for mid in machine_ids:
        perm = Permission(guest_id=guest_id, machine_id=mid, granted_by=current.id)
        db.add(perm)

    await db.commit()
    await log_svc.log(
        db, LogType.permission_granted,
        f"Berechtigungen aktualisiert: {guest.name} — {len(machine_ids)} Maschine(n)",
        guest_id=guest_id, user_id=current.id
    )
    return {"ok": True, "count": len(machine_ids)}


@router.get("/history")
async def permission_history(
    guest_id:   Optional[int] = Query(None),
    machine_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Letzter Berechtigungs-Logeintrag pro Maschine (Gast-Ansicht) oder pro Gast (Maschinen-Ansicht)."""
    if guest_id is None and machine_id is None:
        raise HTTPException(400, "guest_id oder machine_id erforderlich")

    q = select(ActivityLog).where(
        ActivityLog.type.in_([LogType.permission_granted, LogType.permission_revoked])
    )
    if guest_id   is not None: q = q.where(ActivityLog.guest_id   == guest_id)
    if machine_id is not None: q = q.where(ActivityLog.machine_id == machine_id)
    q = q.order_by(ActivityLog.created_at.desc())

    entries = (await db.execute(q)).scalars().all()
    users   = {u.id: u.name for u in (await db.execute(select(User))).scalars().all()}

    # Neuesten Eintrag pro Gegenseite behalten
    group_attr = "machine_id" if guest_id is not None else "guest_id"
    seen: set = set()
    result: dict = {}
    for e in entries:
        key = getattr(e, group_attr)
        if key not in seen:
            seen.add(key)
            result[str(key)] = {
                "type":       e.type,
                "comment":    e.meta.get("comment") if e.meta else None,
                "user_name":  users.get(e.user_id),
                "created_at": e.created_at.isoformat(),
            }
    return result
