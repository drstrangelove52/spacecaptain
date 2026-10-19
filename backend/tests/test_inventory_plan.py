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
    assert p["room"] == {"name": "Makerspace", "width_cm": 1500.0, "height_cm": 1000.0, "wall_cm": 0.0}
    assert all(a["plan"] is None for a in p["areas"]) and all(f["plan"] is None for f in p["furniture"])
    assert [f["code"] for f in p["furniture"]] == ["LAS-M01"]               # M00 erscheint nicht
    assert "Lasercutter" in [m["name"] for m in p["machines"]]


async def test_place_move_resize_and_remove(client, enabled, power, db):
    laser, t, mid = await _fill(client, power, db)
    r = await client.patch(f"/api/inventory/plan/area/{laser}", headers=power, json={"x": 100, "y": 50, "w": 400, "h": 300})
    assert r.status_code == 200 and {k: v for k, v in r.json()["plan"].items() if k != "floor_id"} == {"x": 100, "y": 50, "w": 400, "h": 300, "rot": 0.0}
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
    assert r.json() == {"name": "Neue Halle", "width_cm": 2000.0, "height_cm": 1200.0, "wall_cm": 0.0}
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


# ── Stockwerke, Räume, Treppen ───────────────────────────────────────────────
async def test_plan_has_a_default_floor_and_elements_land_on_it(client, enabled, power, db):
    laser, t, mid = await _fill(client, power, db)
    p = (await client.get("/api/inventory/plan", headers=power)).json()
    assert [f["name"] for f in p["floors"]] == ["EG"] and p["rooms"] == []
    eg = p["floors"][0]["id"]
    r = await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 10, "y": 10, "w": 100, "h": 50})
    assert r.json()["plan"]["floor_id"] == eg


async def test_floors_rooms_and_stairs(client, enabled, power, manager, db):
    laser, t, mid = await _fill(client, power, db)
    og = (await client.post("/api/inventory/plan/floors", headers=power, json={"name": "OG"})).json()
    assert (await client.post("/api/inventory/plan/floors", headers=power, json={"name": "og"})).status_code == 409
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    room = (await client.post("/api/inventory/plan/rooms", headers=power,
                              json={"floor_id": eg, "name": "Werkstatt", "x": 0, "y": 0, "w": 800, "h": 600})).json()
    stairs = (await client.post("/api/inventory/plan/rooms", headers=power,
                                json={"floor_id": eg, "name": "Treppe Süd", "kind": "treppe", "x": 800, "y": 0,
                                      "link_floor_id": og["id"]})).json()
    assert stairs["plan"]["w"] == 100 and stairs["link_floor_id"] == og["id"]
    # Möbel aufs OG stellen
    r = await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power,
                           json={"x": 10, "y": 10, "w": 100, "h": 50, "floor_id": og["id"]})
    assert r.json()["plan"]["floor_id"] == og["id"]
    pub = (await client.get("/api/inventory-public/plan")).json()
    assert [r["name"] for r in pub["rooms"]] == ["Werkstatt", "Treppe Süd"] and pub["furniture"][0]["plan"]["floor_id"] == og["id"]
    # Räume ändern und löschen
    r = await client.patch(f"/api/inventory/plan/rooms/{room['id']}", headers=power, json={"w": 900, "name": "Grosse Werkstatt"})
    assert r.json()["plan"]["w"] == 900 and r.json()["name"] == "Grosse Werkstatt"
    assert (await client.patch(f"/api/inventory/plan/rooms/{room['id']}", headers=power, json={"w": 1})).status_code == 400
    assert (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": 999, "name": "X"})).status_code == 404
    assert (await client.post("/api/inventory/plan/rooms", headers=manager, json={"name": "X"})).status_code == 403
    # Stockwerk mit Inhalt lässt sich nicht löschen
    assert (await client.delete(f"/api/inventory/plan/floors/{og['id']}", headers=power)).status_code == 409
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"remove": True})
    assert (await client.delete(f"/api/inventory/plan/rooms/{stairs['id']}", headers=power)).status_code == 200
    assert (await client.delete(f"/api/inventory/plan/floors/{og['id']}", headers=power)).status_code == 200
    assert (await client.delete(f"/api/inventory/plan/floors/{eg}", headers=power)).status_code == 409   # letztes Stockwerk


