"""Inventar Etappe 4: Bauplan (Raum, Bereiche, Möbel, Maschinen als Rechtecke)."""
from sqlalchemy import select, delete

from app.models_inventory import InvPlacement, InvFurniture, InvPlan
from tests.test_inventory_machines import _setup, _area_id, _machines


async def _fill(client, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    t = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": laser, "kind": "tisch", "name": "Tisch 1"})).json()
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    return laser, t, mid


async def test_plan_starts_empty_with_default_room(client, enabled, power, db):
    await _fill(client, power, db)
    p = (await client.get("/api/inventory/plan", headers=power)).json()
    assert p["room"] == {"name": "Makerspace", "width_cm": 1500.0, "height_cm": 1000.0}
    assert all(a["plan"] is None for a in p["areas"]) and all(f["plan"] is None for f in p["furniture"])
    assert [f["code"] for f in p["furniture"]] == ["LAS-M01"]               # M00 erscheint nicht
    assert "Lasercutter" in [m["name"] for m in p["machines"]]


async def test_place_move_resize_and_remove(client, enabled, power, db):
    laser, t, mid = await _fill(client, power, db)
    r = await client.patch(f"/api/inventory/plan/area/{laser}", headers=power, json={"x": 100, "y": 50, "w": 400, "h": 300})
    assert r.status_code == 200 and r.json()["plan"] == {"x": 100, "y": 50, "w": 400, "h": 300, "rot": 0.0}
    r = await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power,
                           json={"x": 120, "y": 60, "w": 160, "h": 80, "rot": 450})
    assert r.json()["plan"]["rot"] == 90.0                                  # auf 0–359° normalisiert
    r = await client.patch(f"/api/inventory/plan/machine/{mid}", headers=power, json={"x": 130, "y": 70, "w": 80, "h": 60})
    assert r.status_code == 200
    p = (await client.get("/api/inventory/plan", headers=power)).json()
    assert [a["plan"]["w"] for a in p["areas"] if a["plan"]] == [400]
    assert [m["name"] for m in p["machines"] if m["plan"]] == ["Lasercutter"]
    assert [f["plan"]["h"] for f in p["furniture"]] == [80]
    # vom Plan nehmen
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"remove": True})
    assert (await client.get("/api/inventory/plan", headers=power)).json()["furniture"][0]["plan"] is None
    # Maschinen-Platz bleibt, auch wenn sie das Möbel verlässt
    pl = await db.get(InvPlacement, mid)
    assert pl.plan_x == 130


async def test_plan_validation_roles_and_zero_furniture(client, enabled, manager, power, db):
    laser, t, mid = await _fill(client, power, db)
    bad = {"x": 0, "y": 0, "w": 1, "h": 50}
    assert (await client.patch(f"/api/inventory/plan/area/{laser}", headers=power, json=bad)).status_code == 400
    assert (await client.patch(f"/api/inventory/plan/area/{laser}", headers=manager, json={"x": 0, "y": 0, "w": 50, "h": 50})).status_code == 403
    assert (await client.get("/api/inventory/plan", headers=manager)).status_code == 200      # lesen darf jeder
    m00 = (await db.execute(select(InvFurniture).where(InvFurniture.number == 0))).scalars().first()
    assert (await client.patch(f"/api/inventory/plan/furniture/{m00.id}", headers=power, json={"x": 0, "y": 0, "w": 50, "h": 50})).status_code == 400
    assert (await client.patch("/api/inventory/plan/machine/99999", headers=power, json={"x": 0, "y": 0, "w": 50, "h": 50})).status_code == 404
    assert (await client.put("/api/inventory/plan/room", headers=manager, json={"width_cm": 800})).status_code == 403


async def test_room_update_is_logged(client, enabled, power, db):
    from app.models import ActivityLog, LogType
    await _fill(client, power, db)
    r = await client.put("/api/inventory/plan/room", headers=power, json={"name": "Neue Halle", "width_cm": 2000, "height_cm": 1200})
    assert r.json() == {"name": "Neue Halle", "width_cm": 2000.0, "height_cm": 1200.0}
    assert (await client.put("/api/inventory/plan/room", headers=power, json={"width_cm": 10})).status_code == 422
    logs = (await db.execute(select(ActivityLog).where(ActivityLog.type == LogType.inventory_plan_updated))).scalars().all()
    assert len(logs) == 1


async def test_public_plan_shows_only_placed_elements(client, enabled, power, db):
    laser, t, mid = await _fill(client, power, db)
    empty = (await client.get("/api/inventory-public/plan")).json()
    assert empty["areas"] == [] and empty["furniture"] == [] and empty["machines"] == []
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 10, "y": 10, "w": 100, "h": 50})
    pub = (await client.get("/api/inventory-public/plan")).json()
    assert [f["code"] for f in pub["furniture"]] == ["LAS-M01"] and pub["room"]["width_cm"] == 1500.0


async def test_plan_survives_backup(client, enabled, power, admin, db):
    laser, t, mid = await _fill(client, power, db)
    await client.put("/api/inventory/plan/room", headers=power, json={"name": "Halle", "width_cm": 1800, "height_cm": 900})
    await client.patch(f"/api/inventory/plan/area/{laser}", headers=power, json={"x": 5, "y": 5, "w": 300, "h": 200})
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 20, "y": 20, "w": 120, "h": 60, "rot": 90})
    await client.patch(f"/api/inventory/plan/machine/{mid}", headers=power, json={"x": 30, "y": 30, "w": 70, "h": 50})
    data = (await client.get("/api/backup/export", headers=admin)).json()
    assert data["inventory"]["room"]["width_cm"] == 1800.0
    # alles zurücksetzen und wieder einspielen
    for model in (InvPlacement,):
        await db.execute(delete(model))
    await db.execute(delete(InvPlan))
    f = await db.get(InvFurniture, t["id"])
    f.plan_x = f.plan_y = f.plan_w = f.plan_h = f.plan_rot = None
    await db.commit()
    r = await client.post("/api/backup/import", headers=admin, json=data)
    assert r.status_code == 200, r.text
    p = (await client.get("/api/inventory/plan", headers=power)).json()
    assert p["room"]["name"] == "Halle"
    assert p["furniture"][0]["plan"]["rot"] == 90.0 and p["furniture"][0]["plan"]["w"] == 120
    assert [m["plan"]["w"] for m in p["machines"] if m["plan"]] == [70]
    assert [a["plan"]["w"] for a in p["areas"] if a["plan"]] == [300]
