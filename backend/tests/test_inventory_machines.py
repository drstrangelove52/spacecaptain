"""Inventar Etappe 2: Maschinen ↔ Bereiche, «steht auf», Suche, Umbenennen, Backup/Restore."""
import pytest
from sqlalchemy import select, delete

from app.models import MachineLocation, Machine, ActivityLog, LogType
from app.models_inventory import InvFurniture, InvLevel, InvPosition, InvItem, InvPlacement


def _machine(name, location=None, category="Sonstiges"):
    return Machine(name=name, category=category, location=location, qr_token=f"qr-{name}")


async def _setup(db):
    """Bereiche Laser (LAS) und Holz (HOL) mit Maschinen verschiedener Schreibweisen."""
    db.add_all([MachineLocation(name="Laser", code="LAS"), MachineLocation(name="Holz", code="HOL")])
    db.add_all([_machine("Lasercutter", "laser", "Laser"), _machine("Tischkreissäge", "Holz", "Holz"),
                _machine("Plotter", "Unbekannt"), _machine("Nähmaschine", None)])
    await db.commit()


async def _area_id(client, hdr, name):
    return [a for a in (await client.get("/api/inventory/areas", headers=hdr)).json() if a["name"] == name][0]["id"]


async def _machines(client, hdr, **params):
    return {m["name"]: m for m in (await client.get("/api/inventory/machines", params=params, headers=hdr)).json()}


async def test_machines_get_their_area_from_the_location_text(client, enabled, power, db):
    await _setup(db)
    ms = await _machines(client, power)
    assert ms["Lasercutter"]["area"]["name"] == "Laser"          # Gross-/Kleinschreibung egal
    assert ms["Tischkreissäge"]["area"]["code"] == "HOL"
    assert ms["Plotter"]["area"] is None and ms["Plotter"]["location"] == "Unbekannt"   # Text ohne Bereich bleibt
    assert ms["Nähmaschine"]["area"] is None
    assert sorted((await _machines(client, power, unassigned=True)).keys()) == ["Nähmaschine", "Plotter"]
    areas = {a["name"]: a for a in (await client.get("/api/inventory/areas", headers=power)).json()}
    assert areas["Laser"]["machine_count"] == 1 and areas["Holz"]["machine_count"] == 1


