"""
Inventar-Modul, Etappe 4: Bauplan-Endpunkte (Teil von /api/inventory, gleiche Freischaltung).

Lesen: jeder Lab Manager. Zeichnen, Verschieben, Raum aendern: Power-Manager/Admin.
Verschieben ist Alltag und wird nicht einzeln protokolliert; nur Aenderungen am Raum stehen im Aktivitaetslog.
"""
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, Machine, User, LogType
from sqlalchemy import select, func, update, delete
from app.models_inventory import InvFurniture, InvPlacement, InvFloor, InvRoom
from app.routers.inventory import require_inventory_enabled
from app.services import inventory_plan as plan_svc
from app.services import logger as log_svc
from app.services.auth import get_current_user, require_power_manager

router = APIRouter(prefix="/inventory/plan", tags=["inventory-plan"],
                   dependencies=[Depends(require_inventory_enabled)])


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    width_cm: Optional[float] = Field(default=None, ge=100, le=100000)
    height_cm: Optional[float] = Field(default=None, ge=100, le=100000)


class RectUpdate(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    rot: Optional[float] = 0.0
    floor_id: Optional[int] = None       # Stockwerk; leer = bisheriges bzw. erstes
    remove: bool = False                 # True = vom Plan nehmen


class FloorBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    sort_order: Optional[int] = None


class RoomBody(BaseModel):
    floor_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    kind: Optional[Literal["raum", "treppe", "tuer", "durchgang"]] = None
    points: Optional[list[list[float]]] = None        # Eckpunkte eines Raums (cm); null = Rechteck
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    rot: Optional[float] = None
    link_floor_id: Optional[int] = None


async def _floor_ids(db: AsyncSession) -> set:
    return {f.id for f in await plan_svc.get_floors(db)}


# ── Stockwerke ──
@router.post("/floors")
async def create_floor(payload: FloorBody, db: AsyncSession = Depends(get_db), current: User = Depends(require_power_manager)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Name fehlt")
    floors = await plan_svc.get_floors(db)
    if any(f.name.lower() == name.lower() for f in floors):
        raise HTTPException(409, "Dieses Stockwerk gibt es schon")
    f = InvFloor(name=name, sort_order=max(x.sort_order for x in floors) + 1)
    db.add(f)
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated, f"Plan: Stockwerk «{name}» angelegt", user_id=current.id)
    return {"id": f.id, "name": f.name}


@router.patch("/floors/{floor_id}")
async def update_floor(floor_id: int, payload: FloorBody, db: AsyncSession = Depends(get_db),
                       current: User = Depends(require_power_manager)):
    f = await db.get(InvFloor, floor_id)
    if not f:
        raise HTTPException(404, "Stockwerk nicht gefunden")
    if payload.name is not None:
        name = payload.name.strip()
        if any(o.id != f.id and o.name.lower() == name.lower() for o in await plan_svc.get_floors(db)):
            raise HTTPException(409, "Dieses Stockwerk gibt es schon")
        f.name = name
    if payload.sort_order is not None:
        f.sort_order = payload.sort_order
    await db.commit()
    return {"id": f.id, "name": f.name}


@router.delete("/floors/{floor_id}")
async def delete_floor(floor_id: int, db: AsyncSession = Depends(get_db), current: User = Depends(require_power_manager)):
    f = await db.get(InvFloor, floor_id)
    if not f:
        raise HTTPException(404, "Stockwerk nicht gefunden")
    floors = await plan_svc.get_floors(db)
    if len(floors) <= 1:
        raise HTTPException(409, "Das letzte Stockwerk lässt sich nicht löschen")
    used = await db.scalar(select(func.count(InvRoom.id)).where((InvRoom.floor_id == floor_id) | (InvRoom.link_floor_id == floor_id)))
    for model in (MachineLocation, InvFurniture, InvPlacement):
        used = (used or 0) + (await db.scalar(select(func.count()).select_from(model).where(
            model.plan_floor_id == floor_id, model.plan_x.is_not(None))) or 0)
    if used:
        raise HTTPException(409, "Das Stockwerk ist nicht leer: erst Räume und Elemente entfernen oder verschieben")
    await db.delete(f)
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated, f"Plan: Stockwerk «{f.name}» gelöscht", user_id=current.id)
    return {"ok": True}


