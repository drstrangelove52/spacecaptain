"""
Inventar-Modul: Lagerort-Codes, Nullplaetze (M00/E00/P00) und Code-Aufloesung.

Code-Schema:  <Bereich>-M<Möbel>-E<Ebene>-P<Position>   z.B. ELE-M02-E03-P04
  Bereich = genau 3 Zeichen; Möbel = Schrank, Regal, Wand oder Tisch; Nummern zweistellig mit führender Null.
Die 00 bedeutet auf jeder Stufe «nicht unterteilt oder noch nicht festgelegt».
Siehe docs/inventar-konzept.md.
"""
import re
import unicodedata
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineLocation, Machine, MachineCategory
from app.services.system_settings import get_system_settings
from app.models_inventory import InvFurniture, InvLevel, InvPosition, InvItem, InvPlacement, FurnitureKind

AREA_LEN = 3
AREA_CODE_RE = re.compile(r"^[A-Z0-9]{3}$")
# Eingabe tolerant (M1 = M01), Ausgabe immer zweistellig
_CODE_RE = re.compile(r"^([A-Z0-9]{3})(?:-M(\d{1,3}))?(?:-E(\d{1,3}))?(?:-P(\d{1,3}))?$")


# ── Codes ────────────────────────────────────────────────────────────────────
def normalize_area_code(raw: str) -> str:
    code = (raw or "").strip().upper()
    if not AREA_CODE_RE.match(code):
        raise HTTPException(400, "Kürzel: genau 3 Zeichen, nur Buchstaben und Ziffern (z.B. ELE)")
    return code


def full_code(area_code: Optional[str], m: int, e: int, p: int) -> str:
    return f"{area_code or '???'}-M{m:02d}-E{e:02d}-P{p:02d}"


def short_code(area_code: Optional[str], m: int, e: int = 0, p: int = 0) -> str:
    """Code ohne abschliessende Nullen: HOL-M01-E02 statt HOL-M01-E02-P00."""
    parts = [area_code or "???", f"M{m:02d}"]
    if e or p:
        parts.append(f"E{e:02d}")
    if p:
        parts.append(f"P{p:02d}")
    return "-".join(parts)


def parse_code(text: str) -> tuple[str, int, int, int]:
    """Zerlegt einen Code. Fehlende Stufen werden 0 (z.B. «ELE-M02» = ELE-M02-E00-P00)."""
    m = _CODE_RE.match((text or "").strip().upper())
    if not m:
        raise HTTPException(400, f"Ungültiger Code: {text!r} (Beispiel: ELE-M02-E03-P04)")
    area, mm, e, p = m.groups()
    return area, int(mm or 0), int(e or 0), int(p or 0)


_PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed",
            "#0891b2", "#db2777", "#4b5563", "#65a30d", "#ea580c"]


def default_color(code: str, used=()) -> str:
    """Farbe fuer einen neuen Bereich: stabil aus dem Kuerzel, aber eine noch nicht
    vergebene bevorzugen (die Palette hat 10 Farben, danach wiederholen sie sich)."""
    start = sum(ord(c) for c in code) % len(_PALETTE)
    used = {u.lower() for u in used if u}
    for i in range(len(_PALETTE)):
        c = _PALETTE[(start + i) % len(_PALETTE)]
        if c.lower() not in used:
            return c
    return _PALETTE[start]


async def _used_colors(db: AsyncSession) -> set:
    return {c.lower() for c in (await db.execute(
        select(MachineLocation.color).where(MachineLocation.color.is_not(None)))).scalars().all() if c}


def _ascii_upper(text: str) -> str:
    text = (text or "").replace("ß", "ss")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


