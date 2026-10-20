from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, Machine, User, LogType
from app.schemas import MachineLocationCreate, MachineLocationOut, MachineLocationUpdate
from app.services.auth import get_current_user, require_power_manager
from app.services import logger as log_svc
from app.services import inventory as inv_svc
from app.services.system_settings import get_system_settings

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
    loc = MachineLocation(name=payload.name, sort_order=payload.sort_order,
                          color=(payload.color or "").strip() or None)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    # Inventar-Modul: Bereich braucht ein Kuerzel — gewaehltes pruefen, sonst bei aktivem Modul vorschlagen
    if (payload.code or "").strip():
        await inv_svc.set_area_code(db, loc, payload.code)
    elif (await get_system_settings(db)).inventory_enabled:
        loc.code = await inv_svc.suggest_area_code(db, loc.name, exclude_id=loc.id)
    if loc.code and not loc.color:
        loc.color = inv_svc.default_color(loc.code, await inv_svc._used_colors(db))
    await db.commit()
    await db.refresh(loc)
    await inv_svc.ensure_area_structure(db, loc.id)
    if await inv_svc.inventory_enabled(db):                     # Kategorie «<Bereich>» anlegen
        await inv_svc.align_categories(db)
        await db.commit()
    await log_svc.log(db, LogType.location_created, f"Standort {loc.name} hinzugefügt", user_id=current.id)
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
    changes = payload.model_dump(exclude_unset=True)
    old_name = loc.name
    code = changes.pop("code", None)
    if "color" in changes:
        changes["color"] = (changes["color"] or "").strip() or None
    for k, v in changes.items():
        setattr(loc, k, v)
    if "name" in changes and changes["name"] != old_name:
        # Umbenennen: Maschinen dieses Standorts (feste Zuordnung oder gleicher Text) und die gleichnamige Kategorie ziehen mit
        await inv_svc.propagate_area_rename(db, loc.id, old_name, changes["name"])
    if (code or "").strip():                     # leeres Kuerzel = unveraendert (Entfernen nur im Inventar)
        await inv_svc.set_area_code(db, loc, code)
        changes["code"] = code
    await db.commit()
    await db.refresh(loc)
    await log_svc.log(db, LogType.location_updated, f"Standort {loc.name} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
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
    await inv_svc.remove_empty_area_structure(db, loc)   # 409, wenn noch Moebel/Werkzeug zugeordnet sind
    await inv_svc.release_machines_of_area(db, loc)      # Maschinen ohne Bereich → «Sonstiges»
    await log_svc.log(db, LogType.location_deleted, f"Standort {loc.name} gelöscht", user_id=current.id)
    await db.delete(loc)
    await db.commit()
    return {"ok": True}