async def test_floors_and_rooms_survive_backup(client, enabled, power, admin, db):
    from app.models_inventory import InvRoom, InvFloor
    laser, t, mid = await _fill(client, power, db)
    og = (await client.post("/api/inventory/plan/floors", headers=power, json={"name": "OG"})).json()
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": og["id"], "name": "Atelier", "x": 5, "y": 6, "w": 400, "h": 300})
    await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "name": "Treppe", "kind": "treppe", "link_floor_id": og["id"]})
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 1, "y": 2, "w": 100, "h": 50, "floor_id": og["id"]})
    data = (await client.get("/api/backup/export", headers=admin)).json()
    assert [r["name"] for r in data["inventory"]["rooms"]] == ["Treppe", "Atelier"] or sorted(r["name"] for r in data["inventory"]["rooms"]) == ["Atelier", "Treppe"]
    await db.execute(delete(InvRoom)); await db.execute(delete(InvFloor))
    f = await db.get(InvFurniture, t["id"])
    f.plan_x = f.plan_y = f.plan_w = f.plan_h = f.plan_rot = f.plan_floor_id = None
    await db.commit()
    assert (await client.post("/api/backup/import", headers=admin, json=data)).status_code == 200
    p = (await client.get("/api/inventory/plan", headers=power)).json()
    names = {f["id"]: f["name"] for f in p["floors"]}
    assert sorted(names.values()) == ["EG", "OG"]
    by = {r["name"]: r for r in p["rooms"]}
    assert names[by["Atelier"]["floor_id"]] == "OG" and by["Treppe"]["kind"] == "treppe" and names[by["Treppe"]["link_floor_id"]] == "OG"
    assert names[p["furniture"][0]["plan"]["floor_id"]] == "OG"


async def test_reset_plan_clears_everything_but_keeps_locations(client, enabled, power, manager, db):
    laser, t, mid = await _fill(client, power, db)
    og = (await client.post("/api/inventory/plan/floors", headers=power, json={"name": "OG"})).json()
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": og["id"], "name": "Atelier"})
    await client.patch(f"/api/inventory/plan/area/{laser}", headers=power, json={"x": 0, "y": 0, "w": 300, "h": 200})
    await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 5, "y": 5, "w": 100, "h": 50, "floor_id": og["id"]})
    await client.patch(f"/api/inventory/plan/machine/{mid}", headers=power, json={"x": 9, "y": 9, "w": 70, "h": 50})
    await client.put("/api/inventory/plan/room", headers=power, json={"name": "Halle", "width_cm": 2000, "height_cm": 1200})
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": t["id"]})

    assert (await client.post("/api/inventory/plan/reset", headers=manager)).status_code == 403
    p = (await client.post("/api/inventory/plan/reset", headers=power)).json()
    assert [f["name"] for f in p["floors"]] == ["EG"] and p["rooms"] == []
    assert all(x["plan"] is None for k in ("areas", "furniture", "machines") for x in p[k])
    assert p["room"] == {"name": "Halle", "width_cm": 2000.0, "height_cm": 1200.0, "wall_cm": 0.0}          # Gebäude bleibt
    m = (await _machines(client, power))["Lasercutter"]
    assert m["stands_on"]["code"] == "LAS-M01"                                              # Standort (Möbel) bleibt
    # danach wieder normal zeichnen
    new_eg = p["floors"][0]["id"]
    r = await client.patch(f"/api/inventory/plan/furniture/{t['id']}", headers=power, json={"x": 1, "y": 1, "w": 50, "h": 50})
    assert r.json()["plan"]["floor_id"] == new_eg


# ── Vieleck-Räume, Türen und Durchgänge ──────────────────────────────────────
async def test_polygon_room_doors_and_scaling(client, enabled, power, db):
    await _fill(client, power, db)
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    l_shape = [[0, 0], [600, 0], [600, 300], [300, 300], [300, 600], [0, 600]]
    r = (await client.post("/api/inventory/plan/rooms", headers=power,
                           json={"floor_id": eg, "name": "Werkstatt", "points": l_shape})).json()
    assert r["points"] == [[0.0, 0.0], [600.0, 0.0], [600.0, 300.0], [300.0, 300.0], [300.0, 600.0], [0.0, 600.0]]
    assert (r["plan"]["x"], r["plan"]["y"], r["plan"]["w"], r["plan"]["h"]) == (0, 0, 600, 600)       # bbox aus den Punkten
    # Verschieben/Skalieren per Rechteck führt die Punkte mit
    r2 = (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power, json={"x": 100, "y": 50, "w": 1200, "h": 600})).json()
    assert r2["points"][1] == [1300.0, 50.0] and r2["points"][4] == [700.0, 650.0]
    # Punkte ändern → bbox folgt; ungültige Punkte werden abgelehnt
    r3 = (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power,
                             json={"points": [[0, 0], [100, 0], [100, 100]]})).json()
    assert r3["plan"]["w"] == 100 and len(r3["points"]) == 3
    assert (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power, json={"points": [[0, 0], [1, 1]]})).status_code == 400
    # zurück zum Rechteck
    r4 = (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power, json={"points": None})).json()
    assert r4["points"] is None and r4["plan"]["w"] == 100
    # Türen und Durchgänge: eigene Arten mit Standardgrösse, keine Eckpunkte
    d = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "kind": "tuer", "x": 10, "y": 10})).json()
    assert d["kind"] == "tuer" and d["name"] == "Tür" and d["plan"]["w"] == 90 and d["points"] is None
    g = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "kind": "durchgang", "x": 10, "y": 10, "rot": 90})).json()
    assert g["kind"] == "durchgang" and g["plan"]["rot"] == 90
    # Türen haben keine Eckpunkte, auch wenn welche mitgeschickt werden
    d2 = (await client.patch(f"/api/inventory/plan/rooms/{d['id']}", headers=power, json={"points": [[0, 0], [50, 0], [50, 50]]})).json()
    assert d2["points"] is None