async def suggest_area_code(db: AsyncSession, name: str, exclude_id: Optional[int] = None) -> str:
    """Schlägt ein freies 3-Zeichen-Kürzel aus dem Namen vor: bei mehreren Wörtern die Initialen,
    aufgefüllt mit den folgenden Buchstaben des letzten Wortes («Precious Plastic» → PPL, «3D-Druck» → 3DR),
    sonst die ersten drei Buchstaben («Elektronik» → ELE); als Rückfalloption zwei Buchstaben plus Ziffer."""
    words = [re.sub(r"[^A-Z0-9]", "", w) for w in re.split(r"[\s\-_/]+", _ascii_upper(name))]
    words = [w for w in words if w]
    flat = "".join(words)
    cands: list[str] = []
    if len(words) >= 2:
        ini = "".join(w[0] for w in words)
        cands.append((ini + words[-1][1:])[:AREA_LEN] if len(ini) < AREA_LEN else ini[:AREA_LEN])
    cands.append(flat[:AREA_LEN])
    if len(flat) >= 4:
        cands.append(flat[:2] + flat[3])              # HOLZ → HOZ, falls HOL vergeben
    base = (flat[:2] or "XX").ljust(2, "X")
    cands += [f"{base}{i}" for i in range(2, 10)]      # HO2 … HO9
    q = select(MachineLocation.code).where(MachineLocation.code.is_not(None))
    if exclude_id is not None:
        q = q.where(MachineLocation.id != exclude_id)
    used = set((await db.execute(q)).scalars().all())
    for c in cands:
        if AREA_CODE_RE.match(c) and c not in used:
            return c
    raise HTTPException(409, "Kein freies Kürzel gefunden — bitte von Hand vergeben")


async def upgrade_legacy_codes(db: AsyncSession, commit: bool = True) -> int:
    """Kürzel aus früheren Fassungen (2 oder 4 Zeichen) werden auf 3 Zeichen umgestellt. Die Etiketten der
    betroffenen Möbel gelten danach als «neu/veraltet». Idempotent; gibt die Anzahl der Umstellungen zurück."""
    areas = (await db.execute(select(MachineLocation).where(
        MachineLocation.code.is_not(None), func.length(MachineLocation.code) != AREA_LEN)
        .order_by(MachineLocation.id))).scalars().all()
    for a in areas:
        a.code = await suggest_area_code(db, a.name, exclude_id=a.id)
        await db.flush()
        for f in (await db.execute(select(InvFurniture).where(
                InvFurniture.area_id == a.id, InvFurniture.number > 0))).scalars():
            f.label_outdated = True
    if areas:
        await (db.commit() if commit else db.flush())
    return len(areas)


async def set_area_code(db: AsyncSession, area: MachineLocation, raw: Optional[str]) -> bool:
    """Setzt das Kuerzel eines Bereichs (validiert, eindeutig). Aendert sich der Code, sind die
    Etiketten aller Moebel des Bereichs veraltet. Gibt zurueck, ob sich etwas geaendert hat."""
    new = normalize_area_code(raw) if (raw or "").strip() else None
    if new == area.code:
        return False
    if new is None:
        real = await db.scalar(select(func.count(InvFurniture.id)).where(
            InvFurniture.area_id == area.id, InvFurniture.number > 0))
        if real:
            raise HTTPException(409, "Das Kürzel lässt sich nicht entfernen, solange der Bereich Möbel hat")
    elif await db.scalar(select(MachineLocation.id).where(
            MachineLocation.code == new, MachineLocation.id != area.id)):
        raise HTTPException(409, f"Kürzel «{new}» ist schon vergeben")
    area.code = new
    for f in (await db.execute(select(InvFurniture).where(
            InvFurniture.area_id == area.id, InvFurniture.number > 0))).scalars():
        f.label_outdated = True
    return True


async def assign_missing_codes(db: AsyncSession, dry_run: bool) -> list[dict]:
    """Vergibt allen Bereichen ohne Kuerzel einen Vorschlag (und eine Farbe, falls leer)."""
    areas = (await db.execute(select(MachineLocation).where(
        or_(MachineLocation.code.is_(None), MachineLocation.code == ""))
        .order_by(MachineLocation.sort_order, MachineLocation.name))).scalars().all()
    # Erst alle Vorschlaege berechnen, danach anwenden: sonst sieht die naechste Abfrage per
    # Autoflush schon das eben vergebene Kuerzel und Vorschau und Ergebnis wuerden abweichen.
    out, taken = [], set()
    for a in areas:
        code = await suggest_area_code(db, a.name, exclude_id=a.id)
        n = 2
        while code in taken:               # innerhalb dieses Laufs nicht doppelt vergeben
            code = f"{code[:2]}{n}"
            n += 1
        taken.add(code)
        out.append({"id": a.id, "name": a.name, "code": code})
    if not dry_run:
        used = await _used_colors(db)
        for a, o in zip(areas, out):
            a.code = o["code"]
            if not a.color:
                a.color = default_color(o["code"], used)
                used.add(a.color.lower())
    if not dry_run:
        await db.commit()
    return out


