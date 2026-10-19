"""
Inventar-Modul, Etappe 4: Bauplan (Raum, Bereiche, Moebel, Maschinen als Rechtecke in cm).

Der Plan liegt in vorhandenen Spalten: `machine_locations.plan_*` (Bereich), `inv_furniture.plan_*` (Moebel),
`inv_placements.plan_*` (Maschine); der Raum selbst in `inv_plan` (eine Zeile). Ein Element ist «auf dem Plan», sobald
plan_x/plan_y/plan_w/plan_h gesetzt sind. Codes und Zuordnungen haengen nicht am Plan: zieht der Makerspace um,
wird nur neu gezeichnet.
"""
import json
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineLocation, Machine
from app.models_inventory import InvFurniture, InvPlacement, InvPlan, InvFloor, InvRoom
from app.services import inventory as inv

DEFAULT_ROOM = {"name": "Makerspace", "width_cm": 1500.0, "height_cm": 1000.0}
MIN_SIZE, MAX_SIZE, MAX_POS = 5.0, 20000.0, 50000.0
DEFAULT_COLOR = "#22d3ee"


async def get_room(db: AsyncSession) -> InvPlan:
    row = await db.get(InvPlan, 1)
    if row is None:
        row = InvPlan(id=1, **DEFAULT_ROOM)
        db.add(row)
        await db.flush()
    return row


async def get_floors(db: AsyncSession) -> list:
    """Stockwerke in Reihenfolge; legt beim ersten Aufruf «EG» an."""
    rows = (await db.execute(select(InvFloor).order_by(InvFloor.sort_order, InvFloor.id))).scalars().all()
    if not rows:
        f = InvFloor(name="EG", sort_order=0)
        db.add(f)
        await db.flush()
        rows = [f]
    return list(rows)


ROOM_KINDS = ("raum", "treppe", "tuer", "durchgang")
MAX_POINTS = 60


def parse_points(raw) -> Optional[list]:
    """JSON-Text → [[x, y], …] oder None (Rechteck)."""
    if not raw:
        return None
    try:
        pts = json.loads(raw)
    except ValueError:
        return None
    ok = isinstance(pts, list) and len(pts) >= 3 and all(isinstance(q, list) and len(q) == 2 for q in pts)
    return [[float(q[0]), float(q[1])] for q in pts] if ok else None


def points_valid(pts) -> bool:
    if not isinstance(pts, list) or not 3 <= len(pts) <= MAX_POINTS:
        return False
    for q in pts:
        if not (isinstance(q, (list, tuple)) and len(q) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= MAX_POS for v in q)):
            return False
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return max(xs) - min(xs) >= MIN_SIZE and max(ys) - min(ys) >= MIN_SIZE


def points_bbox(pts) -> tuple:
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def room_out(r: InvRoom) -> dict:
    return {"id": r.id, "floor_id": r.floor_id, "name": r.name, "kind": r.kind, "link_floor_id": r.link_floor_id,
            "points": parse_points(r.points), "flip": r.flip or 0, "plan": rect(r.plan_x, r.plan_y, r.plan_w, r.plan_h, r.plan_rot)}


def room_dict(r: InvPlan) -> dict:
    return {"name": r.name, "width_cm": r.width_cm, "height_cm": r.height_cm}


def rect(x, y, w, h, rot=None, floor_id=None) -> Optional[dict]:
    if None in (x, y, w, h):
        return None
    out = {"x": x, "y": y, "w": w, "h": h, "rot": rot or 0.0}
    if floor_id is not None:
        out["floor_id"] = floor_id
    return out


def valid_rect(x, y, w, h, rot) -> bool:
    vals = (x, y, w, h, rot or 0.0)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
        return False
    return MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE and abs(x) <= MAX_POS and abs(y) <= MAX_POS


async def build_plan(db: AsyncSession, only_placed: bool = False) -> dict:
    """Alles, was der Plan zeichnet. `only_placed` (Gaeste): nur Elemente, die schon auf dem Plan stehen."""
    room = await get_room(db)
    floors = await get_floors(db)
    first = floors[0].id
    fl = lambda v: v if v in {f.id for f in floors} else first          # fehlendes/veraltetes Stockwerk → erstes
    rooms = (await db.execute(select(InvRoom).order_by(InvRoom.floor_id, InvRoom.id))).scalars().all()
    areas = (await db.execute(select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    area_by_id = {a.id: a for a in areas}
    furns = (await db.execute(select(InvFurniture).where(InvFurniture.number > 0)
                              .order_by(InvFurniture.area_id, InvFurniture.number))).scalars().all()
    machines = (await db.execute(select(Machine).order_by(Machine.name))).scalars().all()
    placements = {p.machine_id: p for p in (await db.execute(select(InvPlacement))).scalars().all()}

    out_areas = [{"id": a.id, "name": a.name, "code": a.code, "color": a.color or DEFAULT_COLOR,
                  "plan": rect(a.plan_x, a.plan_y, a.plan_w, a.plan_h, None, fl(a.plan_floor_id))} for a in areas]
    out_furn = []
    for f in furns:
        a = area_by_id.get(f.area_id)
        if a is None:
            continue
        out_furn.append({"id": f.id, "code": inv.short_code(a.code, f.number), "title": inv.furniture_title(f),
                         "kind": f.kind.value, "area_id": a.id, "area": a.name, "color": a.color or DEFAULT_COLOR,
                         "plan": rect(f.plan_x, f.plan_y, f.plan_w, f.plan_h, f.plan_rot, fl(f.plan_floor_id))})
    out_mach = []
    for m in machines:
        a = area_by_id.get(m.area_id) if m.area_id else None
        pl = placements.get(m.id)
        out_mach.append({"id": m.id, "name": m.name, "category": m.category, "area_id": a.id if a else None,
                         "area": a.name if a else None, "color": (a.color if a else None) or DEFAULT_COLOR,
                         "plan": rect(pl.plan_x, pl.plan_y, pl.plan_w, pl.plan_h, pl.plan_rot, fl(pl.plan_floor_id)) if pl else None})
    if only_placed:
        out_areas = [x for x in out_areas if x["plan"]]
        out_furn = [x for x in out_furn if x["plan"]]
        out_mach = [x for x in out_mach if x["plan"]]
    return {"room": room_dict(room), "floors": [{"id": f.id, "name": f.name} for f in floors],
            "rooms": [room_out(r) for r in rooms], "areas": out_areas, "furniture": out_furn, "machines": out_mach}
