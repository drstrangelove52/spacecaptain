"""
Inventar-Modul: Backup und Restore (Sektion «inventory» im JSON-Backup).

Alle Verweise laufen ueber natuerliche Schluessel statt DB-IDs, damit ein Restore auf einer anderen Instanz stimmt:
  Bereich → Name, Moebel → (Bereich, Nummer), Ebene/Position → Nummern, Maschine → Name.
Kompatibilitaet (siehe CLAUDE.md «Backup-Kompatibilitaetsregeln»): fehlt die Sektion oder ein Feld, wird sie bzw. es
uebersprungen (`.get()` mit Vorgabewert); aeltere Backups bleiben importierbar.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineLocation, Machine
from app.models_inventory import (InvFurniture, InvLevel, InvPosition, InvItem, InvPlacement,
                                  FurnitureKind, InvItemStatus)
from app.services import inventory as inv

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

    out_furn = []
    for f in furns:
        if f.number == 0 or f.area_id not in area_name:          # M00 entsteht automatisch
            continue
        out_furn.append({
            "area": area_name[f.area_id], "number": f.number, "kind": f.kind.value, "name": f.name, "note": f.note,
            "label_outdated": bool(f.label_outdated),
            "plan_x": f.plan_x, "plan_y": f.plan_y, "plan_w": f.plan_w, "plan_h": f.plan_h, "plan_rot": f.plan_rot,
            "levels": [{
                "number": l.number, "label": l.label,
                "positions": [{"number": p.number, "label": p.label} for p in pos_by_lvl.get(l.id, []) if p.number > 0],
            } for l in lvl_by_furn.get(f.id, []) if l.number > 0 or any(p.number > 0 for p in pos_by_lvl.get(l.id, []))],
        })

    items = (await db.execute(select(InvItem).order_by(InvItem.id))).scalars().all()
    out_items = [{
        "name": i.name, "synonyms": i.synonyms, "description": i.description, "quantity": i.quantity,
        "status": i.status.value, "place": place_by_pos.get(i.position_id) if i.position_id else None,
    } for i in items]

    machine_name = {m.id: m.name for m in (await db.execute(select(Machine))).scalars().all()}
    out_pl = []
    for pl in (await db.execute(select(InvPlacement).order_by(InvPlacement.machine_id))).scalars().all():
        if pl.machine_id not in machine_name:
            continue
        f = furn_by_id.get(pl.furniture_id) if pl.furniture_id else None
        out_pl.append({
            "machine": machine_name[pl.machine_id],
            "furniture": {"area": area_name[f.area_id], "number": f.number} if f and f.area_id in area_name else None,
            "plan_x": pl.plan_x, "plan_y": pl.plan_y, "plan_w": pl.plan_w, "plan_h": pl.plan_h, "plan_rot": pl.plan_rot,
        })

    return {
        "areas": [{"name": a.name, "code": a.code, "color": a.color,
                   "plan_x": a.plan_x, "plan_y": a.plan_y, "plan_w": a.plan_w, "plan_h": a.plan_h}
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
                      plan_h=f.get("plan_h"), plan_rot=f.get("plan_rot"))
        if fo is None:
            fo = InvFurniture(area_id=area.id, number=f["number"], **fields)
            db.add(fo)
            await db.flush()
            furn_by_key[(area.id, f["number"])] = fo
            stats["inventory_furniture"] += 1
        elif overwrite:
            for k, v in fields.items():
                setattr(fo, k, v)
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
            continue
        new = InvItem(name=name[:150], synonyms=it.get("synonyms"), description=it.get("description"),
                      quantity=it.get("quantity", 1), status=_status(it.get("status")), position_id=pid)
        db.add(new)
        existing[(name.lower(), pid)] = new
        stats["inventory_items"] += 1
    await db.flush()

    # 4) Platzierung der Maschinen («steht auf»)
    machine_id = {m.name: m.id for m in (await db.execute(select(Machine))).scalars().all()}
    placed = {pl.machine_id: pl for pl in (await db.execute(select(InvPlacement))).scalars().all()}
    furn_ids = {(area_by_id[f.area_id], f.number): f.id for f in furn_by_id.values() if f.area_id in area_by_id}
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
        for k in ("plan_x", "plan_y", "plan_w", "plan_h", "plan_rot"):
            setattr(row, k, p.get(k))
    await db.flush()
