"""
Inventar-Modul, Etappe 4: Bauplan-Endpunkte (Teil von /api/inventory, gleiche Freischaltung).

Lesen: jeder Lab Manager. Zeichnen, Verschieben, Raum aendern: Power-Manager/Admin.
Verschieben ist Alltag und wird nicht einzeln protokolliert; nur Aenderungen am Raum stehen im Aktivitaetslog.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation, Machine, User, LogType
from app.models_inventory import InvFurniture, InvPlacement
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
    remove: bool = False                 # True = vom Plan nehmen


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
    obj.plan_x, obj.plan_y, obj.plan_w, obj.plan_h = x, y, w, h
    if kind != "area":                    # Bereiche werden nicht gedreht (nur Rechteck)
        obj.plan_rot = rot
    await db.commit()
    return {"plan": plan_svc.rect(x, y, w, h, rot)}
