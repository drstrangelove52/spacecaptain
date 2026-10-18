"""
Inventar-Modul: Bereiche, Moebel/Ebenen/Positionen, Werkzeug, Suche, Etiketten.
Siehe docs/inventar-konzept.md.

Rechte: lesen = jeder Lab-Manager, Werkzeug schreiben = jeder Lab-Manager,
Struktur schreiben = Power-Manager/Admin. Das ganze Modul ist per Einstellung
`inventory_enabled` ein-/ausschaltbar (aus = 404).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, Machine, MachineOwner, User, LogType
from app.models_inventory import (InvFurniture, InvLevel, InvPosition, InvItem, InvPlacement,
                                  FurnitureKind, InvItemStatus)
from app.services import inventory as inv
from app.services import logger as log_svc
from app.services.auth import get_current_user, require_power_manager
from app.services.system_settings import get_system_settings


async def require_inventory_enabled(db: AsyncSession = Depends(get_db)) -> None:
    s = await get_system_settings(db)
    if not s.inventory_enabled:
        raise HTTPException(404, "Das Inventar-Modul ist nicht aktiviert")
    await inv.ensure_structure_if_needed(db)


router = APIRouter(prefix="/inventory", tags=["inventory"],
                   dependencies=[Depends(require_inventory_enabled)])


# ── Schemas ──────────────────────────────────────────────────────────────────
class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=9)


class AreaUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    code: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=9)
    sort_order: Optional[int] = None


class FurnitureCreate(BaseModel):
    area_id: int
    kind: FurnitureKind = FurnitureKind.schrank
    name: Optional[str] = Field(default=None, max_length=100)
    levels: int = Field(default=0, ge=0, le=40)
    positions: int = Field(default=0, ge=0, le=40)
    note: Optional[str] = None


class FurnitureUpdate(BaseModel):
    kind: Optional[FurnitureKind] = None
    name: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = None
    area_id: Optional[int] = None


class LevelsCreate(BaseModel):
    count: int = Field(default=1, ge=1, le=40)
    positions: int = Field(default=0, ge=0, le=40)


class PositionsCreate(BaseModel):
    count: int = Field(default=1, ge=1, le=40)


class LabelUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=100)


class PrintedPayload(BaseModel):
    furniture_ids: list[int]


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    synonyms: Optional[str] = None
    description: Optional[str] = None
    quantity: int = Field(default=1, ge=0, le=100000)
    status: InvItemStatus = InvItemStatus.aktiv
    position_id: Optional[int] = None
    code: Optional[str] = None          # Alternative zu position_id, z.B. "ELE-M02-E03"
    serial_number: Optional[str] = Field(default=None, max_length=100)
    purchase_date: Optional[date] = None
    value_new: Optional[float] = Field(default=None, ge=0)      # Neuwert je Stück
    owner_id: Optional[int] = None


class ItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    synonyms: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=0, le=100000)
    status: Optional[InvItemStatus] = None
    position_id: Optional[int] = None
    code: Optional[str] = None
    unplace: bool = False               # True = Platz entfernen
    serial_number: Optional[str] = Field(default=None, max_length=100)
    purchase_date: Optional[date] = None
    value_new: Optional[float] = Field(default=None, ge=0)
    owner_id: Optional[int] = None


class ImportRow(BaseModel):
    name: str
    synonyms: Optional[str] = None
    code: Optional[str] = None
    quantity: int = 1


class ImportPayload(BaseModel):
    rows: list[ImportRow] = Field(max_length=2000)
    dry_run: bool = False


# ── Hilfen ───────────────────────────────────────────────────────────────────
def _clean(s: Optional[str]) -> Optional[str]:
    s = (s or "").strip()
    return s or None


def _area_out(a: MachineLocation, furniture_count: int = 0, item_count: int = 0, machine_count: int = 0) -> dict:
    return {"id": a.id, "name": a.name, "code": a.code, "color": a.color,
            "sort_order": a.sort_order, "furniture_count": furniture_count, "item_count": item_count,
            "machine_count": machine_count}


def _furniture_out(a: MachineLocation, f: InvFurniture) -> dict:
    return {
        "id": f.id, "area_id": f.area_id, "number": f.number, "kind": f.kind.value,
        "name": f.name, "note": f.note, "label_outdated": bool(f.label_outdated),
        "code": inv.short_code(a.code, f.number), "area": a.name, "color": a.color,
    }


def _item_out(item: InvItem, info: Optional[dict]) -> dict:
    return {
        "id": item.id, "name": item.name, "synonyms": item.synonyms or "",
        "description": item.description or "", "quantity": item.quantity,
        "status": item.status.value, "position": info,
        "serial_number": item.serial_number or "",
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "value_new": item.value_new, "owner_id": item.owner_id,
    }


async def _check_owner(db: AsyncSession, owner_id: Optional[int]) -> None:
    if owner_id is not None and not await db.scalar(select(MachineOwner.id).where(MachineOwner.id == owner_id)):
        raise HTTPException(400, "Eigentümer nicht gefunden")


_ITEM_JOIN = (
    select(InvItem, MachineLocation, InvFurniture, InvLevel, InvPosition)
    .outerjoin(InvPosition, InvPosition.id == InvItem.position_id)
    .outerjoin(InvLevel, InvLevel.id == InvPosition.level_id)
    .outerjoin(InvFurniture, InvFurniture.id == InvLevel.furniture_id)
    .outerjoin(MachineLocation, MachineLocation.id == InvFurniture.area_id)
)


def _row_to_item(row) -> dict:
    item, area, furn, lvl, pos = row
    info = inv.describe(area, furn, lvl, pos) if pos is not None else None
    return _item_out(item, info)


def _text_or_code_filter(q: str):
    """Treffer in Name/Synonymen/Beschreibung (alle Woerter) ODER passender Lagerort-Code."""
    words = [w for w in q.split() if w]
    text_cond = and_(*[
        or_(InvItem.name.ilike(f"%{w}%"), InvItem.synonyms.ilike(f"%{w}%"),
            InvItem.description.ilike(f"%{w}%"))
        for w in words
    ]) if words else None
    code_cond = None
    try:
        area_code, *_ = inv.parse_code(q.strip())
    except HTTPException:
        area_code = None
    if area_code:
        m = inv._CODE_RE.match(q.strip().upper())
        _, s, e, p = m.groups()
        conds = [MachineLocation.code == area_code]
        if s is not None:
            conds.append(InvFurniture.number == int(s))
        if e is not None:
            conds.append(InvLevel.number == int(e))
        if p is not None:
            conds.append(InvPosition.number == int(p))
        code_cond = and_(*conds)
    if text_cond is not None and code_cond is not None:
        return or_(text_cond, code_cond)
    return text_cond if text_cond is not None else code_cond


async def _get_area(db: AsyncSession, area_id: int) -> MachineLocation:
    a = await db.get(MachineLocation, area_id)
    if not a:
        raise HTTPException(404, "Bereich nicht gefunden")
    return a


async def _get_furniture(db: AsyncSession, fid: int) -> InvFurniture:
    f = await db.get(InvFurniture, fid)
    if not f:
        raise HTTPException(404, "Möbel nicht gefunden")
    return f


async def _count_items(db: AsyncSession, *, position_ids=None, level_id=None, furniture_id=None) -> int:
    q = select(func.count(InvItem.id)).join(InvPosition, InvPosition.id == InvItem.position_id)
    if position_ids is not None:
        q = q.where(InvItem.position_id.in_(position_ids))
    if level_id is not None:
        q = q.where(InvPosition.level_id == level_id)
    if furniture_id is not None:
        q = q.join(InvLevel, InvLevel.id == InvPosition.level_id).where(InvLevel.furniture_id == furniture_id)
    return await db.scalar(q) or 0


async def _resolve_target(db: AsyncSession, position_id: Optional[int], code: Optional[str]) -> Optional[InvPosition]:
    if code and code.strip():
        return await inv.resolve_position(db, code)
    if position_id is not None:
        pos = await db.get(InvPosition, position_id)
        if not pos:
            raise HTTPException(404, "Position nicht gefunden")
        return pos
    return None


# ── Bereiche ─────────────────────────────────────────────────────────────────
@router.get("/areas")
async def list_areas(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    areas = (await db.execute(select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    fcount = dict((await db.execute(
        select(InvFurniture.area_id, func.count(InvFurniture.id))
        .where(InvFurniture.number > 0).group_by(InvFurniture.area_id))).all())
    icount = dict((await db.execute(
        select(InvFurniture.area_id, func.count(InvItem.id))
        .select_from(InvItem)
        .join(InvPosition, InvPosition.id == InvItem.position_id)
        .join(InvLevel, InvLevel.id == InvPosition.level_id)
        .join(InvFurniture, InvFurniture.id == InvLevel.furniture_id)
        .group_by(InvFurniture.area_id))).all())
    mcount = dict((await db.execute(
        select(Machine.area_id, func.count(Machine.id)).where(Machine.area_id.is_not(None))
        .group_by(Machine.area_id))).all())
    return [_area_out(a, fcount.get(a.id, 0), icount.get(a.id, 0), mcount.get(a.id, 0)) for a in areas]


@router.post("/areas")
async def create_area(payload: AreaCreate, db: AsyncSession = Depends(get_db),
                      current: User = Depends(require_power_manager)):
    if await db.scalar(select(MachineLocation.id).where(MachineLocation.name == payload.name.strip())):
        raise HTTPException(409, "Bereich existiert bereits")
    code = inv.normalize_area_code(payload.code) if payload.code else None
    if code and await db.scalar(select(MachineLocation.id).where(MachineLocation.code == code)):
        raise HTTPException(409, f"Kürzel «{code}» ist schon vergeben")
    if not code:
        code = await inv.suggest_area_code(db, payload.name)
    a = MachineLocation(name=payload.name.strip(), code=code, color=_clean(payload.color) or inv.default_color(code, await inv._used_colors(db)))
    db.add(a)
    await db.commit()
    await db.refresh(a)
    await inv.ensure_area_structure(db, a.id)
    await inv.align_categories(db)                                        # Kategorie «<Bereich>» anlegen
    await db.commit()
    await log_svc.log(db, LogType.location_created, f"Bereich {a.name} hinzugefügt", user_id=current.id)
    return _area_out(a)


@router.get("/areas/suggest-code")
async def suggest_code(name: str = Query(..., min_length=1, max_length=100), area_id: Optional[int] = None,
                       db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return {"code": await inv.suggest_area_code(db, name, exclude_id=area_id)}


@router.post("/areas/assign-missing-codes")
async def assign_missing_codes(dry_run: bool = True, db: AsyncSession = Depends(get_db),
                               current: User = Depends(require_power_manager)):
    """Vergibt allen Bereichen ohne Kürzel einen Vorschlag. Standard: nur anzeigen (dry_run)."""
    result = await inv.assign_missing_codes(db, dry_run)
    if not dry_run and result:
        await log_svc.log(db, LogType.inventory_area_updated,
                          f"Kürzel für {len(result)} Bereiche vergeben: "
                          + ", ".join(f"{r['name']}={r['code']}" for r in result),
                          user_id=current.id)
    return {"dry_run": dry_run, "areas": result}


@router.patch("/areas/{area_id}")
async def update_area(area_id: int, payload: AreaUpdate, db: AsyncSession = Depends(get_db),
                      current: User = Depends(require_power_manager)):
    a = await _get_area(db, area_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"].strip() != a.name:
        if await db.scalar(select(MachineLocation.id).where(
                MachineLocation.name == changes["name"].strip(), MachineLocation.id != a.id)):
            raise HTTPException(409, "Bereich existiert bereits")
        old_name = a.name
        a.name = changes["name"].strip()
        await inv.propagate_area_rename(db, a.id, old_name, a.name)       # Maschinen und Kategorie ziehen mit
    if "code" in changes:
        await inv.set_area_code(db, a, changes["code"])   # markiert bei Aenderung die Etiketten als veraltet
    if "color" in changes:
        a.color = _clean(changes["color"])
    if "sort_order" in changes and changes["sort_order"] is not None:
        a.sort_order = changes["sort_order"]
    await db.commit()
    await db.refresh(a)
    await log_svc.log(db, LogType.inventory_area_updated, f"Bereich {a.name} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return _area_out(a)


# ── Struktur ─────────────────────────────────────────────────────────────────
@router.get("/tree")
async def tree(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    areas = (await db.execute(select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    furns = (await db.execute(select(InvFurniture).order_by(InvFurniture.number))).scalars().all()
    lvls = (await db.execute(select(InvLevel).order_by(InvLevel.number))).scalars().all()
    poss = (await db.execute(select(InvPosition).order_by(InvPosition.number))).scalars().all()
    counts = dict((await db.execute(
        select(InvItem.position_id, func.count(InvItem.id))
        .where(InvItem.position_id.is_not(None)).group_by(InvItem.position_id))).all())

    mcount = dict((await db.execute(
        select(Machine.area_id, func.count(Machine.id)).where(Machine.area_id.is_not(None))
        .group_by(Machine.area_id))).all())

    pos_by_level: dict[int, list] = {}
    for p in poss:
        pos_by_level.setdefault(p.level_id, []).append(p)
    lvl_by_furn: dict[int, list] = {}
    for l in lvls:
        lvl_by_furn.setdefault(l.furniture_id, []).append(l)
    furn_by_area: dict[int, list] = {}
    for f in furns:
        furn_by_area.setdefault(f.area_id, []).append(f)

    out = []
    for a in areas:
        a_total = 0
        f_list = []
        for f in furn_by_area.get(a.id, []):
            f_total = 0
            l_list = []
            for l in lvl_by_furn.get(f.id, []):
                p_list = []
                l_total = 0
                for p in pos_by_level.get(l.id, []):
                    n = counts.get(p.id, 0)
                    l_total += n
                    p_list.append({
                        "id": p.id, "number": p.number, "label": p.label, "item_count": n,
                        "code": inv.short_code(a.code, f.number, l.number, p.number),
                    })
                f_total += l_total
                l_list.append({
                    "id": l.id, "number": l.number, "label": l.label, "item_count": l_total,
                    "code": inv.short_code(a.code, f.number, l.number), "positions": p_list,
                })
            a_total += f_total
            fo = _furniture_out(a, f)
            fo.update({"item_count": f_total, "levels": l_list})
            f_list.append(fo)
        ao = _area_out(a, machine_count=mcount.get(a.id, 0))
        ao.update({"item_count": a_total, "furniture": f_list})
        out.append(ao)
    return out


@router.post("/furniture")
async def create_furniture(payload: FurnitureCreate, db: AsyncSession = Depends(get_db),
                           current: User = Depends(require_power_manager)):
    if payload.kind == FurnitureKind.bereich:
        raise HTTPException(400, "Die Art «bereich» ist nur für S0 vorgesehen")
    area = await _get_area(db, payload.area_id)
    f = await inv.create_furniture(db, area, payload.kind, _clean(payload.name),
                                   payload.levels, payload.positions, _clean(payload.note))
    await log_svc.log(db, LogType.inventory_furniture_created,
                      f"Möbel {inv.short_code(area.code, f.number)} angelegt", user_id=current.id)
    return _furniture_out(area, f)


@router.patch("/furniture/{fid}")
async def update_furniture(fid: int, payload: FurnitureUpdate, db: AsyncSession = Depends(get_db),
                           current: User = Depends(require_power_manager)):
    f = await _get_furniture(db, fid)
    if f.number == 0:
        raise HTTPException(400, "S0 («ohne Möbel») lässt sich nicht ändern")
    changes = payload.model_dump(exclude_unset=True)
    old_area = await _get_area(db, f.area_id)
    if "kind" in changes and changes["kind"] is not None:
        if changes["kind"] == FurnitureKind.bereich:
            raise HTTPException(400, "Die Art «bereich» ist nur für S0 vorgesehen")
        f.kind = changes["kind"]
    if "name" in changes:
        f.name = _clean(changes["name"])
    if "note" in changes:
        f.note = _clean(changes["note"])
    if changes.get("area_id") and changes["area_id"] != f.area_id:
        new_area = await _get_area(db, changes["area_id"])
        if not new_area.code:
            raise HTTPException(409, "Der Ziel-Bereich braucht zuerst ein Kürzel")
        top = await db.scalar(select(func.max(InvFurniture.number)).where(InvFurniture.area_id == new_area.id))
        f.area_id = new_area.id
        f.number = max(top or 0, 0) + 1
        f.label_outdated = True      # Code hat sich geaendert -> Etikett neu drucken
    await db.commit()
    area = await _get_area(db, f.area_id)
    await log_svc.log(db, LogType.inventory_furniture_updated,
                      f"Möbel {inv.short_code(area.code, f.number)} bearbeitet", user_id=current.id,
                      meta={"changed": list(changes.keys()),
                            "from_area": old_area.name, "to_area": area.name})
    return _furniture_out(area, f)


@router.delete("/furniture/{fid}")
async def delete_furniture(fid: int, db: AsyncSession = Depends(get_db),
                           current: User = Depends(require_power_manager)):
    f = await _get_furniture(db, fid)
    if f.number == 0:
        raise HTTPException(400, "S0 («ohne Möbel») lässt sich nicht löschen")
    n = await _count_items(db, furniture_id=f.id)
    if n:
        raise HTTPException(409, f"Im Möbel liegen noch {n} Werkzeuge — zuerst umlagern")
    area = await _get_area(db, f.area_id)
    code = inv.short_code(area.code, f.number)
    await db.execute(update(InvPlacement).where(InvPlacement.furniture_id == f.id).values(furniture_id=None, level_id=None))
    await db.delete(f)
    await db.commit()
    await log_svc.log(db, LogType.inventory_furniture_deleted, f"Möbel {code} gelöscht", user_id=current.id)
    return {"ok": True}


@router.post("/furniture/printed")
async def mark_printed(payload: PrintedPayload, db: AsyncSession = Depends(get_db),
                       _: User = Depends(get_current_user)):
    for f in (await db.execute(select(InvFurniture).where(InvFurniture.id.in_(payload.furniture_ids)))).scalars():
        f.label_outdated = False
    await db.commit()
    return {"ok": True}


@router.post("/furniture/{fid}/levels")
async def add_levels(fid: int, payload: LevelsCreate, db: AsyncSession = Depends(get_db),
                     current: User = Depends(require_power_manager)):
    f = await _get_furniture(db, fid)
    if f.number == 0:
        raise HTTPException(400, "S0 hat keine Ebenen")
    created = await inv.add_levels(db, f, payload.count, payload.positions)
    return {"ok": True, "created": len(created)}


@router.patch("/levels/{lid}")
async def update_level(lid: int, payload: LabelUpdate, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_power_manager)):
    lvl = await db.get(InvLevel, lid)
    if not lvl:
        raise HTTPException(404, "Ebene nicht gefunden")
    lvl.label = _clean(payload.label)
    await db.commit()
    return {"ok": True}


@router.delete("/levels/{lid}")
async def delete_level(lid: int, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_power_manager)):
    lvl = await db.get(InvLevel, lid)
    if not lvl:
        raise HTTPException(404, "Ebene nicht gefunden")
    if lvl.number == 0:
        raise HTTPException(400, "E0 lässt sich nicht löschen")
    n = await _count_items(db, level_id=lvl.id)
    if n:
        raise HTTPException(409, f"Auf der Ebene liegen noch {n} Werkzeuge — zuerst umlagern")
    await db.execute(update(InvPlacement).where(InvPlacement.level_id == lvl.id).values(level_id=None))
    await db.delete(lvl)
    await db.commit()
    return {"ok": True}


@router.post("/levels/{lid}/positions")
async def add_positions(lid: int, payload: PositionsCreate, db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_power_manager)):
    lvl = await db.get(InvLevel, lid)
    if not lvl:
        raise HTTPException(404, "Ebene nicht gefunden")
    created = await inv.add_positions(db, lvl, payload.count)
    return {"ok": True, "created": len(created)}


@router.patch("/positions/{pid}")
async def update_position(pid: int, payload: LabelUpdate, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_power_manager)):
    pos = await db.get(InvPosition, pid)
    if not pos:
        raise HTTPException(404, "Position nicht gefunden")
    pos.label = _clean(payload.label)
    await db.commit()
    return {"ok": True}


@router.delete("/positions/{pid}")
async def delete_position(pid: int, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_power_manager)):
    pos = await db.get(InvPosition, pid)
    if not pos:
        raise HTTPException(404, "Position nicht gefunden")
    if pos.number == 0:
        raise HTTPException(400, "P0 lässt sich nicht löschen")
    n = await _count_items(db, position_ids=[pos.id])
    if n:
        raise HTTPException(409, f"Am Platz liegen noch {n} Werkzeuge — zuerst umlagern")
    await db.delete(pos)
    await db.commit()
    return {"ok": True}


# ── Werkzeug ─────────────────────────────────────────────────────────────────
@router.get("/items")
async def list_items(
    q: str = "", area_id: Optional[int] = None, furniture_id: Optional[int] = None,
    status: Optional[InvItemStatus] = None,
    unplaced: bool = False, level_open: bool = False, valued: bool = False,
    limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user),
):
    conds = []
    if q.strip():
        c = _text_or_code_filter(q)
        if c is not None:
            conds.append(c)
    if area_id is not None:
        conds.append(MachineLocation.id == area_id)
    if furniture_id is not None:
        conds.append(InvFurniture.id == furniture_id)
    if status is not None:
        conds.append(InvItem.status == status)
    if unplaced:
        conds.append(InvItem.position_id.is_(None))
    if level_open:
        conds.append(and_(InvLevel.number == 0, InvFurniture.number > 0))
    if valued:                                     # nur Werkzeug mit Neuwert (Inventarliste für Buchhaltung/Versicherung)
        conds.append(InvItem.value_new.is_not(None))

    total_q = (select(func.count(InvItem.id))
               .outerjoin(InvPosition, InvPosition.id == InvItem.position_id)
               .outerjoin(InvLevel, InvLevel.id == InvPosition.level_id)
               .outerjoin(InvFurniture, InvFurniture.id == InvLevel.furniture_id)
               .outerjoin(MachineLocation, MachineLocation.id == InvFurniture.area_id))
    rows_q = _ITEM_JOIN
    for c in conds:
        total_q = total_q.where(c)
        rows_q = rows_q.where(c)
    total = await db.scalar(total_q) or 0
    rows = (await db.execute(rows_q.order_by(InvItem.name).limit(limit).offset(offset))).all()
    return {"total": total, "items": [_row_to_item(r) for r in rows]}


@router.get("/items/{item_id}")
async def get_item(item_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Ein Werkzeug mit Lagerort — Ziel der QR-Codes auf Werkzeug-Etiketten («gehört nach …»)."""
    row = (await db.execute(_ITEM_JOIN.where(InvItem.id == item_id))).first()
    if not row:
        raise HTTPException(404, "Werkzeug nicht gefunden")
    return _row_to_item(row)


