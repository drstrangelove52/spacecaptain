import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import MachineLocation
from app.models_inventory import InvFurniture, InvLevel, InvPosition
from app.services import inventory as inv


# ── reine Code-Logik ─────────────────────────────────────────────────────────
def test_short_code_strips_trailing_zeros():
    assert inv.short_code("ELE", 2, 3, 4) == "ELE-M02-E03-P04"
    assert inv.short_code("HOL", 1, 2, 0) == "HOL-M01-E02"
    assert inv.short_code("HOL", 1, 0, 0) == "HOL-M01"
    assert inv.short_code("HOL", 0) == "HOL-M00"
    assert inv.short_code("HOL", 1, 0, 3) == "HOL-M01-E00-P03"   # Position ohne Ebene bleibt eindeutig
    assert inv.short_code(None, 1) == "???-M01"


def test_full_code():
    assert inv.full_code("ELE", 2, 0, 0) == "ELE-M02-E00-P00"


@pytest.mark.parametrize("text,expected", [
    ("ELE", ("ELE", 0, 0, 0)),
    ("ele-m02", ("ELE", 2, 0, 0)),
    ("ELE-M02-E03", ("ELE", 2, 3, 0)),
    ("ELE-M02-E03-P04", ("ELE", 2, 3, 4)),
    (" HOL-M00 ", ("HOL", 0, 0, 0)),
    ("ELE-M2-E3-P4", ("ELE", 2, 3, 4)),          # Eingabe tolerant: ohne führende Null
    ("3DR-M10-E12-P99", ("3DR", 10, 12, 99)),
])
def test_parse_code(text, expected):
    assert inv.parse_code(text) == expected


@pytest.mark.parametrize("text", ["", "E", "EL", "ELE-2-3-4", "ELE-M02-P04-E03", "ELEKTRO-M01", "ELE-M", "!!",
                                  "ELE-S1", "EL-M01"])
def test_parse_code_rejects(text):
    with pytest.raises(HTTPException) as e:
        inv.parse_code(text)
    assert e.value.status_code == 400


def test_normalize_area_code():
    assert inv.normalize_area_code(" ele ") == "ELE"
    for bad in ("E", "EL", "ELEK", "A B", ""):
        with pytest.raises(HTTPException):
            inv.normalize_area_code(bad)


# ── Nullplaetze ──────────────────────────────────────────────────────────────
async def test_ensure_structure_is_idempotent(db):
    db.add_all([MachineLocation(name="Holz", code="HOL"), MachineLocation(name="Laser", code="LAS")])
    await db.commit()

    first = await inv.ensure_structure(db)
    assert first == 6                       # 2x S0 + 2x E0 + 2x P0
    assert await inv.ensure_structure(db) == 0

    furn = (await db.execute(select(InvFurniture))).scalars().all()
    assert sorted(f.number for f in furn) == [0, 0]
    assert (await db.execute(select(InvPosition))).scalars().all()[0].number == 0


async def test_ensure_structure_repairs_missing_zero_rows(db):
    a = MachineLocation(name="Holz", code="HOL")
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
    a = MachineLocation(name="Elektronik", code="ELE")
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
    assert await inv.resolve_position(db, "ELE-M02")


async def test_create_furniture_requires_area_code(db):
    a = MachineLocation(name="Ohne Kuerzel")
    db.add(a)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await inv.create_furniture(db, a, inv.FurnitureKind.schrank, None, 1, 0)
    assert e.value.status_code == 409


async def test_resolve_position_errors_name_the_missing_level(db):
    a = MachineLocation(name="Holz", code="HOL")
    db.add(a)
    await db.commit()
    await inv.ensure_structure(db)
    await inv.create_furniture(db, a, inv.FurnitureKind.regal, None, 2, 0)

    assert (await inv.resolve_position(db, "HOL-M01-E02")).number == 0
    assert (await inv.resolve_position(db, "hol")).number == 0           # S0-E0-P0
    for text, msg in [("XXX", "Bereich"), ("HOL-M09", "HOL-M09 gibt"), ("HOL-M01-E07", "HOL-M01-E07 gibt"),
                      ("HOL-M01-E01-P05", "HOL-M01-E01-P05 gibt")]:
        with pytest.raises(HTTPException) as e:
            await inv.resolve_position(db, text)
        assert e.value.status_code == 404 and msg in e.value.detail