# ── Nullplaetze ──────────────────────────────────────────────────────────────
async def ensure_structure(db: AsyncSession, commit: bool = True, align: bool = False) -> int:
    """Legt fehlende Nullplaetze an: M00 je Bereich, E00 je Moebel, P00 je Ebene.
    Idempotent, gibt die Anzahl neu angelegter Zeilen zurueck."""
    created = await upgrade_legacy_codes(db, commit)

    area_ids = (await db.execute(select(MachineLocation.id))).scalars().all()
    have = set((await db.execute(
        select(InvFurniture.area_id).where(InvFurniture.number == 0)
    )).scalars().all())
    for aid in area_ids:
        if aid not in have:
            db.add(InvFurniture(area_id=aid, number=0, kind=FurnitureKind.bereich,
                                name="Im Bereich (ohne Möbel)"))
            created += 1
    await db.flush()

    furn_ids = (await db.execute(select(InvFurniture.id))).scalars().all()
    have = set((await db.execute(
        select(InvLevel.furniture_id).where(InvLevel.number == 0)
    )).scalars().all())
    for fid in furn_ids:
        if fid not in have:
            db.add(InvLevel(furniture_id=fid, number=0))
            created += 1
    await db.flush()

    level_ids = (await db.execute(select(InvLevel.id))).scalars().all()
    have = set((await db.execute(
        select(InvPosition.level_id).where(InvPosition.number == 0)
    )).scalars().all())
    for lid in level_ids:
        if lid not in have:
            db.add(InvPosition(level_id=lid, number=0))
            created += 1
    created += await sync_machine_areas(db)
    if align:
        created += await align_categories(db)
    await (db.commit() if commit else db.flush())
    return created


async def ensure_structure_if_needed(db: AsyncSession) -> None:
    """Guenstiger Vorab-Check (2 Zaehlabfragen) — nur bei Luecken wird nachgezogen.
    Noetig, weil Standorte auch ueber CSV-Import oder Backup-Restore entstehen."""
    areas = await db.scalar(select(func.count(MachineLocation.id))) or 0
    zero = await db.scalar(select(func.count(InvFurniture.id)).where(InvFurniture.number == 0)) or 0
    legacy = await db.scalar(select(func.count(MachineLocation.id)).where(
        MachineLocation.code.is_not(None), func.length(MachineLocation.code) != AREA_LEN)) or 0
    if zero < areas or legacy or await machines_need_sync(db) or await categories_need_align(db):
        await ensure_structure(db, align=True)


async def ensure_area_structure(db: AsyncSession, area_id: int) -> None:
    """Nullplaetze fuer einen einzelnen (neuen) Bereich — guenstig, ohne Vollscan."""
    exists = await db.scalar(select(InvFurniture.id).where(
        InvFurniture.area_id == area_id, InvFurniture.number == 0))
    if exists:
        return
    f = InvFurniture(area_id=area_id, number=0, kind=FurnitureKind.bereich,
                     name="Im Bereich (ohne Möbel)")
    f.levels.append(InvLevel(number=0, positions=[InvPosition(number=0)]))
    db.add(f)
    await db.commit()


async def create_furniture(db: AsyncSession, area: MachineLocation, kind: FurnitureKind,
                           name: Optional[str], levels: int, positions: int,
                           note: Optional[str] = None) -> InvFurniture:
    """Legt ein Moebel mit E0 (+P0), `levels` echten Ebenen und je `positions` Positionen an."""
    if not area.code:
        raise HTTPException(409, "Der Bereich braucht zuerst ein Kürzel (z.B. EL)")
    top = await db.scalar(select(func.max(InvFurniture.number)).where(InvFurniture.area_id == area.id))
    number = max(top or 0, 0) + 1
    # neu angelegt = Etikett noch nicht gedruckt (wird nach dem Druck zurückgesetzt)
    f = InvFurniture(area_id=area.id, number=number, kind=kind, name=(name or None), note=note,
                     label_outdated=True)
    f.levels.append(InvLevel(number=0, positions=[InvPosition(number=0)]))
    for n in range(1, levels + 1):
        lv = InvLevel(number=n, positions=[InvPosition(number=0)])
        lv.positions.extend(InvPosition(number=k) for k in range(1, positions + 1))
        f.levels.append(lv)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


