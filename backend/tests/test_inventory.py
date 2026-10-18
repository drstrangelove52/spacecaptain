import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import MachineLocation
from app.models_inventory import InvFurniture, InvLevel, InvPosition
from app.services import inventory as inv


# ── reine Code-Logik ─────────────────────────────────────────────────────────
def test_short_code_strips_trailing_zeros():
    assert inv.short_code("EL", 2, 3, 4) == "EL-S2-E3-P4"
    assert inv.short_code("HO", 1, 2, 0) == "HO-S1-E2"
    assert inv.short_code("HO", 1, 0, 0) == "HO-S1"
    assert inv.short_code("HO", 0) == "HO-S0"
    assert inv.short_code("HO", 1, 0, 3) == "HO-S1-E0-P3"   # Position ohne Ebene bleibt eindeutig
    assert inv.short_code(None, 1) == "??-S1"


def test_full_code():
    assert inv.full_code("EL", 2, 0, 0) == "EL-S2-E0-P0"


@pytest.mark.parametrize("text,expected", [
    ("EL", ("EL", 0, 0, 0)),
    ("el-s2", ("EL", 2, 0, 0)),
    ("EL-S2-E3", ("EL", 2, 3, 0)),
    ("EL-S2-E3-P4", ("EL", 2, 3, 4)),
    (" HO-S0 ", ("HO", 0, 0, 0)),
])
def test_parse_code(text, expected):
    assert inv.parse_code(text) == expected


@pytest.mark.parametrize("text", ["", "E", "EL-2-3-4", "EL-S2-P4-E3", "ELEKTRO-S1", "EL-S", "!!"])
def test_parse_code_rejects(text):
    with pytest.raises(HTTPException) as e:
        inv.parse_code(text)
    assert e.value.status_code == 400


def test_normalize_area_code():
    assert inv.normalize_area_code(" el ") == "EL"
    with pytest.raises(HTTPException):
        inv.normalize_area_code("E")
    with pytest.raises(HTTPException):
        inv.normalize_area_code("A B")


# ── Nullplaetze ──────────────────────────────────────────────────────────────
async def test_ensure_structure_is_idempotent(db):
    db.add_all([MachineLocation(name="Holz", code="HO"), MachineLocation(name="Laser", code="LA")])
    await db.commit()

    first = await inv.ensure_structure(db)
    assert first == 6                       # 2x S0 + 2x E0 + 2x P0
    assert await inv.ensure_structure(db) == 0

    furn = (await db.execute(select(InvFurniture))).scalars().all()
    assert sorted(f.number for f in furn) == [0, 0]
    assert (await db.execute(select(InvPosition))).scalars().all()[0].number == 0


async def test_ensure_structure_repairs_missing_zero_rows(db):
    a = MachineLocation(name="Holz", code="HO")
    db.add(a)
    await db.commit()
    await inv.ensure_structure(db)
    # E0/P0 eines echten Moebels wurden (z.B. von Hand) entfernt -> wieder anlegen
    f = await inv.create_furniture(db, a, inv.FurnitureKind.schrank, None, 2, 2)
    lvl0 = await db.scalar(select(InvLevel).where(InvLevel.furniture_id == f.id, InvLevel.number == 0))
    await db.delete(lvl0)
    await db.commit()
    assert await inv.ensure_structure(db) >= 2      # E0 + sein P0
    assert await db.scalar(select(InvLevel).where(InvLevel.furniture_id == f.id, InvLevel.number == 0))


