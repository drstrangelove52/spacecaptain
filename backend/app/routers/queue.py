"""
Wartelisten-Endpoints für Gäste und Admins/Manager.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models import MachineQueue, Machine, Guest, Permission, QueueStatus, User, LogType
from app.services.system_settings import get_system_settings
from app.services.auth import get_current_user
from app.services.logger import log as activity_log

router = APIRouter(prefix="/queue", tags=["queue"])


def _guest_from_token(token: str, db):
    """Hilfsfunktion — inline guest auth ohne Dependency."""
    pass


@router.get("")
async def get_all_queues(db: AsyncSession = Depends(get_db)):
    """Gibt alle aktiven Wartelisten zurück (für TV-Dashboard, öffentlich)."""
    result = await db.execute(
        select(MachineQueue).where(
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified])
        ).order_by(MachineQueue.machine_id, MachineQueue.joined_at)
    )
    entries = result.scalars().all()

    # Gastdaten laden
    guests_res = await db.execute(select(Guest))
    guests = {g.id: g for g in guests_res.scalars().all()}

    out = []
    for e in entries:
        g = guests.get(e.guest_id)
        name = g.name if g else "?"
        out.append({
            "id": e.id,
            "machine_id": e.machine_id,
            "guest_id": e.guest_id,
            "guest_display": name,
            "status": e.status,
            "joined_at": e.joined_at.isoformat() if e.joined_at else None,
            "expires_at": (e.expires_at.isoformat() + 'Z') if e.expires_at else None,
        })
    return out


@router.post("/{machine_id}")
async def join_queue(
    machine_id: int,
    access_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Gast tritt Warteliste bei."""
    from app.services.auth import decode_guest_token
    payload = decode_guest_token(access_token)
    if not payload:
        raise HTTPException(401, "Ungültiger Token")
    guest_id = payload.get("guest_id")

    # Maschine prüfen
    machine_res = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = machine_res.scalar_one_or_none()
    if not machine or machine.status != "online":
        raise HTTPException(404, "Maschine nicht gefunden oder offline")

    # Berechtigung prüfen
    perm_res = await db.execute(
        select(Permission).where(Permission.guest_id == guest_id, Permission.machine_id == machine_id)
    )
    perm = perm_res.scalar_one_or_none()
    if machine.training_required:
        if not perm or perm.is_blocked:
            raise HTTPException(403, "Keine Berechtigung für diese Maschine")
    else:
        if perm and perm.is_blocked:
            raise HTTPException(403, "Du bist für diese Maschine gesperrt")

    # Bereits in der Warteliste?
    existing = await db.execute(
        select(MachineQueue).where(
            MachineQueue.machine_id == machine_id,
            MachineQueue.guest_id == guest_id,
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Du stehst bereits in der Warteliste")

    entry = MachineQueue(machine_id=machine_id, guest_id=guest_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # Position ermitteln
    pos_res = await db.execute(
        select(MachineQueue).where(
            MachineQueue.machine_id == machine_id,
            MachineQueue.status == QueueStatus.waiting,
        ).order_by(MachineQueue.joined_at)
    )
    entries = pos_res.scalars().all()
    position = next((i + 1 for i, e in enumerate(entries) if e.guest_id == guest_id), len(entries))

    await activity_log(db, LogType.queue_joined,
                       f"Gast {guest_id} tritt Warteliste für Maschine {machine_id} bei (Position {position})",
                       guest_id=guest_id, machine_id=machine_id)
    return {"ok": True, "position": position}


@router.delete("/{machine_id}")
async def leave_queue(
    machine_id: int,
    access_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Gast verlässt Warteliste."""
    from app.services.auth import decode_guest_token
    payload = decode_guest_token(access_token)
    if not payload:
        raise HTTPException(401, "Ungültiger Token")
    guest_id = payload.get("guest_id")

    await db.execute(
        delete(MachineQueue).where(
            MachineQueue.machine_id == machine_id,
            MachineQueue.guest_id == guest_id,
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]),
        )
    )
    await db.commit()
    await activity_log(db, LogType.queue_left,
                       f"Gast {guest_id} verlässt Warteliste für Maschine {machine_id}",
                       guest_id=guest_id, machine_id=machine_id)
    return {"ok": True}


@router.get("/my")
async def my_queue_entries(
    access_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Gibt alle aktiven Wartelisten-Einträge des eingeloggten Gasts zurück."""
    from app.services.auth import decode_guest_token
    payload = decode_guest_token(access_token)
    if not payload:
        raise HTTPException(401, "Ungültiger Token")
    guest_id = payload.get("guest_id")

    result = await db.execute(
        select(MachineQueue).where(
            MachineQueue.guest_id == guest_id,
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]),
        )
    )
    entries = result.scalars().all()

    settings = await get_system_settings(db)

    return [{
        "machine_id": e.machine_id,
        "status": e.status,
        "joined_at": e.joined_at.isoformat() if e.joined_at else None,
        "expires_at": e.expires_at.isoformat() if e.expires_at else None,
        "reservation_minutes": settings.queue_reservation_minutes,
    } for e in entries]


# ── Admin/Manager-Endpoints ────────────────────────────────────────────────────

@router.get("/admin")
async def admin_get_queues(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Alle aktiven Wartelisten-Einträge mit Gast- und Maschinennamen (Manager/Admin)."""
    result = await db.execute(
        select(MachineQueue).where(
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified])
        ).order_by(MachineQueue.machine_id, MachineQueue.joined_at)
    )
    entries = result.scalars().all()

    guests_res = await db.execute(select(Guest))
    guests = {g.id: g.name for g in guests_res.scalars().all()}

    machines_res = await db.execute(select(Machine))
    machines = {m.id: m.name for m in machines_res.scalars().all()}

    return [{
        "id": e.id,
        "machine_id": e.machine_id,
        "machine_name": machines.get(e.machine_id, "?"),
        "guest_id": e.guest_id,
        "guest_name": guests.get(e.guest_id, "?"),
        "status": e.status,
        "joined_at": e.joined_at.isoformat() if e.joined_at else None,
        "expires_at": e.expires_at.isoformat() if e.expires_at else None,
    } for e in entries]


@router.delete("/admin/{entry_id}")
async def admin_remove_queue_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Entfernt einen Wartelisten-Eintrag (Manager/Admin)."""
    result = await db.execute(select(MachineQueue).where(MachineQueue.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Eintrag nicht gefunden")
    guest_id = entry.guest_id
    machine_id = entry.machine_id
    await db.delete(entry)
    await db.commit()
    await activity_log(db, LogType.queue_left,
                       f"Gast {guest_id} aus Warteliste für Maschine {machine_id} entfernt (durch {current_user.name})",
                       guest_id=guest_id, machine_id=machine_id, user_id=current_user.id)
    return {"ok": True}


@router.post("/admin/{machine_id}/{guest_id}")
async def admin_add_to_queue(
    machine_id: int,
    guest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fügt einen Gast zur Warteliste hinzu (Manager/Admin)."""
    machine_res = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = machine_res.scalar_one_or_none()
    if not machine or machine.status != "online":
        raise HTTPException(404, "Maschine nicht gefunden oder offline")

    guest_res = await db.execute(select(Guest).where(Guest.id == guest_id, Guest.is_active == True))
    guest = guest_res.scalar_one_or_none()
    if not guest:
        raise HTTPException(404, "Gast nicht gefunden")

    existing = await db.execute(
        select(MachineQueue).where(
            MachineQueue.machine_id == machine_id,
            MachineQueue.guest_id == guest_id,
            MachineQueue.status.in_([QueueStatus.waiting, QueueStatus.notified]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Gast steht bereits in der Warteliste")

    entry = MachineQueue(machine_id=machine_id, guest_id=guest_id)
    db.add(entry)
    await db.commit()
    await activity_log(db, LogType.queue_joined,
                       f"Gast {guest.name} zur Warteliste für Maschine {machine.name} hinzugefügt (durch {current_user.name})",
                       guest_id=guest_id, machine_id=machine_id, user_id=current_user.id)
    return {"ok": True}