async def test_polygon_rooms_and_doors_survive_backup(client, enabled, power, admin, db):
    from sqlalchemy import delete
    from app.models_inventory import InvRoom
    await _fill(client, power, db)
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    tri = [[0, 0], [400, 0], [0, 300]]
    await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "name": "Dreieck", "points": tri})
    await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "name": "Eingang", "kind": "tuer", "x": 5, "y": 5, "rot": 180})
    data = (await client.get("/api/backup/export", headers=admin)).json()
    assert [r["points"] for r in data["inventory"]["rooms"] if r["name"] == "Dreieck"] == [[[0.0, 0.0], [400.0, 0.0], [0.0, 300.0]]]
    await db.execute(delete(InvRoom))
    await db.commit()
    assert (await client.post("/api/backup/import", headers=admin, json=data)).status_code == 200
    by = {r["name"]: r for r in (await client.get("/api/inventory/plan", headers=power)).json()["rooms"]}
    assert by["Dreieck"]["points"] == [[0.0, 0.0], [400.0, 0.0], [0.0, 300.0]]
    assert by["Eingang"]["kind"] == "tuer" and by["Eingang"]["plan"]["rot"] == 180


async def test_doors_can_be_mirrored_and_keep_it_in_the_backup(client, enabled, power, admin, db):
    from sqlalchemy import delete
    from app.models_inventory import InvRoom
    await _fill(client, power, db)
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    d = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "kind": "tuer", "x": 10, "y": 10})).json()
    assert d["flip"] == 0
    d = (await client.patch(f"/api/inventory/plan/rooms/{d['id']}", headers=power, json={"flip": 3})).json()
    assert d["flip"] == 3
    assert (await client.patch(f"/api/inventory/plan/rooms/{d['id']}", headers=power, json={"flip": 7})).status_code == 422
    room = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "name": "R", "flip": 1})).json()
    assert room["flip"] == 0                                  # nur Türen haben einen Schwenk
    data = (await client.get("/api/backup/export", headers=admin)).json()
    await db.execute(delete(InvRoom)); await db.commit()
    assert (await client.post("/api/backup/import", headers=admin, json=data)).status_code == 200
    by = {r["name"]: r for r in (await client.get("/api/inventory/plan", headers=power)).json()["rooms"]}
    assert by["Tür"]["flip"] == 3 and by["R"]["flip"] == 0


# ── Hintergrund-Grundriss und Wanddicke ──────────────────────────────────────
def plan_crop(floor_resp):
    c = floor_resp["background"]["crop"]
    return (c["l"], c["t"], c["r"], c["b"])


def _jpeg(w=800, h=400):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 220, 240)).save(buf, "JPEG")
    return buf.getvalue()