# ── Räume und Treppen ──
def _room_apply(r: InvRoom, p: RoomBody, given: set) -> None:
    old = (r.plan_x, r.plan_y, r.plan_w, r.plan_h)
    for src, dst in (("x", "plan_x"), ("y", "plan_y"), ("w", "plan_w"), ("h", "plan_h")):
        if src in given and getattr(p, src) is not None:
            setattr(r, dst, getattr(p, src))
    if "rot" in given and p.rot is not None:
        r.plan_rot = p.rot % 360
    if "name" in given and p.name:
        r.name = p.name.strip()
    if "kind" in given and p.kind:
        r.kind = p.kind
    if "points" in given:
        if p.points is None:
            r.points = None                                   # zurück zum Rechteck (bbox bleibt)
        else:
            if not plan_svc.points_valid(p.points):
                raise HTTPException(400, "Ungültige Eckpunkte (3–60 Punkte, Mindestgrösse 5 cm)")
            r.plan_x, r.plan_y, r.plan_w, r.plan_h = plan_svc.points_bbox(p.points)
            r.points = json.dumps([[round(q[0], 2), round(q[1], 2)] for q in p.points])
    elif r.points and (r.plan_x, r.plan_y, r.plan_w, r.plan_h) != old and old[2] and old[3]:
        pts = plan_svc.parse_points(r.points)                   # Verschieben/Skalieren per Rechteck: Punkte mitführen
        if pts:
            ox, oy, ow, oh = old
            r.points = json.dumps([[round(r.plan_x + (q[0] - ox) / ow * r.plan_w, 2),
                                    round(r.plan_y + (q[1] - oy) / oh * r.plan_h, 2)] for q in pts])
    if r.kind != "raum":
        r.points = None                                       # nur Räume haben Eckpunkte


async def _check_room(db: AsyncSession, r: InvRoom, p: RoomBody, given: set) -> None:
    ids = await _floor_ids(db)
    if r.floor_id not in ids:
        raise HTTPException(404, "Stockwerk nicht gefunden")
    if "link_floor_id" in given:
        if p.link_floor_id is not None and (p.link_floor_id not in ids or p.link_floor_id == r.floor_id):
            raise HTTPException(400, "Ungültiges Ziel-Stockwerk")
        r.link_floor_id = p.link_floor_id if r.kind == "treppe" else None
    if not plan_svc.valid_rect(r.plan_x, r.plan_y, r.plan_w, r.plan_h, r.plan_rot):
        raise HTTPException(400, "Ungültige Position oder Grösse")


@router.post("/rooms")
async def create_room(payload: RoomBody, db: AsyncSession = Depends(get_db), _: User = Depends(require_power_manager)):
    floors = await plan_svc.get_floors(db)
    given = payload.model_fields_set
    r = InvRoom(floor_id=payload.floor_id if payload.floor_id is not None else floors[0].id,
                name=(payload.name or "Raum").strip(), kind=payload.kind or "raum",
                plan_x=0.0, plan_y=0.0, plan_w=300.0, plan_h=300.0, plan_rot=0.0)
    if r.kind == "treppe" and "w" not in given:
        r.plan_w, r.plan_h = 100.0, 250.0
    if r.kind in ("tuer", "durchgang") and "w" not in given:
        r.plan_w, r.plan_h = 90.0, 14.0
        if not payload.name:
            r.name = "Tür" if r.kind == "tuer" else "Durchgang"
    _room_apply(r, payload, given)
    await _check_room(db, r, payload, given)
    db.add(r)
    await db.commit()
    return plan_svc.room_out(r)


@router.patch("/rooms/{room_id}")
async def update_room_rect(room_id: int, payload: RoomBody, db: AsyncSession = Depends(get_db),
                           _: User = Depends(require_power_manager)):
    r = await db.get(InvRoom, room_id)
    if not r:
        raise HTTPException(404, "Raum nicht gefunden")
    given = payload.model_fields_set
    if "floor_id" in given and payload.floor_id is not None:
        r.floor_id = payload.floor_id
    _room_apply(r, payload, given)
    await _check_room(db, r, payload, given)
    await db.commit()
    return plan_svc.room_out(r)


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_power_manager)):
    r = await db.get(InvRoom, room_id)
    if not r:
        raise HTTPException(404, "Raum nicht gefunden")
    await db.delete(r)
    await db.commit()
    return {"ok": True}