async def test_machine_filters(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    assert list((await _machines(client, power, area_id=laser)).keys()) == ["Lasercutter"]
    assert list((await _machines(client, power, q="kreis")).keys()) == ["Tischkreissäge"]
    assert "Lasercutter" in await _machines(client, power, q="laser")        # auch über Kategorie/Bereich


async def test_changing_the_area_moves_text_and_writes_log(client, enabled, power, db):
    await _setup(db)
    holz = await _area_id(client, power, "Holz")
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": holz})
    assert r.status_code == 200 and r.json()["area"]["name"] == "Holz" and r.json()["location"] == "Holz"
    # der Text bleibt für Maschinenliste/CSV/Display mit dem Bereich in Einklang
    m = await db.scalar(select(Machine).where(Machine.id == mid))
    await db.refresh(m)
    assert m.location == "Holz" and m.area_id == holz
    log = (await db.execute(select(ActivityLog).where(ActivityLog.type == LogType.machine_area_changed))).scalars().all()
    assert len(log) == 1 and "Laser → Holz" in log[0].message and log[0].machine_id == mid
    # gleicher Bereich noch einmal: kein neuer Eintrag
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": holz})
    assert len((await db.execute(select(ActivityLog).where(ActivityLog.type == LogType.machine_area_changed))).scalars().all()) == 1
    # Bereich entfernen
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": None})
    assert r.json()["area"] is None and r.json()["location"] is None


async def test_stands_on_furniture(client, enabled, power, db):
    await _setup(db)
    laser, holz = await _area_id(client, power, "Laser"), await _area_id(client, power, "Holz")
    tisch = (await client.post("/api/inventory/furniture", headers=power,
                               json={"area_id": laser, "kind": "tisch", "name": "Tisch 1"})).json()
    fremd = (await client.post("/api/inventory/furniture", headers=power,
                               json={"area_id": holz, "kind": "tisch"})).json()
    mid = (await _machines(client, power))["Lasercutter"]["id"]

    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": tisch["id"]})
    assert r.status_code == 200
    assert r.json()["stands_on"] == {"furniture_id": tisch["id"], "code": "LAS-M01", "title": "Tisch 1", "level": None}
    assert r.json()["path"] == "Laser › Tisch 1"
    # anderer Bereich → 409, «Im Bereich, ohne Möbel» (M00) → 400
    assert (await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": fremd["id"]})).status_code == 409
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    m00 = [f for a in tree if a["name"] == "Laser" for f in a["furniture"] if f["number"] == 0][0]
    assert (await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": m00["id"]})).status_code == 400
    # Bereichswechsel entfernt «steht auf», weil das Möbel zum alten Bereich gehört
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": holz})
    assert r.json()["stands_on"] is None and r.json()["area"]["name"] == "Holz"
    # ausdrücklich wieder entfernen
    mid2 = (await _machines(client, power))["Tischkreissäge"]["id"]
    await client.patch(f"/api/inventory/machines/{mid2}", headers=power, json={"furniture_id": fremd["id"]})
    r = await client.patch(f"/api/inventory/machines/{mid2}", headers=power, json={"furniture_id": None})
    assert r.json()["stands_on"] is None


async def test_roles_for_machine_assignment(client, enabled, manager, power, db):
    await _setup(db)
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    assert (await client.get("/api/inventory/machines", headers=manager)).status_code == 200      # lesen: jeder Lab Manager
    assert (await client.patch(f"/api/inventory/machines/{mid}", headers=manager, json={"area_id": None})).status_code == 403
    assert (await client.patch("/api/inventory/machines/99999", headers=power, json={"area_id": None})).status_code == 404


async def test_machine_form_location_change_updates_area(client, enabled, power, db):
    await _setup(db)
    ms = await _machines(client, power)
    mid = ms["Plotter"]["id"]
    r = await client.patch(f"/api/machines/{mid}", headers=power, json={"location": "Holz"})        # altes Maschinenformular
    assert r.status_code == 200, r.text
    assert (await _machines(client, power))["Plotter"]["area"]["name"] == "Holz"
    await client.patch(f"/api/machines/{mid}", headers=power, json={"location": ""})
    assert (await _machines(client, power))["Plotter"]["area"] is None


async def test_new_machine_gets_its_area(client, enabled, power, db):
    await _setup(db)
    r = await client.post("/api/machines", headers=power, json={"name": "Fräse", "category": "CNC", "location": "Holz"})
    assert r.status_code == 200, r.text
    assert (await _machines(client, power))["Fräse"]["area"]["code"] == "HOL"


async def test_renaming_a_location_moves_its_machines(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    await client.patch(f"/api/locations/{laser}", headers=power, json={"name": "Lasergravur"})
    ms = await _machines(client, power)
    assert ms["Lasercutter"]["location"] == "Lasergravur" and ms["Lasercutter"]["area"]["name"] == "Lasergravur"
    assert ms["Lasercutter"]["area"]["id"] == laser


async def test_deleting_a_machine_removes_its_placement(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    tisch = (await client.post("/api/inventory/furniture", headers=power, json={"area_id": laser, "kind": "tisch"})).json()
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": tisch["id"]})
    assert (await db.execute(select(InvPlacement))).scalars().all()
    assert (await client.delete(f"/api/machines/{mid}", headers=power)).status_code == 200
    assert (await db.execute(select(InvPlacement))).scalars().all() == []


async def test_search_finds_machines_and_tools_together(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    tisch = (await client.post("/api/inventory/furniture", headers=power,
                               json={"area_id": laser, "kind": "tisch", "name": "Tisch 1", "levels": 1})).json()
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": tisch["id"]})
    await client.post("/api/inventory/items", headers=power, json={"name": "Laserbrille", "code": "LAS-M01-E01"})

    res = (await client.get("/api/inventory/search", params={"q": "laser"}, headers=power)).json()
    kinds = sorted(r["type"] for r in res)
    assert kinds == ["furniture", "machine", "tool"]       # «laser» trifft Werkzeug, Maschine und das Möbel im Bereich Laser
    machine = [r for r in res if r["type"] == "machine"][0]
    assert machine["name"] == "Lasercutter" and machine["path"] == "Laser › Tisch 1"
    assert machine["stands_on"]["code"] == "LAS-M01" and machine["code"] is None
    assert [r["type"] for r in (await client.get("/api/inventory/search", params={"q": "kreissäge"}, headers=power)).json()] == ["machine"]


# ── Backup / Restore ─────────────────────────────────────────────────────────
async def _populate(client, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    holz = await _area_id(client, power, "Holz")
    await client.patch(f"/api/inventory/areas/{laser}", headers=power, json={"color": "#112233"})
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": holz, "kind": "regal", "name": "Regal Süd", "levels": 2, "positions": 2})).json()
    t = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": laser, "kind": "tisch", "name": "Tisch 1"})).json()
    mk = lambda name, code, qty=1, syn=None: client.post("/api/inventory/items", headers=power,
                                                         json={"name": name, "code": code, "quantity": qty, "synonyms": syn})
    await mk("Lineal 30 cm", "HOL-M01-E02-P01", 12, "Massstab")
    await mk("Zollstock", "HOL-M01-E02", 5)
    await mk("Kiste", "HOL")                                  # M00
    await mk("Ohne Platz", "")
    lvl = (await client.get("/api/inventory/tree", headers=power)).json()
    await client.patch(f"/api/inventory/levels/{[l for a in lvl if a['name']=='Holz' for fu in a['furniture'] if fu['number']==1 for l in fu['levels'] if l['number']==2][0]['id']}",
                       headers=power, json={"label": "Obere Schublade"})
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": t["id"]})
    return f, t


async def _wipe_inventory(db):
    for model in (InvPlacement, InvItem, InvPosition, InvLevel, InvFurniture):
        await db.execute(delete(model))
    for a in (await db.execute(select(MachineLocation))).scalars().all():
        a.code = None; a.color = None
    await db.commit()


async def test_backup_export_contains_inventory(client, enabled, power, admin, db):
    await _populate(client, power, db)
    data = (await client.get("/api/backup/export", headers=admin)).json()
    inv = data["inventory"]
    assert {a["name"]: a["code"] for a in inv["areas"]} == {"Laser": "LAS", "Holz": "HOL"}
    assert [f["name"] for f in inv["furniture"]] == ["Tisch 1", "Regal Süd"] or sorted(f["name"] for f in inv["furniture"]) == ["Regal Süd", "Tisch 1"]
    names = {i["name"]: i for i in inv["items"]}
    assert names["Lineal 30 cm"]["place"] == {"area": "Holz", "furniture": 1, "level": 2, "position": 1}
    assert names["Kiste"]["place"] == {"area": "Holz", "furniture": 0, "level": 0, "position": 0}
    assert names["Ohne Platz"]["place"] is None
    assert inv["placements"][0]["machine"] == "Lasercutter" and inv["placements"][0]["furniture"] == {"area": "Laser", "number": 1}
    # keine DB-IDs im Export (natürliche Schlüssel)
    assert "id" not in inv["furniture"][0] and "area_id" not in inv["items"][0]


async def test_backup_roundtrip_restores_inventory(client, enabled, power, admin, db):
    await _populate(client, power, db)
    backup = (await client.get("/api/backup/export", headers=admin)).json()
    await _wipe_inventory(db)
    assert (await db.execute(select(InvItem))).scalars().all() == []

    r = await client.post("/api/backup/import", headers=admin, json=backup)
    assert r.status_code == 200, r.text
    imp = r.json()["imported"]
    assert imp["inventory_furniture"] == 2 and imp["inventory_items"] == 4 and imp["inventory_placements"] == 1

    areas = {a["name"]: a for a in (await client.get("/api/inventory/areas", headers=power)).json()}
    assert areas["Holz"]["code"] == "HOL" and areas["Laser"]["code"] == "LAS" and areas["Laser"]["color"] == "#112233"
    items = (await client.get("/api/inventory/items", params={"limit": 50}, headers=power)).json()["items"]
    by = {i["name"]: i for i in items}
    assert by["Lineal 30 cm"]["position"]["code"] == "HOL-M01-E02-P01" and by["Lineal 30 cm"]["quantity"] == 12
    assert by["Lineal 30 cm"]["synonyms"] == "Massstab"
    assert by["Zollstock"]["position"]["code"] == "HOL-M01-E02"
    assert by["Kiste"]["position"]["code"] == "HOL-M00"
    assert by["Ohne Platz"]["position"] is None
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    holz = [a for a in tree if a["name"] == "Holz"][0]
    regal = [f for f in holz["furniture"] if f["number"] == 1][0]
    assert regal["name"] == "Regal Süd" and regal["kind"] == "regal"
    assert [l["label"] for l in regal["levels"] if l["number"] == 2] == ["Obere Schublade"]
    assert len([p for l in regal["levels"] if l["number"] == 1 for p in l["positions"]]) == 3     # P00 + 2
    ms = await _machines(client, power)
    assert ms["Lasercutter"]["stands_on"]["title"] == "Tisch 1" and ms["Lasercutter"]["area"]["code"] == "LAS"


async def test_backup_import_is_idempotent_and_keeps_existing(client, enabled, power, admin, db):
    await _populate(client, power, db)
    backup = (await client.get("/api/backup/export", headers=admin)).json()
    total_before = (await client.get("/api/inventory/items", headers=power)).json()["total"]
    r = (await client.post("/api/backup/import", headers=admin, json=backup)).json()["imported"]
    assert r["inventory_furniture"] == 0 and r["inventory_items"] == 0           # nichts doppelt
    assert (await client.get("/api/inventory/items", headers=power)).json()["total"] == total_before


async def test_old_backup_without_inventory_section_still_imports(client, enabled, admin, db):
    r = await client.post("/api/backup/import", headers=admin, json={"version": "3.0", "machine_locations": [{"name": "Laser"}]})
    assert r.status_code == 200 and r.json()["ok"] is True


async def test_machines_need_sync_compares_text_in_python(db):
    """Regression (Dev, MariaDB): machines und machine_locations haben verschiedene Sortierungen; der Vergleich der
    Textspalten per SQL scheiterte mit 'Illegal mix of collations'. Jetzt wird in Python verglichen."""
    from app.services import inventory as inv
    db.add(MachineLocation(name="Laser", code="LAS"))
    await db.commit()
    a = await db.scalar(select(MachineLocation))
    m = _machine("Lasercutter", "laser")                     # Schreibweise weicht ab, gleicher Bereich
    m.area_id = a.id
    db.add(m)
    await db.commit()
    assert await inv.machines_need_sync(db) is False         # gross/klein ist kein Unterschied
    m.location = "Holz"                                      # Text zeigt woanders hin
    await db.commit()
    assert await inv.machines_need_sync(db) is True
    m.location = "Laser"
    m2 = _machine("Plotter", "Laser")                        # Text ohne area_id
    db.add(m2)
    await db.commit()
    assert await inv.machines_need_sync(db) is True
    await inv.sync_machine_areas(db)
    await db.commit()
    assert await inv.machines_need_sync(db) is False


async def test_machine_on_a_level_of_a_shelf(client, enabled, power, db):
    await _setup(db)
    holz = await _area_id(client, power, "Holz")
    laser = await _area_id(client, power, "Laser")
    regal = (await client.post("/api/inventory/furniture", headers=power,
                               json={"area_id": holz, "kind": "regal", "levels": 3})).json()
    fremd = (await client.post("/api/inventory/furniture", headers=power,
                               json={"area_id": laser, "kind": "regal", "levels": 2})).json()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    lv = {l["number"]: l["id"] for a in tree if a["name"] == "Holz" for f in a["furniture"] if f["number"] == 1 for l in f["levels"]}
    lv_fremd = [l["id"] for a in tree if a["name"] == "Laser" for f in a["furniture"] if f["number"] == 1 for l in f["levels"] if l["number"] == 1][0]
    mid = (await _machines(client, power))["Tischkreissäge"]["id"]

    # Möbel und Ebene in einem Schritt
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": regal["id"], "level_id": lv[3]})
    assert r.status_code == 200, r.text
    so = r.json()["stands_on"]
    assert so["title"] == "Regal 1" and so["level"]["number"] == 3 and so["level"]["code"] == "HOL-M01-E03"
    assert r.json()["path"] == "Holz › Regal 1 › Ebene 3"
    # E00 und fremde Ebene werden abgelehnt
    assert (await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"level_id": lv[0]})).status_code == 400
    assert (await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"level_id": lv_fremd})).status_code == 409
    # nur die Ebene wechseln, Möbel bleibt
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"level_id": lv[1]})
    assert r.json()["stands_on"]["level"]["number"] == 1 and r.json()["stands_on"]["title"] == "Regal 1"
    # Ebene entfernen
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"level_id": None})
    assert r.json()["stands_on"]["level"] is None and r.json()["stands_on"]["title"] == "Regal 1"
    # Ebene ohne Möbel ist ungültig
    mid2 = (await _machines(client, power))["Lasercutter"]["id"]
    assert (await client.patch(f"/api/inventory/machines/{mid2}", headers=power, json={"level_id": lv_fremd})).status_code == 409