async def test_create_furniture_numbers_and_levels(db):
    a = MachineLocation(name="Elektronik", code="EL")
    db.add(a)
    await db.commit()
    await inv.ensure_structure(db)

    f1 = await inv.create_furniture(db, a, inv.FurnitureKind.schrank, "Hilti 1", levels=3, positions=2)
    f2 = await inv.create_furniture(db, a, inv.FurnitureKind.tisch, None, levels=0, positions=0)
    assert (f1.number, f2.number) == (1, 2)          # S0 bleibt reserviert, echte Moebel ab 1

    lvls = (await db.execute(select(InvLevel).where(InvLevel.furniture_id == f1.id)
                             .order_by(InvLevel.number))).scalars().all()
    assert [l.number for l in lvls] == [0, 1, 2, 3]
    pos = (await db.execute(select(InvPosition).where(InvPosition.level_id == lvls[2].id)
                            .order_by(InvPosition.number))).scalars().all()
    assert [p.number for p in pos] == [0, 1, 2]       # P0 + 2 echte
    # Tisch ohne Ebenen hat trotzdem E0/P0 -> Werkzeug kann «auf dem Tisch» liegen
    assert await inv.resolve_position(db, "EL-S2")


async def test_create_furniture_requires_area_code(db):
    a = MachineLocation(name="Ohne Kuerzel")
    db.add(a)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await inv.create_furniture(db, a, inv.FurnitureKind.schrank, None, 1, 0)
    assert e.value.status_code == 409


async def test_resolve_position_errors_name_the_missing_level(db):
    a = MachineLocation(name="Holz", code="HO")
    db.add(a)
    await db.commit()
    await inv.ensure_structure(db)
    await inv.create_furniture(db, a, inv.FurnitureKind.regal, None, 2, 0)

    assert (await inv.resolve_position(db, "HO-S1-E2")).number == 0
    assert (await inv.resolve_position(db, "ho")).number == 0           # S0-E0-P0
    for text, msg in [("XX", "Bereich"), ("HO-S9", "HO-S9 gibt"), ("HO-S1-E7", "HO-S1-E7 gibt"),
                      ("HO-S1-E1-P5", "HO-S1-E1-P5 gibt")]:
        with pytest.raises(HTTPException) as e:
            await inv.resolve_position(db, text)
        assert e.value.status_code == 404 and msg in e.value.detail