async def test_floor_background_upload_adjust_download_delete(client, enabled, power, manager, db):
    await _fill(client, power, db)
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    up = await client.put(f"/api/inventory/plan/floors/{eg}/background", headers=power,
                          files={"file": ("grundriss.jpg", _jpeg(), "image/jpeg")})
    assert up.status_code == 200, up.text
    bg = up.json()["background"]
    assert (bg["x"], bg["y"], bg["w"], bg["h"], bg["opacity"], bg["version"]) == (0.0, 0.0, 1500.0, 750.0, 0.5, 1)    # so breit wie das Gebäude
    assert (await client.get(f"/api/inventory/plan/floors/{eg}/background", headers=manager)).headers["content-type"] == "image/jpeg"
    p = (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"x": 20, "w": 3000, "h": 1500, "opacity": 0.8})).json()
    assert p["background"]["w"] == 3000 and p["background"]["opacity"] == 0.8
    assert p["background"]["rot"] == 0.0
    r = (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"rot": 450})).json()
    assert r["background"]["rot"] == 90.0                          # wird auf 0–360° normalisiert
    r = (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"rot": -1.5})).json()
    assert r["background"]["rot"] == 358.5                         # auch Zehntelgrad für schief gescannte Pläne
    assert plan_crop(r) == (0, 0, 0, 0)
    c = (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power,
                            json={"crop_l": 0.1, "crop_t": 0.05, "crop_r": 0.2, "crop_b": 0.0})).json()
    assert plan_crop(c) == (0.1, 0.05, 0.2, 0.0)                    # Ausschnitt: Ränder wegschneiden (z.B. Bemassung)
    assert (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"crop_l": 0.9, "crop_r": 0.9})).status_code == 400
    assert (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"crop_l": 0.99})).status_code == 422
    assert (await client.patch(f"/api/inventory/plan/floors/{eg}/background", headers=power, json={"opacity": 5})).status_code == 422
    plan = (await client.get("/api/inventory/plan", headers=power)).json()
    assert plan["floors"][0]["background"]["x"] == 20
    assert "background" not in (await client.get("/api/inventory-public/plan")).json()["floors"][0]       # Gäste sehen das Bild nicht
    assert (await client.put(f"/api/inventory/plan/floors/{eg}/background", headers=manager,
                             files={"file": ("x.jpg", _jpeg(), "image/jpeg")})).status_code == 403
    assert (await client.put(f"/api/inventory/plan/floors/{eg}/background", headers=power,
                             files={"file": ("x.txt", b"kein bild", "text/plain")})).status_code == 400
    assert (await client.delete(f"/api/inventory/plan/floors/{eg}/background", headers=power)).status_code == 200
    assert (await client.get(f"/api/inventory/plan/floors/{eg}/background", headers=power)).status_code == 404
    assert "background" not in (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]


async def test_wall_thickness_and_background_survive_backup(client, enabled, power, admin, db):
    from sqlalchemy import delete
    from app.models_inventory import InvFloor, InvFloorImage, InvPlan
    await _fill(client, power, db)
    assert (await client.get("/api/inventory/plan", headers=power)).json()["room"]["wall_cm"] == 0.0
    await client.put("/api/inventory/plan/room", headers=power, json={"wall_cm": 30})
    assert (await client.put("/api/inventory/plan/room", headers=power, json={"wall_cm": 101})).status_code == 422
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    await client.put(f"/api/inventory/plan/floors/{eg}/background", headers=power, files={"file": ("g.jpg", _jpeg(), "image/jpeg")})
    data = (await client.get("/api/backup/export", headers=admin)).json()
    assert data["inventory"]["room"]["wall_cm"] == 30.0 and data["inventory"]["floors"][0]["background"]["image"]
    await db.execute(delete(InvFloorImage)); await db.execute(delete(InvFloor)); await db.execute(delete(InvPlan)); await db.commit()
    assert (await client.post("/api/backup/import", headers=admin, json=data)).status_code == 200
    plan = (await client.get("/api/inventory/plan", headers=power)).json()
    assert plan["room"]["wall_cm"] == 30.0 and plan["floors"][0]["background"]["w"] == 1500.0
    assert plan["floors"][0]["background"]["crop"]["l"] == 0.0
    assert (await client.get(f"/api/inventory/plan/floors/{plan['floors'][0]['id']}/background", headers=power)).status_code == 200
    # Zurücksetzen entfernt auch das Bild
    await client.post("/api/inventory/plan/reset", headers=power)
    assert "background" not in (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]


async def test_wall_thickness_per_room_overrides_the_default(client, enabled, power, admin, db):
    from sqlalchemy import delete
    from app.models_inventory import InvRoom
    await _fill(client, power, db)
    eg = (await client.get("/api/inventory/plan", headers=power)).json()["floors"][0]["id"]
    r = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "name": "Aussenmauer"})).json()
    assert r["wall_cm"] is None                                              # Standard des Gebäudes
    r = (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power, json={"wall_cm": 35})).json()
    assert r["wall_cm"] == 35
    assert (await client.patch(f"/api/inventory/plan/rooms/{r['id']}", headers=power, json={"wall_cm": 500})).status_code == 422
    t = (await client.post("/api/inventory/plan/rooms", headers=power, json={"floor_id": eg, "kind": "treppe", "wall_cm": 10})).json()
    assert t["wall_cm"] is None                                              # nur Räume haben eine eigene Wanddicke
    data = (await client.get("/api/backup/export", headers=admin)).json()
    await db.execute(delete(InvRoom)); await db.commit()
    assert (await client.post("/api/backup/import", headers=admin, json=data)).status_code == 200
    by = {x["name"]: x for x in (await client.get("/api/inventory/plan", headers=power)).json()["rooms"]}
    assert by["Aussenmauer"]["wall_cm"] == 35
    r = (await client.patch(f"/api/inventory/plan/rooms/{by['Aussenmauer']['id']}", headers=power, json={"wall_cm": None})).json()
    assert r["wall_cm"] is None                                              # zurück zum Standard
    assert (await client.put("/api/inventory/plan/room", headers=power, json={"wall_cm": 0})).json()["wall_cm"] == 0.0