async def test_level_is_cleared_when_furniture_changes_or_level_is_deleted(client, enabled, power, db):
    await _setup(db)
    holz = await _area_id(client, power, "Holz")
    r1 = (await client.post("/api/inventory/furniture", headers=power, json={"area_id": holz, "kind": "regal", "levels": 2})).json()
    r2 = (await client.post("/api/inventory/furniture", headers=power, json={"area_id": holz, "kind": "regal", "levels": 2})).json()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    lv = {(f["number"], l["number"]): l["id"] for a in tree if a["name"] == "Holz" for f in a["furniture"] for l in f["levels"]}
    mid = (await _machines(client, power))["Tischkreissäge"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": r1["id"], "level_id": lv[(1, 2)]})
    # anderes Möbel gewählt → alte Ebene entfällt
    r = await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": r2["id"]})
    assert r.json()["stands_on"]["title"] == "Regal 2" and r.json()["stands_on"]["level"] is None
    # Ebene löschen → Zuordnung der Maschine verliert die Ebene, nicht das Möbel
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"level_id": lv[(2, 2)]})
    assert (await client.delete(f"/api/inventory/levels/{lv[(2, 2)]}", headers=power)).status_code == 200
    r = (await _machines(client, power))["Tischkreissäge"]
    assert r["stands_on"]["title"] == "Regal 2" and r["stands_on"]["level"] is None
    # Möbel löschen → keine Standfläche mehr
    assert (await client.delete(f"/api/inventory/furniture/{r2['id']}", headers=power)).status_code == 200
    assert (await _machines(client, power))["Tischkreissäge"]["stands_on"] is None


