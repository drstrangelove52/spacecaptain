"""
Inventar-Modul, Etappe 3: oeffentliche Nur-Lese-Sicht fuer Gaeste (ohne Anmeldung).

Ziel der QR-Codes auf Moebeln, Ebenen und Werkzeug (`/inventar.html?code=…` bzw. `?item=…`) und der Suche «Wo ist …?».
Es gibt hier nur GET-Endpunkte; ausgemustertes Werkzeug wird nicht gezeigt. Wie alle Inventar-Endpunkte ist die Sicht
mit der Einstellung `inventory_enabled` ein-/ausschaltbar (aus = 404). Sie ist bewusst schlanker als `/api/inventory`.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MachineLocation
from app.models_inventory import InvFurniture, InvLevel, InvItem, InvItemStatus, InvFloorImage
from app.routers import inventory as admin
from app.services import inventory as inv
from app.services import inventory_plan as plan_svc
from app.services.system_settings import get_system_settings


async def require_public_inventory(db: AsyncSession = Depends(get_db)) -> None:
    if not (await get_system_settings(db)).inventory_enabled:
        raise HTTPException(404, "Das Inventar ist nicht aktiviert")


router = APIRouter(prefix="/inventory-public", tags=["inventory-public"],
                   dependencies=[Depends(require_public_inventory)])


def _visible(item: dict) -> bool:
    return item.get("status") != InvItemStatus.ausgemustert.value


def _guest_item(d: dict) -> dict:
    pos = d.get("position")
    return {"id": d["id"], "name": d["name"], "description": d["description"], "quantity": d["quantity"],
            "status": d["status"],
            "place": pos and {"code": pos["code"], "path": pos["path"], "area": pos["area"], "color": pos["color"]}}


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    """Bereiche mit ihren Moebeln zum Durchstoebern (nur Bereiche mit Kuerzel)."""
    areas = (await db.execute(select(MachineLocation).where(MachineLocation.code.is_not(None))
                              .order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    furns = (await db.execute(select(InvFurniture).where(InvFurniture.number > 0)
                              .order_by(InvFurniture.number))).scalars().all()
    by_area: dict[int, list] = {}
    for f in furns:
        by_area.setdefault(f.area_id, []).append(f)
    return [{"name": a.name, "code": a.code, "color": a.color,
             "furniture": [{"code": inv.short_code(a.code, f.number), "title": inv.furniture_title(f)}
                           for f in by_area.get(a.id, [])]} for a in areas]


@router.get("/search")
async def search(q: str = Query("", max_length=100), db: AsyncSession = Depends(get_db)):
    res = await admin.search(q=q, limit=30, db=db, _=None)
    out = []
    for r in res:
        if r["type"] == "tool":
            if _visible(r):
                out.append({"type": "tool", **_guest_item(r)})
        elif r["type"] == "furniture":
            out.append({"type": "furniture", "name": r["name"], "code": r["code"], "path": r["path"], "color": r["color"]})
        else:
            out.append({"type": "machine", "id": r["id"], "name": r["name"], "path": r["path"], "color": r["color"],
                        "code": (r.get("stands_on") or {}).get("code")})
    return out


@router.get("/code/{code}")
async def by_code(code: str, db: AsyncSession = Depends(get_db)):
    """Inhalt eines Bereichs, Moebels, einer Ebene oder Position: Werkzeug und darauf stehende Maschinen."""
    res = await admin.by_code(code=code, db=db, _=None)
    area = await db.scalar(select(MachineLocation).where(MachineLocation.name == res["area"]))
    machines = []
    if area is not None and res["scope"] in ("area", "furniture", "level"):
        for r in (await db.execute(admin._MACHINE_JOIN.where(admin.Machine.area_id == area.id)
                                   .order_by(admin.Machine.name))).all():
            d = admin._machine_dict(r)
            so = d["stands_on"]
            lvl_code = so and so["level"] and so["level"]["code"]
            ok = (res["scope"] == "area"
                  or (res["scope"] == "furniture" and so and so["code"] == res["code"])
                  or (res["scope"] == "level" and lvl_code == res["code"]))
            if ok:
                machines.append({"id": d["id"], "name": d["name"], "path": d["path"], "category": d["category"],
                                 "code": (lvl_code or (so and so["code"])) or None})
    return {"code": res["code"], "scope": res["scope"], "area": res["area"], "color": res["color"],
            "items": [_guest_item(i) for i in res["items"] if _visible(i)], "machines": machines}


@router.get("/items/{item_id}")
async def item(item_id: int, db: AsyncSession = Depends(get_db)):
    d = await admin.get_item(item_id=item_id, db=db, _=None)
    if not _visible(d):
        raise HTTPException(404, "Werkzeug nicht gefunden")
    return _guest_item(d)


@router.get("/plan")
async def plan(db: AsyncSession = Depends(get_db)):
    """Bauplan fuer Gaeste: Raum und nur die Elemente, die schon auf dem Plan stehen."""
    data = await plan_svc.build_plan(db, only_placed=True)
    await db.commit()
    return data


@router.get("/plan/floors/{floor_id}/background")
async def plan_background(floor_id: int, db: AsyncSession = Depends(get_db)):
    """Grundriss-Bild eines Stockwerks für die Gäste-Ansicht (derselbe Plan, den sie auch sehen)."""
    img = await db.get(InvFloorImage, floor_id)
    if img is None:
        raise HTTPException(404, "Kein Grundriss hinterlegt")
    return Response(content=img.data, media_type=img.content_type, headers={"Cache-Control": "public, max-age=86400"})