@router.post("/items")
async def create_item(payload: ItemCreate, db: AsyncSession = Depends(get_db),
                      current: User = Depends(get_current_user)):
    pos = await _resolve_target(db, payload.position_id, payload.code)
    await _check_owner(db, payload.owner_id)
    item = InvItem(name=payload.name.strip(), synonyms=_clean(payload.synonyms),
                   description=_clean(payload.description), quantity=payload.quantity,
                   status=payload.status, position_id=pos.id if pos else None,
                   serial_number=_clean(payload.serial_number), purchase_date=payload.purchase_date,
                   value_new=payload.value_new, owner_id=payload.owner_id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    info = await inv.position_info(db, pos.id) if pos else None
    await log_svc.log(db, LogType.inventory_item_created,
                      f"Werkzeug {item.name} angelegt" + (f" ({info['code']})" if info else ""),
                      user_id=current.id)
    return _item_out(item, info)


@router.patch("/items/{item_id}")
async def update_item(item_id: int, payload: ItemUpdate, db: AsyncSession = Depends(get_db),
                      current: User = Depends(get_current_user)):
    item = await db.get(InvItem, item_id)
    if not item:
        raise HTTPException(404, "Werkzeug nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    old_info = await inv.position_info(db, item.position_id) if item.position_id else None
    for field in ("name", "synonyms", "description"):
        if field in changes:
            val = _clean(changes[field])
            if field == "name" and not val:
                raise HTTPException(400, "Name darf nicht leer sein")
            setattr(item, field, val)
    if "quantity" in changes and changes["quantity"] is not None:
        item.quantity = changes["quantity"]
    if "status" in changes and changes["status"] is not None:
        item.status = changes["status"]
    if "serial_number" in changes:
        item.serial_number = _clean(changes["serial_number"])
    for field in ("purchase_date", "value_new"):               # null = Wert entfernen
        if field in changes:
            setattr(item, field, changes[field])
    if "owner_id" in changes:
        await _check_owner(db, changes["owner_id"])
        item.owner_id = changes["owner_id"]
    moved = False
    if changes.get("unplace"):
        item.position_id = None
        moved = old_info is not None
    elif changes.get("code") or changes.get("position_id") is not None:
        pos = await _resolve_target(db, changes.get("position_id"), changes.get("code"))
        moved = pos.id != item.position_id
        item.position_id = pos.id
    await db.commit()
    await db.refresh(item)
    info = await inv.position_info(db, item.position_id) if item.position_id else None
    if moved:
        await log_svc.log(db, LogType.inventory_item_moved,
                          f"Werkzeug {item.name} umgelagert: {old_info['code'] if old_info else 'ohne Platz'}"
                          f" → {info['code'] if info else 'ohne Platz'}",
                          user_id=current.id,
                          meta={"from": old_info and old_info["code"], "to": info and info["code"]})
    else:
        await log_svc.log(db, LogType.inventory_item_updated, f"Werkzeug {item.name} bearbeitet",
                          user_id=current.id, meta={"changed": list(changes.keys())})
    return _item_out(item, info)


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db),
                      current: User = Depends(get_current_user)):
    item = await db.get(InvItem, item_id)
    if not item:
        raise HTTPException(404, "Werkzeug nicht gefunden")
    name = item.name
    await db.delete(item)
    await db.commit()
    await log_svc.log(db, LogType.inventory_item_deleted, f"Werkzeug {name} gelöscht", user_id=current.id)
    return {"ok": True}