# ── API ──────────────────────────────────────────────────────────────────────
async def _area(client, hdr, name="Elektronik", code="ELE"):
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
    assert r.status_code == 200 and r.json()["code"] == "ELE-M01"
    r = await client.post("/api/inventory/items", headers=manager,
                          json={"name": "Lötkolben", "code": "ELE-M01-E01"})
    assert r.status_code == 200
    assert (await client.patch(f"/api/inventory/areas/{area['id']}", headers=manager,
                               json={"color": "#fff"})).status_code == 403


async def test_item_lifecycle_search_and_move(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power,
                      json={"area_id": area["id"], "kind": "schrank", "levels": 3, "positions": 2})

    r = await client.post("/api/inventory/items", headers=power, json={
        "name": "Akkuschrauber", "synonyms": "Bohrschrauber, Schrauber", "code": "ELE-M01-E02-P01"})
    item = r.json()
    assert item["position"]["code"] == "ELE-M01-E02-P01"
    assert item["position"]["path"] == "Elektronik › Schrank 1 › Ebene 2 › Platz 1"

    # Suche ueber Synonym, Teilwort, Gross-/Kleinschreibung und Code
    for q in ("Bohrschrauber", "schrauber", "AKKU", "ELE-M01-E02", "ele-m01", "ELE"):
        res = (await client.get("/api/inventory/search", params={"q": q}, headers=power)).json()
        assert [x["name"] for x in res if x["type"] == "tool"] == ["Akkuschrauber"], q
    assert (await client.get("/api/inventory/search", params={"q": "Hammer"}, headers=power)).json() == []
    # Anderer Code trifft nicht
    res = (await client.get("/api/inventory/search", params={"q": "ELE-M01-E03"}, headers=power)).json()
    assert [x for x in res if x["type"] == "tool"] == []

    # Umlagern per Kurzcode, danach Platz entfernen
    r = await client.patch(f"/api/inventory/items/{item['id']}", headers=power, json={"code": "ELE-M01-E03"})
    assert r.json()["position"]["code"] == "ELE-M01-E03"
    r = await client.patch(f"/api/inventory/items/{item['id']}", headers=power, json={"unplace": True})
    assert r.json()["position"] is None
    lst = (await client.get("/api/inventory/items", params={"unplaced": True}, headers=power)).json()
    assert lst["total"] == 1

    r = await client.delete(f"/api/inventory/items/{item['id']}", headers=power)
    assert r.json() == {"ok": True}


async def test_unknown_code_is_rejected(client, enabled, power):
    await _area(client, power)
    r = await client.post("/api/inventory/items", headers=power, json={"name": "X", "code": "ELE-M05"})
    assert r.status_code == 404 and "ELE-M05" in r.json()["detail"]


async def test_level_open_filter_and_s0(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power,
                      json={"area_id": area["id"], "kind": "regal", "levels": 2})
    await client.post("/api/inventory/items", headers=power, json={"name": "Kiste", "code": "ELE"})          # S0
    await client.post("/api/inventory/items", headers=power, json={"name": "Offen", "code": "ELE-M01"})       # E0
    await client.post("/api/inventory/items", headers=power, json={"name": "Fest", "code": "ELE-M01-E01"})
    r = (await client.get("/api/inventory/items", params={"level_open": True}, headers=power)).json()
    assert [i["name"] for i in r["items"]] == ["Offen"]          # S0 zaehlt nicht als «Ebene offen»
    r = (await client.get("/api/inventory/code/ELE-M01", headers=power)).json()
    assert sorted(i["name"] for i in r["items"]) == ["Fest", "Offen"] and r["scope"] == "furniture"
    r = (await client.get("/api/inventory/code/ELE", headers=power)).json()
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

    await client.post("/api/inventory/items", headers=power, json={"name": "Zange", "code": "ELE-M01-E01"})
    assert (await client.delete(f"/api/inventory/levels/{e1['id']}", headers=power)).status_code == 409
    assert (await client.delete(f"/api/inventory/furniture/{f['id']}", headers=power)).status_code == 409

    lst = (await client.get("/api/inventory/items", headers=power)).json()["items"]
    await client.patch(f"/api/inventory/items/{lst[0]['id']}", headers=power, json={"unplace": True})
    assert (await client.delete(f"/api/inventory/furniture/{f['id']}", headers=power)).status_code == 200


