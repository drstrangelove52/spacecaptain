"""
Inventar-Modul: Backup und Restore (Sektion «inventory» im JSON-Backup).

Alle Verweise laufen ueber natuerliche Schluessel statt DB-IDs, damit ein Restore auf einer anderen Instanz stimmt:
  Bereich → Name, Moebel → (Bereich, Nummer), Ebene/Position → Nummern, Maschine → Name.
Kompatibilitaet (siehe CLAUDE.md «Backup-Kompatibilitaetsregeln»): fehlt die Sektion oder ein Feld, wird sie bzw. es
uebersprungen (`.get()` mit Vorgabewert); aeltere Backups bleiben importierbar.
"""
import base64
import json
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineLocation, Machine, MachineOwner
from app.models_inventory import (InvFurniture, InvLevel, InvPosition, InvItem, InvPlacement,
                                  FurnitureKind, InvItemStatus, InvPlan, InvFloor, InvRoom, InvFloorImage)
from app.services import inventory as inv
from app.services import inventory_plan as plan_svc

_PLAN = ("plan_x", "plan_y", "plan_w", "plan_h")


def _kind(value) -> FurnitureKind:
    try:
        return FurnitureKind(value)
    except ValueError:
        return FurnitureKind.schrank


def _status(value) -> InvItemStatus:
    try:
        return InvItemStatus(value)
    except ValueError:
        return InvItemStatus.aktiv