async def add_levels(db: AsyncSession, furniture: InvFurniture, count: int, positions: int) -> list[InvLevel]:
    top = await db.scalar(select(func.max(InvLevel.number)).where(InvLevel.furniture_id == furniture.id))
    start = max(top or 0, 0) + 1
    created = []
    for n in range(start, start + count):
        lv = InvLevel(furniture_id=furniture.id, number=n, positions=[InvPosition(number=0)])
        lv.positions.extend(InvPosition(number=k) for k in range(1, positions + 1))
        db.add(lv)
        created.append(lv)
    await db.commit()
    return created


async def add_positions(db: AsyncSession, level: InvLevel, count: int) -> list[InvPosition]:
    top = await db.scalar(select(func.max(InvPosition.number)).where(InvPosition.level_id == level.id))
    start = max(top or 0, 0) + 1
    created = [InvPosition(level_id=level.id, number=n) for n in range(start, start + count)]
    db.add_all(created)
    await db.commit()
    return created


# ── Maschinen ↔ Bereich ──────────────────────────────────────────────────────
# `machines.location` (Text) bleibt fuer die bisherigen Ansichten erhalten, `machines.area_id` ist der massgebliche
# Bereich des Inventar-Moduls. Die Formulare der Maschinen schreiben nur den Text — er wird hier nachgezogen.
def _machine_text_conds():
    return (Machine.location.is_not(None), Machine.location != "")


async def machines_need_sync(db: AsyncSession) -> bool:
    """Stimmen `area_id` und Standort-Text bei allen Maschinen ueberein? Der Vergleich passiert in Python, NICHT per SQL:
    machines (init.sql) und machine_locations (ORM) haben je nach Installation verschiedene Sortierungen, ein Vergleich der
    Textspalten bricht mit «Illegal mix of collations» ab."""
    by_name = {a.name.lower(): a.id for a in (await db.execute(select(MachineLocation))).scalars().all()}
    for loc, aid in (await db.execute(select(Machine.location, Machine.area_id))).all():
        txt = (loc or "").strip().lower()
        want = by_name.get(txt) if txt else None
        if want != aid:                       # None == None: kein Text/unbekannter Text und kein Bereich → in Ordnung
            return True
    return False


async def sync_machine_areas(db: AsyncSession) -> int:
    """Zieht `area_id` aus dem Standort-Text nach: Text → Bereich (ohne Gross-/Kleinschreibung); leerer oder keinem Bereich
    entsprechender Text → kein Bereich (der Text selbst bleibt unveraendert). Gibt die Anzahl Aenderungen zurueck."""
    by_name = {a.name.lower(): a.id for a in (await db.execute(select(MachineLocation))).scalars().all()}
    changed = 0
    for m in (await db.execute(select(Machine))).scalars().all():
        txt = (m.location or "").strip()
        if not txt:
            if m.area_id is not None:
                m.area_id = None
                changed += 1
            continue
        aid = by_name.get(txt.lower())
        if m.area_id != aid:                  # auch Text ohne passenden Bereich: dann kein Bereich
            m.area_id = aid
            changed += 1
            await _clear_foreign_placement(db, m)
    if changed:
        await db.flush()
    return changed


async def _clear_foreign_placement(db: AsyncSession, machine: Machine) -> None:
    """«Steht auf» gilt nur im Bereich der Maschine: wechselt der Bereich, entfaellt Moebel und Ebene."""
    pl = await db.get(InvPlacement, machine.id)
    if pl and pl.furniture_id:
        f = await db.get(InvFurniture, pl.furniture_id)
        if not f or f.area_id != machine.area_id:
            pl.furniture_id = None
            pl.level_id = None


async def sync_machine_area_from_text(db: AsyncSession, machine: Machine) -> None:
    """Fuer einzelne Maschine nach Anlegen/Bearbeiten ueber das Maschinenformular."""
    txt = (machine.location or "").strip()
    if not txt:
        machine.area_id = None
    else:
        area = await db.scalar(select(MachineLocation).where(func.lower(MachineLocation.name) == txt.lower()))
        if area:
            machine.area_id = area.id
    await _clear_foreign_placement(db, machine)
    if await inventory_enabled(db):
        await align_categories(db)
    await db.commit()


async def delete_placement(db: AsyncSession, machine_id: int) -> None:
    pl = await db.get(InvPlacement, machine_id)
    if pl:
        await db.delete(pl)


