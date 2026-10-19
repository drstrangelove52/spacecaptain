"""
Inventar-Modul, Etappe 4: Bauplan-Endpunkte (Teil von /api/inventory, gleiche Freischaltung).

Lesen: jeder Lab Manager. Zeichnen, Verschieben, Raum aendern: Power-Manager/Admin.
Verschieben ist Alltag und wird nicht einzeln protokolliert; nur Aenderungen am Raum stehen im Aktivitaetslog.
"""
import asyncio
import io
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, Machine, User, LogType
from sqlalchemy import select, func, update, delete
from app.models_inventory import InvFurniture, InvPlacement, InvFloor, InvRoom, InvFloorImage
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
    wall_cm: Optional[float] = Field(default=None, ge=0, le=100)          # Standard-Wanddicke; 0 = nur Umriss


class BackgroundUpdate(BaseModel):
    x: Optional[float] = Field(default=None, ge=-100000, le=100000)
    y: Optional[float] = Field(default=None, ge=-100000, le=100000)
    w: Optional[float] = Field(default=None, ge=100, le=100000)
    h: Optional[float] = Field(default=None, ge=100, le=100000)
    opacity: Optional[float] = Field(default=None, ge=0.05, le=1)
    rot: Optional[float] = Field(default=None, ge=-720, le=720)          # Grad, wird auf 0–359,99 normalisiert


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
    flip: Optional[int] = Field(default=None, ge=0, le=3)   # Tür spiegeln: 1 = Anschlag, 2 = Aufschlagseite
    wall_cm: Optional[float] = Field(default=None, ge=0, le=100)   # eigene Wanddicke dieses Raums; null = Standard des Gebäudes
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
    await db.execute(delete(InvFloorImage).where(InvFloorImage.floor_id == floor_id))
    await db.delete(f)
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated, f"Plan: Stockwerk «{f.name}» gelöscht", user_id=current.id)
    return {"ok": True}


# ── Hintergrund-Grundriss (Bild zum Abpausen) ──
MAX_UPLOAD = 12 * 1024 * 1024
MAX_SIDE = 2400


def _prepare_image(raw: bytes) -> tuple:
    """Prüft das Bild, verkleinert es auf höchstens 2400 px und speichert es als JPEG. Gibt (Bytes, Breite, Höhe) zurück."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(400, "Das ist kein lesbares Bild (JPG oder PNG)")
    if img.format not in ("JPEG", "PNG"):
        raise HTTPException(400, "Nur JPG oder PNG")
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue(), img.width, img.height


async def _floor_or_404(db: AsyncSession, floor_id: int) -> InvFloor:
    f = await db.get(InvFloor, floor_id)
    if not f:
        raise HTTPException(404, "Stockwerk nicht gefunden")
    return f


@router.put("/floors/{floor_id}/background")
async def upload_background(floor_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
                            current: User = Depends(require_power_manager)):
    f = await _floor_or_404(db, floor_id)
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Das Bild ist zu gross (höchstens 12 MB)")
    data, w, h = await asyncio.to_thread(_prepare_image, raw)
    img = await db.get(InvFloorImage, floor_id)
    if img is None:
        db.add(InvFloorImage(floor_id=floor_id, data=data, content_type="image/jpeg"))
    else:
        img.data, img.content_type = data, "image/jpeg"
    room = await plan_svc.get_room(db)
    if not f.bg_w:                                           # erste Platzierung: so breit wie das Gebäude, oben links
        f.bg_x, f.bg_y, f.bg_w = 0.0, 0.0, float(room.width_cm)
        f.bg_h = f.bg_w * h / w
    else:                                                    # ersetzen: Breite behalten, Seitenverhältnis des neuen Bildes
        f.bg_h = f.bg_w * h / w
    f.bg_version = (f.bg_version or 0) + 1
    await db.commit()
    await log_svc.log(db, LogType.inventory_plan_updated, f"Plan: Grundriss für «{f.name}» hochgeladen ({len(data) // 1024} KB)", user_id=current.id)
    return plan_svc.floor_out(f)


@router.get("/floors/{floor_id}/background")
async def get_background(floor_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    img = await db.get(InvFloorImage, floor_id)
    if img is None:
        raise HTTPException(404, "Kein Grundriss hinterlegt")
    return Response(content=img.data, media_type=img.content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.patch("/floors/{floor_id}/background")
async def update_background(floor_id: int, payload: BackgroundUpdate, db: AsyncSession = Depends(get_db),
                            _: User = Depends(require_power_manager)):
    f = await _floor_or_404(db, floor_id)
    if not f.bg_version:
        raise HTTPException(404, "Kein Grundriss hinterlegt")
    ch = payload.model_dump(exclude_unset=True)
    for src, dst in (("x", "bg_x"), ("y", "bg_y"), ("w", "bg_w"), ("h", "bg_h"), ("opacity", "bg_opacity")):
        if ch.get(src) is not None:
            setattr(f, dst, ch[src])
    if ch.get("rot") is not None:
        f.bg_rot = round(ch["rot"] % 360, 2)
    await db.commit()
    return plan_svc.floor_out(f)


@router.delete("/floors/{floor_id}/background")
async def delete_background(floor_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_power_manager)):
    f = await _floor_or_404(db, floor_id)
    await db.execute(delete(InvFloorImage).where(InvFloorImage.floor_id == floor_id))
    f.bg_x = f.bg_y = f.bg_w = f.bg_h = None
    f.bg_version = 0
    await db.commit()
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
    if "flip" in given and p.flip is not None:
        r.flip = p.flip
    if "wall_cm" in given:
        r.wall_cm = p.wall_cm if r.kind == "raum" else None
    if r.kind != "raum":
        r.points = None                                       # nur Räume haben Eckpunkte
    if r.kind != "tuer":
        r.flip = 0                                            # nur Türen haben einen Schwenk


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
    await db.execute(delete(InvFloorImage))
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