async def test_backup_keeps_the_level_of_a_machine(client, enabled, power, admin, db):
    await _setup(db)
    holz = await _area_id(client, power, "Holz")
    regal = (await client.post("/api/inventory/furniture", headers=power, json={"area_id": holz, "kind": "regal", "levels": 3})).json()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    lvl2 = [l["id"] for a in tree if a["name"] == "Holz" for f in a["furniture"] if f["number"] == 1 for l in f["levels"] if l["number"] == 2][0]
    mid = (await _machines(client, power))["Tischkreissäge"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": regal["id"], "level_id": lvl2})
    backup = (await client.get("/api/backup/export", headers=admin)).json()
    assert backup["inventory"]["placements"][0]["level"] == 2
    await _wipe_inventory(db)
    assert (await client.post("/api/backup/import", headers=admin, json=backup)).status_code == 200
    so = (await _machines(client, power))["Tischkreissäge"]["stands_on"]
    assert so["title"] == "Regal 1" and so["level"]["number"] == 2


async def test_changing_the_location_in_the_machine_form_drops_a_foreign_stands_on(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    tisch = (await client.post("/api/inventory/furniture", headers=power, json={"area_id": laser, "kind": "tisch"})).json()
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": tisch["id"]})
    assert (await _machines(client, power))["Lasercutter"]["stands_on"] is not None
    await client.patch(f"/api/machines/{mid}", headers=power, json={"location": "Holz"})        # altes Formular
    m = (await _machines(client, power))["Lasercutter"]
    assert m["area"]["name"] == "Holz" and m["stands_on"] is None                               # Tisch gehört zu Laser


# ── Option B: Kategorie wird aus dem Bereich abgeleitet ──────────────────────
async def _cats(db):
    from app.models import MachineCategory
    return {c.name for c in (await db.execute(select(MachineCategory))).scalars().all()}


async def _category(client, hdr, name):
    return (await _machines(client, hdr))[name]["category"]


async def test_category_follows_the_area_on_first_call(client, enabled, power, db):
    await _setup(db)                                         # «Plotter» hat unbekannten Text, «Nähmaschine» keinen
    assert await _category(client, power, "Lasercutter") == "Laser"
    assert await _category(client, power, "Tischkreissäge") == "Holz"
    assert await _category(client, power, "Plotter") == "Sonstiges"
    assert await _category(client, power, "Nähmaschine") == "Sonstiges"
    assert {"Laser", "Holz", "Sonstiges"} <= await _cats(db)


async def test_category_follows_machine_form_and_area_change(client, enabled, power, db):
    await _setup(db)
    ms = await _machines(client, power)
    r = await client.post("/api/machines", headers=power, json={"name": "Fräse", "category": "CNC", "location": "Holz"})
    assert r.status_code == 200, r.text
    assert await _category(client, power, "Fräse") == "Holz"                     # Formularwert «CNC» wird überstimmt
    mid = ms["Plotter"]["id"]
    await client.patch(f"/api/machines/{mid}", headers=power, json={"location": "Laser", "category": "Egal"})
    assert await _category(client, power, "Plotter") == "Laser"
    holz = await _area_id(client, power, "Holz")
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": holz})
    assert await _category(client, power, "Plotter") == "Holz"
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"area_id": None})
    assert await _category(client, power, "Plotter") == "Sonstiges"