# ── Export ───────────────────────────────────────────────────────────────────
async def export_inventory(db: AsyncSession) -> dict:
    areas = (await db.execute(select(MachineLocation).order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    area_name = {a.id: a.name for a in areas}
    furns = (await db.execute(select(InvFurniture).order_by(InvFurniture.area_id, InvFurniture.number))).scalars().all()
    lvls = (await db.execute(select(InvLevel).order_by(InvLevel.furniture_id, InvLevel.number))).scalars().all()
    poss = (await db.execute(select(InvPosition).order_by(InvPosition.level_id, InvPosition.number))).scalars().all()

    lvl_by_furn: dict[int, list] = {}
    for l in lvls:
        lvl_by_furn.setdefault(l.furniture_id, []).append(l)
    pos_by_lvl: dict[int, list] = {}
    for p in poss:
        pos_by_lvl.setdefault(p.level_id, []).append(p)

    # Position → (Bereich, Moebel, Ebene, Position) fuer Werkzeug-Verweise
    furn_by_id = {f.id: f for f in furns}
    lvl_by_id = {l.id: l for l in lvls}
    place_by_pos = {}
    for p in poss:
        l = lvl_by_id.get(p.level_id)
        f = furn_by_id.get(l.furniture_id) if l else None
        if f and f.area_id in area_name:
            place_by_pos[p.id] = {"area": area_name[f.area_id], "furniture": f.number, "level": l.number, "position": p.number}

    floors = (await db.execute(select(InvFloor).order_by(InvFloor.sort_order, InvFloor.id))).scalars().all()
    floor_name = {f.id: f.name for f in floors}
    images = {i.floor_id: i for i in (await db.execute(select(InvFloorImage))).scalars().all()}
    rooms = (await db.execute(select(InvRoom).order_by(InvRoom.floor_id, InvRoom.id))).scalars().all()

    out_furn = []
    for f in furns:
        if f.number == 0 or f.area_id not in area_name:          # M00 entsteht automatisch
            continue
        out_furn.append({
            "area": area_name[f.area_id], "number": f.number, "kind": f.kind.value, "name": f.name, "note": f.note,
            "label_outdated": bool(f.label_outdated),
            "plan_x": f.plan_x, "plan_y": f.plan_y, "plan_w": f.plan_w, "plan_h": f.plan_h, "plan_rot": f.plan_rot,
            "plan_floor": floor_name.get(f.plan_floor_id),
            "levels": [{
                "number": l.number, "label": l.label,
                "positions": [{"number": p.number, "label": p.label} for p in pos_by_lvl.get(l.id, []) if p.number > 0],
            } for l in lvl_by_furn.get(f.id, []) if l.number > 0 or any(p.number > 0 for p in pos_by_lvl.get(l.id, []))],
        })

    items = (await db.execute(select(InvItem).order_by(InvItem.id))).scalars().all()
    owner_name = {o.id: o.name for o in (await db.execute(select(MachineOwner))).scalars().all()}
    out_items = [{
        "name": i.name, "synonyms": i.synonyms, "description": i.description, "quantity": i.quantity,
        "status": i.status.value, "place": place_by_pos.get(i.position_id) if i.position_id else None,
        "serial_number": i.serial_number, "purchase_date": i.purchase_date.isoformat() if i.purchase_date else None,
        "value_new": i.value_new, "owner": owner_name.get(i.owner_id) if i.owner_id else None,
    } for i in items]

    machine_name = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    out_pl = []
    for pl in (await db.execute(select(InvPlacement).order_by(InvPlacement.machine_id))).scalars().all():
        if pl.machine_id not in machine_name:
            continue
        f = furn_by_id.get(pl.furniture_id) if pl.furniture_id else None
        lv = lvl_by_id.get(pl.level_id) if pl.level_id else None
        out_pl.append({
            "machine": machine_name[pl.machine_id],
            "furniture": {"area": area_name[f.area_id], "number": f.number} if f and f.area_id in area_name else None,
            "level": lv.number if lv and f and lv.furniture_id == f.id and lv.number > 0 else None,
            "plan_x": pl.plan_x, "plan_y": pl.plan_y, "plan_w": pl.plan_w, "plan_h": pl.plan_h, "plan_rot": pl.plan_rot,
            "plan_floor": floor_name.get(pl.plan_floor_id),
        })

    room = await db.get(InvPlan, 1)
    return {
        "room": {"name": room.name, "width_cm": room.width_cm, "height_cm": room.height_cm, "wall_cm": room.wall_cm} if room else None,
        "floors": [{"name": f.name, "sort_order": f.sort_order,
                    "background": ({"x": f.bg_x, "y": f.bg_y, "w": f.bg_w, "h": f.bg_h, "opacity": f.bg_opacity,
                                    "image": base64.b64encode(images[f.id].data).decode("ascii")}
                                   if f.bg_version and f.id in images else None)} for f in floors],
        "rooms": [{"floor": floor_name[r.floor_id], "name": r.name, "kind": r.kind, "x": r.plan_x, "y": r.plan_y,
                   "w": r.plan_w, "h": r.plan_h, "rot": r.plan_rot, "link_floor": floor_name.get(r.link_floor_id),
                   "points": plan_svc.parse_points(r.points), "flip": r.flip or 0}
                  for r in rooms if r.floor_id in floor_name],
        "areas": [{"name": a.name, "code": a.code, "color": a.color,
                   "plan_x": a.plan_x, "plan_y": a.plan_y, "plan_w": a.plan_w, "plan_h": a.plan_h,
                   "plan_floor": floor_name.get(a.plan_floor_id)}
                  for a in areas if a.code or a.color or any(getattr(a, k) is not None for k in _PLAN)],
        "furniture": out_furn,
        "items": out_items,
        "placements": out_pl,
    }


# ── Import ───────────────────────────────────────────────────────────────────
async def import_inventory(data: Optional[dict], db: AsyncSession, overwrite: bool, stats: dict) -> None:
    """Spielt die Sektion «inventory» ein. Ohne `overwrite` bleibt Vorhandenes unberuehrt, Fehlendes wird ergaenzt.
    Laeuft in der Transaktion des Aufrufers (kein Commit)."""
    if not data:
        return
    for key in ("inventory_areas", "inventory_furniture", "inventory_levels", "inventory_items", "inventory_placements"):
        stats.setdefault(key, 0)

    r = data.get("room")
    if r and (overwrite or await db.get(InvPlan, 1) is None):
        room = await db.get(InvPlan, 1) or InvPlan(id=1)
        room.name = (r.get("name") or "Makerspace")[:100]
        room.width_cm = float(r.get("width_cm") or 1500.0)
        room.height_cm = float(r.get("height_cm") or 1000.0)
        room.wall_cm = float(r.get("wall_cm") or 20.0)
        db.add(room)

    # Stockwerke und Raeume des Plans (ueber Namen); Elemente verweisen weiter unten darauf
    floor_by_name = {f.name: f for f in (await db.execute(select(InvFloor))).scalars().all()}
    for f in data.get("floors", []) or []:
        created = False
        if f.get("name") and f["name"] not in floor_by_name:
            nf = InvFloor(name=str(f["name"])[:50], sort_order=int(f.get("sort_order") or 0))
            db.add(nf)
            await db.flush()
            floor_by_name[nf.name] = nf
            created = True
        bg = f.get("background")
        row = floor_by_name.get(f.get("name"))
        if bg and bg.get("image") and row is not None and (created or overwrite or not row.bg_version):
            try:
                blob = base64.b64decode(bg["image"])
            except ValueError:
                blob = b""
            if blob:
                img = await db.get(InvFloorImage, row.id)
                if img is None:
                    db.add(InvFloorImage(floor_id=row.id, data=blob, content_type="image/jpeg"))
                else:
                    img.data = blob
                row.bg_x, row.bg_y, row.bg_w, row.bg_h = bg.get("x") or 0.0, bg.get("y") or 0.0, bg.get("w") or 1000.0, bg.get("h") or 700.0
                row.bg_opacity = bg.get("opacity") if bg.get("opacity") is not None else 0.5
                row.bg_version = (row.bg_version or 0) + 1
    floor_id = lambda name: floor_by_name[name].id if name in floor_by_name else None
    have_rooms = {(r.floor_id, r.name): r for r in (await db.execute(select(InvRoom))).scalars().all()}
    for r in data.get("rooms", []) or []:
        fid = floor_id(r.get("floor"))
        if fid is None or not r.get("name"):
            continue
        row = have_rooms.get((fid, r["name"]))
        if row is None:
            row = InvRoom(floor_id=fid, name=str(r["name"])[:100])
            db.add(row)
            have_rooms[(fid, r["name"])] = row
        elif not overwrite:
            continue
        row.kind = r.get("kind") if r.get("kind") in plan_svc.ROOM_KINDS else "raum"
        pts = r.get("points")
        row.points = json.dumps(pts) if row.kind == "raum" and plan_svc.points_valid(pts) else None
        row.flip = int(r.get("flip") or 0) & 3 if row.kind == "tuer" else 0
        row.plan_x, row.plan_y = r.get("x") or 0.0, r.get("y") or 0.0
        row.plan_w, row.plan_h, row.plan_rot = r.get("w") or 300.0, r.get("h") or 300.0, r.get("rot") or 0.0
        row.link_floor_id = floor_id(r.get("link_floor"))

    areas = {a.name: a for a in (await db.execute(select(MachineLocation))).scalars().all()}
    used_codes = {a.code for a in areas.values() if a.code}

    # 1) Kuerzel, Farben, Plan der Bereiche (die Bereiche selbst kommen aus «machine_locations»)
    for a in data.get("areas", []) or []:
        row = areas.get(a.get("name"))
        if not row:
            continue
        code = (a.get("code") or "").strip().upper()
        if (code and inv.AREA_CODE_RE.match(code) and code != row.code
                and (row.code is None or overwrite) and code not in used_codes):
            used_codes.discard(row.code)
            row.code = code
            used_codes.add(code)
            stats["inventory_areas"] += 1
        if a.get("color") and (overwrite or not row.color):
            row.color = a["color"]
        for k in _PLAN:
            if a.get(k) is not None and (overwrite or getattr(row, k) is None):
                setattr(row, k, a[k])
        if a.get("plan_floor") and (overwrite or row.plan_floor_id is None):
            row.plan_floor_id = floor_id(a["plan_floor"])
    await db.flush()
    await inv.ensure_structure(db, commit=False)           # M00 je Bereich, Kuerzel-Umstellung, Maschinen → Bereich

    # 2) Moebel, Ebenen, Positionen
    furn_by_key = {(f.area_id, f.number): f for f in (await db.execute(select(InvFurniture))).scalars().all()}
    lvl_by_key = {(l.furniture_id, l.number): l for l in (await db.execute(select(InvLevel))).scalars().all()}
    pos_by_key = {(p.level_id, p.number): p for p in (await db.execute(select(InvPosition))).scalars().all()}

    for f in data.get("furniture", []) or []:
        area = areas.get(f.get("area"))
        if not area or not isinstance(f.get("number"), int) or f["number"] <= 0:
            continue
        fo = furn_by_key.get((area.id, f["number"]))
        fields = dict(kind=_kind(f.get("kind")), name=f.get("name"), note=f.get("note"),
                      label_outdated=bool(f.get("label_outdated", True)),
                      plan_x=f.get("plan_x"), plan_y=f.get("plan_y"), plan_w=f.get("plan_w"),
                      plan_h=f.get("plan_h"), plan_rot=f.get("plan_rot"), plan_floor_id=floor_id(f.get("plan_floor")))
        if fo is None:
            fo = InvFurniture(area_id=area.id, number=f["number"], **fields)
            db.add(fo)
            await db.flush()
            furn_by_key[(area.id, f["number"])] = fo
            stats["inventory_furniture"] += 1
        elif overwrite:
            for k, v in fields.items():
                setattr(fo, k, v)
        elif fo.plan_x is None and f.get("plan_x") is not None:        # ohne Überschreiben: nur fehlenden Planplatz ergänzen
            for k in ("plan_x", "plan_y", "plan_w", "plan_h", "plan_rot"):
                setattr(fo, k, f.get(k))
            fo.plan_floor_id = floor_id(f.get("plan_floor"))
        for lv in f.get("levels", []) or []:
            if not isinstance(lv.get("number"), int) or lv["number"] < 0:
                continue
            lo = lvl_by_key.get((fo.id, lv["number"]))
            if lo is None:
                lo = InvLevel(furniture_id=fo.id, number=lv["number"], label=lv.get("label"))
                db.add(lo)
                await db.flush()
                lvl_by_key[(fo.id, lv["number"])] = lo
                stats["inventory_levels"] += 1
            elif overwrite:
                lo.label = lv.get("label")
            for ps in lv.get("positions", []) or []:
                if not isinstance(ps.get("number"), int) or ps["number"] < 0:
                    continue
                po = pos_by_key.get((lo.id, ps["number"]))
                if po is None:
                    po = InvPosition(level_id=lo.id, number=ps["number"], label=ps.get("label"))
                    db.add(po)
                    await db.flush()
                    pos_by_key[(lo.id, ps["number"])] = po
                elif overwrite:
                    po.label = ps.get("label")
    await db.flush()
    await inv.ensure_structure(db, commit=False)           # E00/P00 fuer neu angelegte Moebel und Ebenen

    # 3) Werkzeug: Platz ueber natuerliche Schluessel aufloesen
    area_by_id = {a.id: a.name for a in areas.values()}
    furn_by_id = {f.id: f for f in (await db.execute(select(InvFurniture))).scalars().all()}
    lvl_by_id = {l.id: l for l in (await db.execute(select(InvLevel))).scalars().all()}
    pos_ids: dict[tuple, int] = {}
    for p in (await db.execute(select(InvPosition))).scalars().all():
        l = lvl_by_id.get(p.level_id)
        f = furn_by_id.get(l.furniture_id) if l else None
        if f and f.area_id in area_by_id:
            pos_ids[(area_by_id[f.area_id], f.number, l.number, p.number)] = p.id

    owner_id = {o.name: o.id for o in (await db.execute(select(MachineOwner))).scalars().all()}

    def accounting(it: dict) -> dict:
        try:
            pd = date.fromisoformat(it["purchase_date"]) if it.get("purchase_date") else None
        except (TypeError, ValueError):
            pd = None
        return dict(serial_number=it.get("serial_number"), purchase_date=pd, value_new=it.get("value_new"),
                    owner_id=owner_id.get(it.get("owner")) if it.get("owner") else None)

    existing = {}
    for it in (await db.execute(select(InvItem))).scalars().all():
        existing[((it.name or "").lower(), it.position_id)] = it
    for it in data.get("items", []) or []:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        pl = it.get("place") or None
        pid = pos_ids.get((pl.get("area"), pl.get("furniture"), pl.get("level"), pl.get("position"))) if pl else None
        row = existing.get((name.lower(), pid))
        if row is not None:
            if overwrite:
                row.synonyms, row.description = it.get("synonyms"), it.get("description")
                row.quantity, row.status = it.get("quantity", 1), _status(it.get("status"))
                for k, v in accounting(it).items():
                    setattr(row, k, v)
            continue
        new = InvItem(name=name[:150], synonyms=it.get("synonyms"), description=it.get("description"),
                      quantity=it.get("quantity", 1), status=_status(it.get("status")), position_id=pid,
                      **accounting(it))
        db.add(new)
        existing[(name.lower(), pid)] = new
        stats["inventory_items"] += 1
    await db.flush()

    # 4) Platzierung der Maschinen («steht auf»)
    machine_id = {m.name: m.id for m in (await db.execute(select(Machine))).scalars().all()}
    placed = {pl.machine_id: pl for pl in (await db.execute(select(InvPlacement))).scalars().all()}
    furn_ids = {(area_by_id[f.area_id], f.number): f.id for f in furn_by_id.values() if f.area_id in area_by_id}
    lvl_ids = {(l.furniture_id, l.number): l.id for l in (await db.execute(select(InvLevel))).scalars().all()}
    for p in data.get("placements", []) or []:
        mid = machine_id.get(p.get("machine"))
        if mid is None:
            continue
        ref = p.get("furniture") or None
        fid = furn_ids.get((ref.get("area"), ref.get("number"))) if ref else None
        row = placed.get(mid)
        if row is None:
            row = InvPlacement(machine_id=mid)
            db.add(row)
            placed[mid] = row
            stats["inventory_placements"] += 1
        elif not overwrite:
            continue
        row.furniture_id = fid
        row.level_id = lvl_ids.get((fid, p.get("level"))) if fid and p.get("level") else None
        for k in ("plan_x", "plan_y", "plan_w", "plan_h", "plan_rot"):
            setattr(row, k, p.get(k))
        row.plan_floor_id = floor_id(p.get("plan_floor"))
    await db.flush()