@router.post("/items/import")
async def import_items(payload: ImportPayload, db: AsyncSession = Depends(get_db),
                       current: User = Depends(get_current_user)):
    """Mehrere Werkzeuge auf einmal (z.B. beim Einpacken). Zeilen mit Fehlern werden
    uebersprungen und einzeln gemeldet; mit dry_run wird nichts geschrieben."""
    errors, created = [], 0
    cache: dict[str, int] = {}
    to_add = []
    for i, row in enumerate(payload.rows, start=1):
        name = (row.name or "").strip()
        if not name:
            errors.append({"line": i, "error": "Name fehlt"})
            continue
        pos_id = None
        code = (row.code or "").strip().upper()
        if code:
            if code not in cache:
                try:
                    cache[code] = (await inv.resolve_position(db, code)).id
                except HTTPException as e:
                    errors.append({"line": i, "error": e.detail})
                    continue
            pos_id = cache[code]
        to_add.append(InvItem(name=name[:150], synonyms=_clean(row.synonyms),
                              quantity=max(0, min(row.quantity, 100000)), position_id=pos_id))
    if not payload.dry_run:
        db.add_all(to_add)
        await db.commit()
        created = len(to_add)
        await log_svc.log(db, LogType.inventory_items_imported,
                          f"{created} Werkzeuge importiert ({len(errors)} Zeilen mit Fehler)",
                          user_id=current.id)
    return {"created": created, "valid": len(to_add), "errors": errors, "dry_run": payload.dry_run}