# ── API ──────────────────────────────────────────────────────────────────────
async def _area(client, hdr, name="Elektronik", code="EL"):
    r = await client.post("/api/inventory/areas", json={"name": name, "code": code}, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


async def test_module_switch_off_gives_404(client, power):
    r = await client.get("/api/inventory/areas", headers=power)
    assert r.status_code == 404


async def test_requires_login(client, enabled):
    assert (await client.get("/api/inventory/areas")).status_code == 401


async def test_roles(client, enabled, power, manager):
    area = await _area(client, power)
    # Manager darf Werkzeug pflegen, aber keine Struktur
    r = await client.post("/api/inventory/furniture", headers=manager,
                          json={"area_id": area["id"], "kind": "schrank", "levels": 1})
    assert r.status_code == 403
    r = await client.post("/api/inventory/furniture", headers=power,
                          json={"area_id": area["id"], "kind": "schrank", "levels": 2, "positions": 2})
    assert r.status_code == 200 and r.json()["code"] == "EL-S1"
    r = await client.post("/api/inventory/items", headers=manager,
                          json={"name": "Lötkolben", "code": "EL-S1-E1"})
    assert r.status_code == 200
    assert (await client.patch(f"/api/inventory/areas/{area['id']}", headers=manager,
                               json={"color": "#fff"})).status_code == 403


async def test_item_lifecycle_search_and_move(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power,
                      json={"area_id": area["id"], "kind": "schrank", "levels": 3, "positions": 2})

    r = await client.post("/api/inventory/items", headers=power, json={
        "name": "Akkuschrauber", "synonyms": "Bohrschrauber, Schrauber", "code": "EL-S1-E2-P1"})
    item = r.json()
    assert item["position"]["code"] == "EL-S1-E2-P1"
    assert item["position"]["path"] == "Elektronik › Möbel 1 › Ebene 2 › Platz 1"

    # Suche ueber Synonym, Teilwort, Gross-/Kleinschreibung und Code
    for q in ("Bohrschrauber", "schrauber", "AKKU", "EL-S1-E2", "el-s1", "EL"):
        res = (await client.get("/api/inventory/search", params={"q": q}, headers=power)).json()
        assert [x["name"] for x in res if x["type"] == "tool"] == ["Akkuschrauber"], q
    assert (await client.get("/api/inventory/search", params={"q": "Hammer"}, headers=power)).json() == []
    # Anderer Code trifft nicht
    res = (await client.get("/api/inventory/search", params={"q": "EL-S1-E3"}, headers=power)).json()
    assert [x for x in res if x["type"] == "tool"] == []

    # Umlagern per Kurzcode, danach Platz entfernen
    r = await client.patch(f"/api/inventory/items/{item['id']}", headers=power, json={"code": "EL-S1-E3"})
    assert r.json()["position"]["code"] == "EL-S1-E3"
    r = await client.patch(f"/api/inventory/items/{item['id']}", headers=power, json={"unplace": True})
    assert r.json()["position"] is None
    lst = (await client.get("/api/inventory/items", params={"unplaced": True}, headers=power)).json()
    assert lst["total"] == 1

    r = await client.delete(f"/api/inventory/items/{item['id']}", headers=power)
    assert r.json() == {"ok": True}


async def test_unknown_code_is_rejected(client, enabled, power):
    await _area(client, power)
    r = await client.post("/api/inventory/items", headers=power, json={"name": "X", "code": "EL-S5"})
    assert r.status_code == 404 and "EL-S5" in r.json()["detail"]


async def test_level_open_filter_and_s0(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power,
                      json={"area_id": area["id"], "kind": "regal", "levels": 2})
    await client.post("/api/inventory/items", headers=power, json={"name": "Kiste", "code": "EL"})          # S0
    await client.post("/api/inventory/items", headers=power, json={"name": "Offen", "code": "EL-S1"})       # E0
    await client.post("/api/inventory/items", headers=power, json={"name": "Fest", "code": "EL-S1-E1"})
    r = (await client.get("/api/inventory/items", params={"level_open": True}, headers=power)).json()
    assert [i["name"] for i in r["items"]] == ["Offen"]          # S0 zaehlt nicht als «Ebene offen»
    r = (await client.get("/api/inventory/code/EL-S1", headers=power)).json()
    assert sorted(i["name"] for i in r["items"]) == ["Fest", "Offen"] and r["scope"] == "furniture"
    r = (await client.get("/api/inventory/code/EL", headers=power)).json()
    assert len(r["items"]) == 3 and r["scope"] == "area"


async def test_delete_protection(client, enabled, power):
    area = await _area(client, power)
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": area["id"], "levels": 2, "positions": 1})).json()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    furn = [x for x in tree[0]["furniture"] if x["number"] == 1][0]
    s0 = [x for x in tree[0]["furniture"] if x["number"] == 0][0]
    e0 = [l for l in furn["levels"] if l["number"] == 0][0]
    e1 = [l for l in furn["levels"] if l["number"] == 1][0]
    p0_of_e1 = [p for p in e1["positions"] if p["number"] == 0][0]

    assert (await client.delete(f"/api/inventory/furniture/{s0['id']}", headers=power)).status_code == 400
    assert (await client.delete(f"/api/inventory/levels/{e0['id']}", headers=power)).status_code == 400
    assert (await client.delete(f"/api/inventory/positions/{p0_of_e1['id']}", headers=power)).status_code == 400

    await client.post("/api/inventory/items", headers=power, json={"name": "Zange", "code": "EL-S1-E1"})
    assert (await client.delete(f"/api/inventory/levels/{e1['id']}", headers=power)).status_code == 409
    assert (await client.delete(f"/api/inventory/furniture/{f['id']}", headers=power)).status_code == 409

    lst = (await client.get("/api/inventory/items", headers=power)).json()["items"]
    await client.patch(f"/api/inventory/items/{lst[0]['id']}", headers=power, json={"unplace": True})
    assert (await client.delete(f"/api/inventory/furniture/{f['id']}", headers=power)).status_code == 200


async def test_area_code_change_marks_labels_outdated(client, enabled, power):
    area = await _area(client, power)
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": area["id"], "levels": 1})).json()
    assert f["label_outdated"] is False
    r = await client.patch(f"/api/inventory/areas/{area['id']}", headers=power, json={"code": "ELE"})
    assert r.json()["code"] == "ELE"
    lab = (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json()
    assert [x["code"] for x in lab] == ["ELE-S1"]
    assert lab[0]["levels"][0]["code"] == "ELE-S1-E1"
    await client.post("/api/inventory/furniture/printed", headers=power, json={"furniture_ids": [f["id"]]})
    assert (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json() == []


async def test_area_code_must_be_unique_and_valid(client, enabled, power):
    await _area(client, power, "Elektronik", "EL")
    r = await client.post("/api/inventory/areas", headers=power, json={"name": "Eloxal", "code": "el"})
    assert r.status_code == 409
    r = await client.post("/api/inventory/areas", headers=power, json={"name": "Holz", "code": "H"})
    assert r.status_code == 400


async def test_move_furniture_to_other_area_gets_new_number(client, enabled, power):
    a = await _area(client, power, "Elektronik", "EL")
    b = await _area(client, power, "Holz", "HO")
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": b["id"], "levels": 1})
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": a["id"], "levels": 1})).json()
    assert f["code"] == "EL-S1"
    r = (await client.patch(f"/api/inventory/furniture/{f['id']}", headers=power,
                            json={"area_id": b["id"]})).json()
    assert r["code"] == "HO-S2" and r["label_outdated"] is True


async def test_import_with_errors_and_dry_run(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 1})
    rows = [{"name": "Hammer", "code": "EL-S1-E1", "quantity": 2},
            {"name": "", "code": "EL-S1"},
            {"name": "Feile", "code": "EL-S7"},
            {"name": "Ohne Platz"}]
    r = (await client.post("/api/inventory/items/import", headers=power,
                           json={"rows": rows, "dry_run": True})).json()
    assert r["created"] == 0 and r["valid"] == 2 and [e["line"] for e in r["errors"]] == [2, 3]
    assert (await client.get("/api/inventory/items", headers=power)).json()["total"] == 0
    r = (await client.post("/api/inventory/items/import", headers=power, json={"rows": rows})).json()
    assert r["created"] == 2
    assert (await client.get("/api/inventory/items", headers=power)).json()["total"] == 2


async def test_location_router_integration(client, enabled, power, admin):
    # Neuer Standort ueber die bestehende Maschinen-Standortliste bekommt S0 automatisch
    r = await client.post("/api/locations", headers=power, json={"name": "Textil"})
    assert r.status_code == 200
    loc_id = r.json()["id"]
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    textil = [a for a in tree if a["name"] == "Textil"][0]
    assert [f["number"] for f in textil["furniture"]] == [0]

    # Leerer Bereich laesst sich loeschen (S0 wird mit entfernt) ...
    assert (await client.delete(f"/api/locations/{loc_id}", headers=power)).status_code == 200
    # ... einer mit Moebel nicht
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 1})
    r = await client.delete(f"/api/locations/{area['id']}", headers=power)
    assert r.status_code == 409 and "Möbel" in r.json()["detail"]


async def test_settings_switch_roundtrip(client, admin):
    r = await client.get("/api/settings/public")
    assert r.json()["inventory_enabled"] is False
    r = await client.patch("/api/settings", headers=admin, json={"inventory_enabled": True})
    assert r.status_code == 200 and r.json()["inventory_enabled"] is True
    assert (await client.get("/api/settings/public")).json()["inventory_enabled"] is True


async def test_areas_created_elsewhere_get_zero_rows_lazily(client, enabled, power, db):
    # z.B. ueber CSV-Import oder Backup-Restore angelegt: kein S0 vorhanden
    db.add(MachineLocation(name="Importiert", code="IM"))
    await db.commit()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    assert [f["number"] for f in tree[0]["furniture"]] == [0]
    r = await client.post("/api/inventory/items", headers=power, json={"name": "Kiste", "code": "IM"})
    assert r.status_code == 200 and r.json()["position"]["code"] == "IM-S0"