# ── Kategorie aus dem Bereich (bei aktivem Inventar) ─────────────────────────
# Bereich und Kategorie sagten bei euch dasselbe. Bei aktivem Inventar ist der Bereich das einzige Ordnungsmerkmal; die
# Kategorie der Maschine wird daraus abgeleitet (gleicher Name, ohne Bereich «Sonstiges»). Die Spalte `category` bleibt
# bestehen, damit Filter, Statistik, Gaeste-Ansicht, CSV und MCP unveraendert funktionieren.
DEFAULT_CATEGORY = "Sonstiges"


async def inventory_enabled(db: AsyncSession) -> bool:
    return bool((await get_system_settings(db)).inventory_enabled)


async def _area_names(db: AsyncSession) -> dict:
    return {a.id: a.name for a in (await db.execute(select(MachineLocation))).scalars().all()}


async def categories_need_align(db: AsyncSession) -> bool:
    names = await _area_names(db)
    for cat, aid in (await db.execute(select(Machine.category, Machine.area_id))).all():
        if (cat or "") != ((names.get(aid) if aid else None) or DEFAULT_CATEGORY):
            return True
    have = {(c or "").lower() for c in (await db.execute(select(MachineCategory.name))).scalars().all()}
    return any(n.lower() not in have for n in set(names.values()) | {DEFAULT_CATEGORY})


async def align_categories(db: AsyncSession) -> int:
    """Legt fehlende Kategorien fuer alle Bereiche (und «Sonstiges») an und setzt die Kategorie jeder Maschine auf den
    Namen ihres Bereichs. Idempotent; gibt die Anzahl geaenderter Maschinen zurueck."""
    names = await _area_names(db)
    cats = (await db.execute(select(MachineCategory))).scalars().all()
    have = {(c.name or "").lower() for c in cats}
    order = max([c.sort_order for c in cats] + [0]) + 1
    for n in sorted(set(names.values()) | {DEFAULT_CATEGORY}, key=str.lower):
        if n.lower() not in have:
            db.add(MachineCategory(name=n, icon="🔧", sort_order=order))
            order += 1
    changed = 0
    for m in (await db.execute(select(Machine))).scalars().all():
        want = (names.get(m.area_id) if m.area_id else None) or DEFAULT_CATEGORY
        if m.category != want:
            m.category = want
            changed += 1
    await db.flush()
    return changed


async def apply_area_rules(db: AsyncSession) -> None:
    """Nach Massenaenderungen (CSV-Import): Bereich aus dem Text, Kategorie aus dem Bereich — nur bei aktivem Inventar."""
    if await inventory_enabled(db):
        await sync_machine_areas(db)
        await align_categories(db)
        await db.commit()


async def propagate_area_rename(db: AsyncSession, area_id: int, old: str, new: str) -> None:
    """Umbenennen eines Bereichs: Maschinen (Text und Zuordnung) und bei aktivem Inventar auch die gleichnamige Kategorie."""
    await db.execute(update(Machine)
                     .where(or_(Machine.area_id == area_id, func.lower(Machine.location) == old.lower()))
                     .values(location=new, area_id=area_id))
    if await inventory_enabled(db):
        row = await db.scalar(select(MachineCategory).where(func.lower(MachineCategory.name) == old.lower()))
        taken = await db.scalar(select(MachineCategory.id).where(func.lower(MachineCategory.name) == new.lower()))
        if row is not None and taken is None:
            row.name = new
        await align_categories(db)


async def release_machines_of_area(db: AsyncSession, area: MachineLocation) -> None:
    """Bereich wird geloescht: seine Maschinen haben danach keinen Bereich (Text leer) und die Kategorie «Sonstiges»;
    die gleichnamige Kategorie entfaellt, wenn sie niemand mehr nutzt. Nur bei aktivem Inventar."""
    if not await inventory_enabled(db):
        return
    await db.execute(update(Machine)
                     .where(or_(Machine.area_id == area.id, func.lower(Machine.location) == area.name.lower()))
                     .values(location=None, area_id=None))
    await align_categories(db)
    used = await db.scalar(select(func.count(Machine.id)).where(func.lower(Machine.category) == area.name.lower())) or 0
    if not used:
        row = await db.scalar(select(MachineCategory).where(func.lower(MachineCategory.name) == area.name.lower()))
        if row is not None and row.name.lower() != DEFAULT_CATEGORY.lower():
            await db.delete(row)