# ── Maschinen ────────────────────────────────────────────────────────────────
_MACHINE_JOIN = (
    select(Machine, MachineLocation, InvPlacement, InvFurniture, InvLevel)
    .outerjoin(MachineLocation, MachineLocation.id == Machine.area_id)
    .outerjoin(InvPlacement, InvPlacement.machine_id == Machine.id)
    .outerjoin(InvFurniture, InvFurniture.id == InvPlacement.furniture_id)
    .outerjoin(InvLevel, InvLevel.id == InvPlacement.level_id)
)


def _machine_dict(row) -> dict:
    m, area, _pl, furn, lvl = row
    stands_on = None
    if furn is not None and area is not None:
        level = None
        if lvl is not None and lvl.furniture_id == furn.id and lvl.number > 0:
            level = {"id": lvl.id, "number": lvl.number, "label": lvl.label,
                     "code": inv.short_code(area.code, furn.number, lvl.number)}
        stands_on = {"furniture_id": furn.id, "code": inv.short_code(area.code, furn.number),
                     "title": inv.furniture_title(furn), "level": level}
    path = area.name if area else (m.location or "")
    if stands_on:
        path += " › " + stands_on["title"]
        if stands_on["level"]:
            path += " › " + (stands_on["level"]["label"] or f"Ebene {stands_on['level']['number']}")
    status = m.status.value if hasattr(m.status, "value") else m.status
    return {
        "id": m.id, "name": m.name, "category": m.category, "manufacturer": m.manufacturer, "model": m.model,
        "status": status, "location": m.location,
        "area": {"id": area.id, "name": area.name, "code": area.code, "color": area.color} if area else None,
        "stands_on": stands_on, "path": path,
    }