async def test_area_code_change_marks_labels_outdated(client, enabled, power):
    area = await _area(client, power)
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": area["id"], "levels": 1})).json()
    assert f["label_outdated"] is True        # neu angelegt = Etikett noch nicht gedruckt
    await client.post("/api/inventory/furniture/printed", headers=power, json={"furniture_ids": [f["id"]]})
    assert (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json() == []
    r = await client.patch(f"/api/inventory/areas/{area['id']}", headers=power, json={"code": "ELK"})
    assert r.json()["code"] == "ELK"
    lab = (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json()
    assert [x["code"] for x in lab] == ["ELK-M01"]
    assert lab[0]["levels"][0]["code"] == "ELK-M01-E01"
    await client.post("/api/inventory/furniture/printed", headers=power, json={"furniture_ids": [f["id"]]})
    assert (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json() == []


async def test_area_code_must_be_unique_and_valid(client, enabled, power):
    await _area(client, power, "Elektronik", "ELE")
    r = await client.post("/api/inventory/areas", headers=power, json={"name": "Eloxal", "code": "ele"})
    assert r.status_code == 409
    r = await client.post("/api/inventory/areas", headers=power, json={"name": "Holz", "code": "H"})
    assert r.status_code == 400


async def test_move_furniture_to_other_area_gets_new_number(client, enabled, power):
    a = await _area(client, power, "Elektronik", "ELE")
    b = await _area(client, power, "Holz", "HOL")
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": b["id"], "levels": 1})
    f = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": a["id"], "levels": 1})).json()
    assert f["code"] == "ELE-M01"
    r = (await client.patch(f"/api/inventory/furniture/{f['id']}", headers=power,
                            json={"area_id": b["id"]})).json()
    assert r["code"] == "HOL-M02" and r["label_outdated"] is True


async def test_import_with_errors_and_dry_run(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 1})
    rows = [{"name": "Hammer", "code": "ELE-M01-E01", "quantity": 2},
            {"name": "", "code": "ELE-M01"},
            {"name": "Feile", "code": "ELE-M07"},
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
    db.add(MachineLocation(name="Importiert", code="IMP"))
    await db.commit()
    tree = (await client.get("/api/inventory/tree", headers=power)).json()
    assert [f["number"] for f in tree[0]["furniture"]] == [0]
    r = await client.post("/api/inventory/items", headers=power, json={"name": "Kiste", "code": "IMP"})
    assert r.status_code == 200 and r.json()["position"]["code"] == "IMP-M00"


# ── Kuerzel-Vorschlag und Zusammenspiel mit «Standorte» ──────────────────────
@pytest.mark.parametrize("name,expected", [
    ("Elektronik", "ELE"), ("Precious Plastic", "PPL"), ("3D-Druck", "3DR"),
    ("Werkzeugwand", "WER"), ("Äpfel", "APF"), ("Öl-Lager", "OLA"), ("Hilti Schrank 1", "HS1"),
    ("Ab", "AB2"),
])
async def test_suggest_area_code(db, name, expected):
    assert await inv.suggest_area_code(db, name) == expected


async def test_suggest_area_code_skips_taken(db):
    db.add_all([MachineLocation(name="Holz", code="HOL"), MachineLocation(name="Hobby", code="HOB")])
    await db.commit()
    assert await inv.suggest_area_code(db, "Holzbau") == "HOZ"        # HOL vergeben → 2 Buchstaben + 4. Buchstabe
    db.add(MachineLocation(name="Holzbau", code="HOZ"))
    await db.commit()
    assert await inv.suggest_area_code(db, "Holzzaun") == "HO2"       # auch HOZ vergeben → Ziffer


async def test_legacy_two_letter_codes_are_upgraded_to_three(db):
    a = MachineLocation(name="Elektronik", code="EL")                 # Kürzel aus einer früheren Fassung
    b = MachineLocation(name="Holz", code="HOLZ")                     # zu lang
    db.add_all([a, b])
    await db.commit()
    f = await inv.create_furniture(db, a, inv.FurnitureKind.schrank, None, 1, 0)
    await db.execute(InvFurniture.__table__.update().where(InvFurniture.id == f.id).values(label_outdated=False))
    await db.commit()
    await db.refresh(f)
    assert f.label_outdated is False                 # Ausgangslage: Etikett gilt als gedruckt

    await inv.ensure_structure(db)
    await db.refresh(a); await db.refresh(b); await db.refresh(f)
    assert (a.code, b.code) == ("ELE", "HOL")
    assert f.label_outdated is True                  # Code hat sich geändert → Etikett neu drucken
    assert await inv.upgrade_legacy_codes(db) == 0   # idempotent


async def test_legacy_codes_are_upgraded_lazily_via_api(client, enabled, power, db):
    db.add(MachineLocation(name="Elektronik", code="EL"))
    await db.commit()
    areas = (await client.get("/api/inventory/areas", headers=power)).json()
    assert [a["code"] for a in areas] == ["ELE"]


async def test_new_location_gets_code_and_color_when_module_on(client, enabled, power):
    r = await client.post("/api/locations", headers=power, json={"name": "Elektronik"})
    assert r.status_code == 200
    assert r.json()["code"] == "ELE" and r.json()["color"].startswith("#")
    # ... und ist sofort im Inventar nutzbar
    area_id = r.json()["id"]
    f = await client.post("/api/inventory/furniture", headers=power, json={"area_id": area_id, "levels": 1})
    assert f.status_code == 200 and f.json()["code"] == "ELE-M01"


async def test_new_location_without_module_stays_untouched(client, power):
    r = await client.post("/api/locations", headers=power, json={"name": "Elektronik"})
    assert r.status_code == 200 and r.json()["code"] is None and r.json()["color"] is None


async def test_location_with_explicit_code(client, enabled, power):
    r = await client.post("/api/locations", headers=power, json={"name": "Elektronik", "code": "ele", "color": "#112233"})
    assert r.json()["code"] == "ELE" and r.json()["color"] == "#112233"
    assert (await client.post("/api/locations", headers=power, json={"name": "Eloxal", "code": "ELE"})).status_code == 409
    assert (await client.post("/api/locations", headers=power, json={"name": "Holz", "code": "H"})).status_code == 400
    # Auch das ungueltige Kuerzel darf keinen halbfertigen Standort hinterlassen... Name bleibt frei nutzbar
    listing = (await client.get("/api/locations", headers=power)).json()
    assert {x["name"] for x in listing} >= {"Elektronik"}


async def test_location_patch_code_marks_labels_outdated(client, enabled, power):
    loc = (await client.post("/api/locations", headers=power, json={"name": "Elektronik"})).json()
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": loc["id"], "levels": 1})
    r = await client.patch(f"/api/locations/{loc['id']}", headers=power, json={"code": "ELX", "color": "#abcdef"})
    assert r.status_code == 200 and r.json()["code"] == "ELX" and r.json()["color"] == "#abcdef"
    lab = (await client.get("/api/inventory/labels", params={"outdated": True}, headers=power)).json()
    assert [x["code"] for x in lab] == ["ELX-M01"]
    # Leeres Kuerzel im Standorte-Dialog = unveraendert
    r = await client.patch(f"/api/locations/{loc['id']}", headers=power, json={"name": "Elektronik 2", "code": ""})
    assert r.json()["code"] == "ELX" and r.json()["name"] == "Elektronik 2"


async def test_code_cannot_be_removed_while_furniture_exists(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 1})
    r = await client.patch(f"/api/inventory/areas/{area['id']}", headers=power, json={"code": ""})
    assert r.status_code == 409


async def test_assign_missing_codes_dry_run_and_apply(client, enabled, power, db):
    db.add_all([MachineLocation(name="Holz"), MachineLocation(name="Holzbau"),
                MachineLocation(name="Laser", code="LAS"), MachineLocation(name="3D-Druck")])
    await db.commit()
    r = (await client.post("/api/inventory/areas/assign-missing-codes", headers=power)).json()
    assert r["dry_run"] is True
    assert {a["name"]: a["code"] for a in r["areas"]} == {"Holz": "HOL", "Holzbau": "HO2", "3D-Druck": "3DR"}
    areas = (await client.get("/api/inventory/areas", headers=power)).json()
    assert [a["code"] for a in areas if a["name"] == "Holz"] == [None]      # Trockenlauf aendert nichts

    r = (await client.post("/api/inventory/areas/assign-missing-codes", params={"dry_run": False}, headers=power)).json()
    assert len(r["areas"]) == 3
    areas = {a["name"]: a for a in (await client.get("/api/inventory/areas", headers=power)).json()}
    assert areas["Holz"]["code"] == "HOL" and areas["Holzbau"]["code"] == "HO2" and areas["Laser"]["code"] == "LAS"
    colors = [a["color"] for a in areas.values() if a["name"] != "Laser"]
    assert all(colors) and len(set(colors)) == len(colors)      # jede neue Farbe ist verschieden
    # Zweiter Lauf: nichts mehr zu tun
    r = (await client.post("/api/inventory/areas/assign-missing-codes", params={"dry_run": False}, headers=power)).json()
    assert r["areas"] == []


async def test_assign_missing_codes_requires_power_manager(client, enabled, manager):
    r = await client.post("/api/inventory/areas/assign-missing-codes", headers=manager)
    assert r.status_code == 403


async def test_suggest_code_endpoint(client, enabled, manager):
    r = await client.get("/api/inventory/areas/suggest-code", params={"name": "Precious Plastic"}, headers=manager)
    assert r.json() == {"code": "PPL"}


async def test_get_single_item_for_qr_landing(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 2})
    item = (await client.post("/api/inventory/items", headers=power,
                              json={"name": "Lineal 30 cm", "quantity": 12, "code": "ELE-M01-E02"})).json()
    r = await client.get(f"/api/inventory/items/{item['id']}", headers=power)
    assert r.status_code == 200
    assert r.json()["name"] == "Lineal 30 cm" and r.json()["quantity"] == 12
    assert r.json()["position"]["code"] == "ELE-M01-E02"
    # nach dem Umlagern bleibt derselbe Link gueltig und zeigt den neuen Ort
    await client.patch(f"/api/inventory/items/{item['id']}", headers=power, json={"code": "ELE-M01-E01"})
    assert (await client.get(f"/api/inventory/items/{item['id']}", headers=power)).json()["position"]["code"] == "ELE-M01-E01"
    assert (await client.get("/api/inventory/items/99999", headers=power)).status_code == 404


async def test_labels_contain_contents_and_positions(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power,
                      json={"area_id": area["id"], "levels": 2, "positions": 2})
    mk = lambda name, code, qty=1: client.post("/api/inventory/items", headers=power,
                                               json={"name": name, "code": code, "quantity": qty})
    await mk("Lineal 30 cm", "ELE-M01-E02-P01", 12)
    await mk("Zollstock", "ELE-M01-E02-P02", 5)
    await mk("Hammer", "ELE-M01-E02", 1)             # Ebene ohne feste Position (P0)
    await mk("Zange", "ELE-M01-E01-P01")
    data = (await client.get("/api/inventory/labels", headers=power)).json()
    f = data[0]
    assert f["code"] == "ELE-M01" and f["item_count"] == 4
    e1, e2 = f["levels"]
    assert e2["code"] == "ELE-M01-E02" and e2["item_count"] == 3
    assert [i["name"] for i in e2["items"]] == ["Hammer", "Lineal 30 cm", "Zollstock"]     # alphabetisch
    assert {"name": "Lineal 30 cm", "quantity": 12} in e2["items"]
    assert [i["name"] for i in e1["items"]] == ["Zange"]
    p1, p2 = e2["positions"]
    assert (p1["code"], p1["item_count"]) == ("ELE-M01-E02-P01", 1) and p1["items"][0]["name"] == "Lineal 30 cm"
    assert p2["code"] == "ELE-M01-E02-P02" and p2["items"][0]["quantity"] == 5
    assert e1["positions"][1]["items"] == [] and e1["positions"][1]["item_count"] == 0


async def test_labels_cap_contents(client, enabled, power):
    area = await _area(client, power)
    await client.post("/api/inventory/furniture", headers=power, json={"area_id": area["id"], "levels": 1})
    for i in range(20):
        await client.post("/api/inventory/items", headers=power, json={"name": f"Teil {i:02d}", "code": "ELE-M01-E01"})
    lvl = (await client.get("/api/inventory/labels", headers=power)).json()[0]["levels"][0]
    assert lvl["item_count"] == 20 and len(lvl["items"]) == 12


# ── Buchhaltungsfelder bei Werkzeug (versicherte Handgeräte) ─────────────────
async def test_item_accounting_fields_roundtrip(client, enabled, power, db):
    from app.models import MachineLocation, MachineOwner
    db.add_all([MachineLocation(name="Elektronik", code="ELE"), MachineOwner(name="Verein")])
    await db.commit()
    owner = (await db.execute(__import__("sqlalchemy").select(MachineOwner))).scalars().first()
    r = await client.post("/api/inventory/items", headers=power, json={
        "name": "Akkuschrauber", "code": "ELE", "serial_number": "SN-1", "purchase_date": "2025-03-01",
        "value_new": 249.9, "owner_id": owner.id})
    assert r.status_code == 200, r.text
    it = r.json()
    assert (it["serial_number"], it["purchase_date"], it["value_new"], it["owner_id"]) == ("SN-1", "2025-03-01", 249.9, owner.id)
    await client.post("/api/inventory/items", headers=power, json={"name": "Lineal", "code": "ELE"})
    valued = (await client.get("/api/inventory/items", params={"valued": True}, headers=power)).json()
    assert [i["name"] for i in valued["items"]] == ["Akkuschrauber"]
    r = await client.patch(f"/api/inventory/items/{it['id']}", headers=power, json={"value_new": None, "owner_id": None})
    assert r.json()["value_new"] is None and r.json()["owner_id"] is None and r.json()["serial_number"] == "SN-1"
    bad = await client.patch(f"/api/inventory/items/{it['id']}", headers=power, json={"owner_id": 9999})
    assert bad.status_code == 400


async def test_item_accounting_fields_survive_backup(client, enabled, power, admin, db):
    from sqlalchemy import select, delete
    from app.models import MachineLocation, MachineOwner
    from app.models_inventory import InvItem
    db.add_all([MachineLocation(name="Elektronik", code="ELE"), MachineOwner(name="Verein")])
    await db.commit()
    owner = (await db.execute(select(MachineOwner))).scalars().first()
    await client.post("/api/inventory/items", headers=power, json={
        "name": "Akkuschrauber", "code": "ELE", "value_new": 100.0, "purchase_date": "2025-03-01", "owner_id": owner.id})
    data = (await client.get("/api/backup/export", headers=admin)).json()
    exp = [i for i in data["inventory"]["items"] if i["name"] == "Akkuschrauber"][0]
    assert exp["value_new"] == 100.0 and exp["owner"] == "Verein" and exp["purchase_date"] == "2025-03-01"
    await db.execute(delete(InvItem))
    await db.commit()
    r = await client.post("/api/backup/import", headers=admin, json=data)
    assert r.status_code == 200, r.text
    back = (await client.get("/api/inventory/items", headers=power)).json()["items"][0]
    assert back["value_new"] == 100.0 and back["purchase_date"] == "2025-03-01" and back["owner_id"] == owner.id