# ── Aufloesung & Beschreibung ────────────────────────────────────────────────
async def resolve_position(db: AsyncSession, text: str) -> InvPosition:
    """Loest einen Code (auch verkuerzt) auf die zugehoerige Position auf."""
    area_code, s, e, p = parse_code(text)
    row = (await db.execute(
        select(InvPosition)
        .join(InvLevel, InvLevel.id == InvPosition.level_id)
        .join(InvFurniture, InvFurniture.id == InvLevel.furniture_id)
        .join(MachineLocation, MachineLocation.id == InvFurniture.area_id)
        .where(MachineLocation.code == area_code, InvFurniture.number == s,
               InvLevel.number == e, InvPosition.number == p)
    )).scalar_one_or_none()
    if row:
        return row
    # Verstaendliche Fehlermeldung: welche Stufe fehlt?
    area = await db.scalar(select(MachineLocation).where(MachineLocation.code == area_code))
    if not area:
        raise HTTPException(404, f"Bereich «{area_code}» nicht gefunden")
    furn = await db.scalar(select(InvFurniture).where(
        InvFurniture.area_id == area.id, InvFurniture.number == s))
    if not furn:
        raise HTTPException(404, f"{area_code}-M{s:02d} gibt es nicht")
    lvl = await db.scalar(select(InvLevel).where(
        InvLevel.furniture_id == furn.id, InvLevel.number == e))
    if not lvl:
        raise HTTPException(404, f"{area_code}-M{s:02d}-E{e:02d} gibt es nicht")
    raise HTTPException(404, f"{area_code}-M{s:02d}-E{e:02d}-P{p:02d} gibt es nicht")


async def position_info(db: AsyncSession, position_id: int) -> Optional[dict]:
    """Code und Klartext-Pfad zu einer Position."""
    row = (await db.execute(
        select(MachineLocation, InvFurniture, InvLevel, InvPosition)
        .join(InvFurniture, InvFurniture.area_id == MachineLocation.id)
        .join(InvLevel, InvLevel.furniture_id == InvFurniture.id)
        .join(InvPosition, InvPosition.level_id == InvLevel.id)
        .where(InvPosition.id == position_id)
    )).first()
    return describe(*row) if row else None


KIND_LABEL = {"schrank": "Schrank", "regal": "Regal", "wand": "Werkzeugwand", "tisch": "Tisch"}


def furniture_title(furn: InvFurniture) -> str:
    """Anzeigename: eigener Name, sonst «Regal 1» / «Schrank 2» …"""
    if furn.name:
        return furn.name
    kind = furn.kind.value if hasattr(furn.kind, "value") else str(furn.kind)
    return f"{KIND_LABEL.get(kind, 'Möbel')} {furn.number}"


def describe(area: MachineLocation, furn: InvFurniture, lvl: InvLevel, pos: InvPosition) -> dict:
    code = short_code(area.code, furn.number, lvl.number, pos.number)
    parts = [area.name]
    if furn.number:
        parts.append(furniture_title(furn))
    else:
        parts.append("ohne Möbel")
    if lvl.number:
        parts.append(lvl.label or f"Ebene {lvl.number}")
    if pos.number:
        parts.append(pos.label or f"Platz {pos.number}")
    return {
        "position_id": pos.id,
        "level_id": lvl.id,
        "furniture_id": furn.id,
        "area_id": area.id,
        "code": code,
        "full_code": full_code(area.code, furn.number, lvl.number, pos.number),
        "path": " › ".join(parts),
        "area": area.name,
        "color": area.color,
    }


async def remove_empty_area_structure(db: AsyncSession, area: MachineLocation) -> None:
    """Vor dem Loeschen eines Bereichs: S0 entfernen, aber nur wenn nichts daran haengt."""
    real = await db.scalar(select(func.count(InvFurniture.id)).where(
        InvFurniture.area_id == area.id, InvFurniture.number > 0))
    if real:
        raise HTTPException(409, f"Der Bereich enthält noch {real} Möbel — zuerst im Inventar entfernen")
    items = await db.scalar(
        select(func.count(InvItem.id))
        .join(InvPosition, InvPosition.id == InvItem.position_id)
        .join(InvLevel, InvLevel.id == InvPosition.level_id)
        .join(InvFurniture, InvFurniture.id == InvLevel.furniture_id)
        .where(InvFurniture.area_id == area.id))
    if items:
        raise HTTPException(409, f"Dem Bereich sind noch {items} Werkzeuge zugeordnet")
    zero = (await db.execute(select(InvFurniture).where(
        InvFurniture.area_id == area.id, InvFurniture.number == 0))).scalars().all()
    for f in zero:
        await db.delete(f)
    await db.flush()