@router.post("/reset")
async def reset_plan(db: AsyncSession = Depends(get_db), current: User = Depends(require_power_manager)):
    """Plan von vorn beginnen: alle Räume, Treppen und Stockwerke weg (danach nur «EG»), alle Elemente vom Plan genommen.
    Das Gebäude (Name, Grundfläche), Codes, Standorte (Möbel/Ebene) und Zuordnungen bleiben unberührt."""
    n_rooms = await db.scalar(select(func.count(InvRoom.id))) or 0
    await db.execute(delete(InvRoom))
    await db.execute(delete(InvFloor))
    cleared = {"plan_x": None, "plan_y": None, "plan_w": None, "plan_h": None, "plan_floor_id": None}
    await db.execute(update(MachineLocation).values(**cleared))
    await db.execute(update(InvFurniture).values(plan_rot=None, **cleared))
    await db.execute(update(InvPlacement).values(plan_rot=None, **cleared))
    await plan_svc.get_floors(db)                                   # legt «EG» neu an
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated, f"Plan zurückgesetzt ({n_rooms} Räume/Treppen entfernt)", user_id=current.id)
    return await plan_svc.build_plan(db)


@router.get("")
async def get_plan(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    data = await plan_svc.build_plan(db)
    await db.commit()                    # legt beim ersten Aufruf die Raumzeile an
    return data


@router.put("/room")
async def update_room(payload: RoomUpdate, db: AsyncSession = Depends(get_db),
                      current: User = Depends(require_power_manager)):
    room = await plan_svc.get_room(db)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is not None:
            setattr(room, k, v)
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated,
                      f"Plan «{room.name}»: Raum {room.width_cm:g} × {room.height_cm:g} cm",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return plan_svc.room_dict(room)


@router.patch("/{kind}/{item_id}")
async def place(kind: Literal["area", "furniture", "machine"], item_id: int, payload: RectUpdate,
                db: AsyncSession = Depends(get_db), _: User = Depends(require_power_manager)):
    """Bereich, Moebel oder Maschine auf dem Plan setzen, verschieben, drehen, in der Groesse aendern oder entfernen."""
    if kind == "area":
        obj = await db.get(MachineLocation, item_id)
    elif kind == "furniture":
        obj = await db.get(InvFurniture, item_id)
        if obj is not None and obj.number == 0:
            raise HTTPException(400, "«Im Bereich, ohne Möbel» hat keinen eigenen Platz auf dem Plan")
    else:
        if not await db.get(Machine, item_id):
            raise HTTPException(404, "Maschine nicht gefunden")
        obj = await db.get(InvPlacement, item_id)
        if obj is None and not payload.remove:
            obj = InvPlacement(machine_id=item_id)
            db.add(obj)
        elif obj is None:
            return {"plan": None}
    if obj is None:
        raise HTTPException(404, "Nicht gefunden")
    if payload.remove:
        x = y = w = h = rot = None
    else:
        if not plan_svc.valid_rect(payload.x, payload.y, payload.w, payload.h, payload.rot):
            raise HTTPException(400, "Ungültige Position oder Grösse")
        x, y, w, h, rot = payload.x, payload.y, payload.w, payload.h, (payload.rot or 0.0) % 360
    floors = await _floor_ids(db)
    if payload.floor_id is not None and payload.floor_id not in floors:
        raise HTTPException(400, "Stockwerk nicht gefunden")
    if payload.remove:
        floor_id = None
    else:
        floor_id = payload.floor_id if payload.floor_id is not None else (
            obj.plan_floor_id if obj.plan_floor_id in floors else (await plan_svc.get_floors(db))[0].id)
    obj.plan_x, obj.plan_y, obj.plan_w, obj.plan_h = x, y, w, h
    obj.plan_floor_id = floor_id
    if kind != "area":                    # Bereiche werden nicht gedreht (nur Rechteck)
        obj.plan_rot = rot
    await db.commit()
    return {"plan": plan_svc.rect(x, y, w, h, rot, floor_id)}