async def test_category_follows_rename_and_delete_of_an_area(client, enabled, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    await _machines(client, power)
    await client.patch(f"/api/locations/{laser}", headers=power, json={"name": "Lasergravur"})
    assert await _category(client, power, "Lasercutter") == "Lasergravur"
    cats = await _cats(db)
    assert "Lasergravur" in cats and "Laser" not in cats
    r = await client.delete(f"/api/locations/{laser}", headers=power)
    assert r.status_code == 200, r.text
    ms = await _machines(client, power)
    assert ms["Lasercutter"]["category"] == "Sonstiges" and ms["Lasercutter"]["area"] is None
    assert "Lasergravur" not in await _cats(db)


async def test_new_area_creates_its_category(client, enabled, power, db):
    await _setup(db)
    r = await client.post("/api/inventory/areas", headers=power, json={"name": "Elektronik"})
    assert r.status_code == 200, r.text
    assert "Elektronik" in await _cats(db)


async def test_categories_stay_untouched_while_inventory_is_off(client, power, db):
    await _setup(db)                                         # kein «enabled»
    r = await client.post("/api/machines", headers=power, json={"name": "Fräse", "category": "CNC", "location": "Holz"})
    assert r.status_code == 200, r.text
    ms = {m["name"]: m for m in (await client.get("/api/machines", headers=power)).json()}
    assert ms["Fräse"]["category"] == "CNC" and ms["Plotter"]["category"] == "Sonstiges"