class MachineAssign(BaseModel):
    area_id: Optional[int] = None          # None = kein Bereich
    furniture_id: Optional[int] = None     # None = steht auf keinem Möbel
    level_id: Optional[int] = None         # None = keine bestimmte Ebene


@router.get("/machines")
async def list_machines(q: str = "", area_id: Optional[int] = None, unassigned: bool = False,
                        db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Alle Maschinen mit Bereich und «steht auf» — gemeinsame Sicht für Suche, Plan und Zuordnung."""
    stmt = _MACHINE_JOIN
    for w in [w for w in q.split() if w]:
        stmt = stmt.where(or_(Machine.name.ilike(f"%{w}%"), Machine.category.ilike(f"%{w}%"),
                              Machine.manufacturer.ilike(f"%{w}%"), Machine.model.ilike(f"%{w}%"),
                              MachineLocation.name.ilike(f"%{w}%")))
    if area_id is not None:
        stmt = stmt.where(Machine.area_id == area_id)
    if unassigned:
        stmt = stmt.where(Machine.area_id.is_(None))
    rows = (await db.execute(stmt.order_by(Machine.name))).all()
    return [_machine_dict(r) for r in rows]


@router.patch("/machines/{machine_id}")
async def assign_machine(machine_id: int, payload: MachineAssign, db: AsyncSession = Depends(get_db),
                         current: User = Depends(require_power_manager)):
    """Bereich wechseln und/oder festlegen, auf welchem Möbel (und welcher Ebene) die Maschine steht. Der Standort-Text
    der Maschine wird mitgeführt, damit Maschinenliste, CSV-Export und Display weiter stimmen."""
    m = await db.get(Machine, machine_id)
    if not m:
        raise HTTPException(404, "Maschine nicht gefunden")
    given = payload.model_fields_set
    old_area = await db.get(MachineLocation, m.area_id) if m.area_id else None
    moved = False
    if "area_id" in given:
        new_area = await _get_area(db, payload.area_id) if payload.area_id is not None else None
        if (new_area.id if new_area else None) != m.area_id:
            m.area_id = new_area.id if new_area else None
            m.location = new_area.name if new_area else None
            moved = True
    pl = await db.get(InvPlacement, m.id)
    if pl is None and ({"furniture_id", "level_id"} & given):
        pl = InvPlacement(machine_id=m.id)
        db.add(pl)
    if "furniture_id" in given:
        fid = payload.furniture_id
        if fid is not None:
            f = await _get_furniture(db, fid)
            if f.number == 0:
                raise HTTPException(400, "«Im Bereich, ohne Möbel» lässt sich nicht als Standfläche wählen")
            if f.area_id != m.area_id:
                raise HTTPException(409, "Das Möbel gehört zu einem anderen Bereich als die Maschine")
        if pl.furniture_id != fid:
            pl.level_id = None                                   # andere Standfläche → alte Ebene gilt nicht mehr
        pl.furniture_id = fid
    elif moved and pl and pl.furniture_id:
        f = await db.get(InvFurniture, pl.furniture_id)         # «steht auf» passt nur im selben Bereich
        if not f or f.area_id != m.area_id:
            pl.furniture_id = None
    if "level_id" in given:
        lid = payload.level_id
        if lid is not None:
            lvl = await db.get(InvLevel, lid)
            if not lvl:
                raise HTTPException(404, "Ebene nicht gefunden")
            if lvl.number == 0:
                raise HTTPException(400, "«Ebene offen» (E00) lässt sich nicht wählen — dann einfach keine Ebene angeben")
            if pl.furniture_id is None or lvl.furniture_id != pl.furniture_id:
                raise HTTPException(409, "Die Ebene gehört nicht zum gewählten Möbel")
        pl.level_id = lid
    if pl is not None and pl.furniture_id is None:
        pl.level_id = None
    if moved:
        await inv.align_categories(db)                           # Kategorie folgt dem Bereich
    await db.commit()
    if moved:
        new_name = m.location or "kein Bereich"
        await log_svc.log(db, LogType.machine_area_changed,
                          f"Maschine {m.name}: Bereich {old_area.name if old_area else 'kein Bereich'} → {new_name}",
                          machine_id=m.id, user_id=current.id,
                          meta={"from": old_area.name if old_area else None, "to": m.location})
    row = (await db.execute(_MACHINE_JOIN.where(Machine.id == m.id))).first()
    return _machine_dict(row)


# ── Suche & Code ─────────────────────────────────────────────────────────────
@router.get("/search")
async def search(q: str = Query("", max_length=100), limit: int = Query(30, ge=1, le=100),
                 db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    q = q.strip()
    if not q:
        return []
    cond = _text_or_code_filter(q)
    rows = (await db.execute(_ITEM_JOIN.where(cond).order_by(InvItem.name).limit(limit))).all() if cond is not None else []
    results = []
    for r in rows:
        d = _row_to_item(r)
        results.append({"type": "tool", **d})
    # Moebel mit passendem Namen («Hilti Schrank») oder Code
    words = [w for w in q.split() if w]
    fcond = [or_(InvFurniture.name.ilike(f"%{w}%"), MachineLocation.name.ilike(f"%{w}%")) for w in words]
    frows = (await db.execute(
        select(MachineLocation, InvFurniture).join(InvFurniture, InvFurniture.area_id == MachineLocation.id)
        .where(InvFurniture.number > 0, and_(*fcond)).limit(10))).all()
    for a, f in frows:
        results.append({"type": "furniture", "id": f.id, "name": inv.furniture_title(f),
                        "code": inv.short_code(a.code, f.number), "path": f"{a.name} › {inv.furniture_title(f)}",
                        "color": a.color})
    # Maschinen (Name, Kategorie, Hersteller, Modell oder Bereich)
    mconds = [or_(Machine.name.ilike(f"%{w}%"), Machine.category.ilike(f"%{w}%"), Machine.manufacturer.ilike(f"%{w}%"),
                  Machine.model.ilike(f"%{w}%"), MachineLocation.name.ilike(f"%{w}%")) for w in words]
    mrows = (await db.execute(_MACHINE_JOIN.where(and_(*mconds)).order_by(Machine.name).limit(10))).all()
    for r in mrows:
        d = _machine_dict(r)
        results.append({"type": "machine", "id": d["id"], "name": d["name"], "category": d["category"],
                        "path": d["path"], "area": d["area"] and d["area"]["name"], "code": None,
                        "color": d["area"] and d["area"]["color"], "stands_on": d["stands_on"]})
    return results


@router.get("/code/{code}")
async def by_code(code: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Inhalt eines Bereichs / Möbels / einer Ebene / Position — Ziel der QR-Codes."""
    area_code, s, e, p = inv.parse_code(code)
    m = inv._CODE_RE.match(code.strip().upper())
    _, gs, ge, gp = m.groups()
    area = await db.scalar(select(MachineLocation).where(MachineLocation.code == area_code))
    if not area:
        raise HTTPException(404, f"Bereich «{area_code}» nicht gefunden")
    conds = [MachineLocation.id == area.id]
    scope = "area"
    if gs is not None:
        conds.append(InvFurniture.number == s)
        scope = "furniture"
    if ge is not None:
        conds.append(InvLevel.number == e)
        scope = "level"
    if gp is not None:
        conds.append(InvPosition.number == p)
        scope = "position"
    rows = (await db.execute(_ITEM_JOIN.where(*conds).order_by(InvItem.name))).all()
    return {"code": inv.short_code(area.code, s, e, p) if gs is not None else area.code,
            "scope": scope, "area": area.name, "color": area.color,
            "items": [_row_to_item(r) for r in rows]}


# ── Etiketten ────────────────────────────────────────────────────────────────
@router.get("/labels")
async def labels(area_id: Optional[int] = None, outdated: bool = False,
                 db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Daten für den Etikettendruck: je Möbel, je Ebene (>0) und je Position (>0) ein Etikett.
    Mitgeliefert wird, was dort liegt (Name und Menge), damit es auf dem Etikett stehen kann."""
    q = (select(MachineLocation, InvFurniture)
         .join(InvFurniture, InvFurniture.area_id == MachineLocation.id)
         .where(InvFurniture.number > 0)
         .order_by(MachineLocation.sort_order, MachineLocation.name, InvFurniture.number))
    if area_id is not None:
        q = q.where(MachineLocation.id == area_id)
    if outdated:
        q = q.where(InvFurniture.label_outdated.is_(True))
    pairs = (await db.execute(q)).all()
    fids = [f.id for _, f in pairs]
    all_lvls = (await db.execute(select(InvLevel).where(InvLevel.furniture_id.in_(fids))
                                 .order_by(InvLevel.number))).scalars().all() if fids else []
    lvl_ids = [l.id for l in all_lvls]
    poss = (await db.execute(select(InvPosition).where(InvPosition.level_id.in_(lvl_ids), InvPosition.number > 0)
                             .order_by(InvPosition.number))).scalars().all() if lvl_ids else []

    # Inhalte: Werkzeug je Position, Ebene und Möbel (Name + Menge)
    rows = (await db.execute(
        select(InvItem.name, InvItem.quantity, InvPosition.id, InvPosition.level_id)
        .join(InvPosition, InvPosition.id == InvItem.position_id)
        .where(InvPosition.level_id.in_(lvl_ids)).order_by(InvItem.name))).all() if lvl_ids else []
    lvl_furn = {l.id: l.furniture_id for l in all_lvls}
    by_pos: dict[int, list] = {}
    by_lvl: dict[int, list] = {}
    by_furn: dict[int, list] = {}
    for name, qty, pid, lid in rows:
        entry = {"name": name, "quantity": qty}
        by_pos.setdefault(pid, []).append(entry)
        by_lvl.setdefault(lid, []).append(entry)
        by_furn.setdefault(lvl_furn[lid], []).append(entry)

    def cut(entries, n):
        return {"items": (entries or [])[:n], "item_count": len(entries or [])}

    pos_by_lvl: dict[int, list] = {}
    for p in poss:
        pos_by_lvl.setdefault(p.level_id, []).append(p)
    lvl_by_f: dict[int, list] = {}
    for l in all_lvls:
        if l.number > 0:
            lvl_by_f.setdefault(l.furniture_id, []).append(l)

    out = []
    for a_, f in pairs:
        levels = []
        for l in lvl_by_f.get(f.id, []):
            levels.append({
                "id": l.id, "number": l.number, "label": l.label,
                "code": inv.short_code(a_.code, f.number, l.number),
                **cut(by_lvl.get(l.id), 12),
                "positions": [{"id": p.id, "number": p.number, "label": p.label,
                               "code": inv.short_code(a_.code, f.number, l.number, p.number),
                               **cut(by_pos.get(p.id), 12)} for p in pos_by_lvl.get(l.id, [])],
            })
        out.append({
            "furniture_id": f.id, "code": inv.short_code(a_.code, f.number),
            "name": inv.furniture_title(f), "area": a_.name,
            "area_code": a_.code, "color": a_.color, "outdated": bool(f.label_outdated),
            **cut(by_furn.get(f.id), 8),
            "levels": levels,
        })
    return out
