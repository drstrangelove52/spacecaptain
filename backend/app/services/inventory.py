"""
Inventar-Modul: Lagerort-Codes, Nullplaetze (S0/E0/P0) und Code-Aufloesung.

Code-Schema:  <Bereich>-S<Schrank>-E<Ebene>-P<Position>   z.B. EL-S2-E3-P4
Die 0 bedeutet auf jeder Stufe «nicht unterteilt oder noch nicht festgelegt».
Siehe docs/inventar-konzept.md.
"""
import re
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MachineLocation
from app.models_inventory import InvFurniture, InvLevel, InvPosition, InvItem, FurnitureKind

AREA_CODE_RE = re.compile(r"^[A-Z0-9]{2,4}$")
_CODE_RE = re.compile(r"^([A-Z0-9]{2,4})(?:-S(\d+))?(?:-E(\d+))?(?:-P(\d+))?$")


# ── Codes ────────────────────────────────────────────────────────────────────
def normalize_area_code(raw: str) -> str:
    code = (raw or "").strip().upper()
    if not AREA_CODE_RE.match(code):
        raise HTTPException(400, "Kürzel: 2–4 Zeichen, nur Buchstaben und Ziffern (z.B. EL)")
    return code


def full_code(area_code: Optional[str], s: int, e: int, p: int) -> str:
    return f"{area_code or '??'}-S{s}-E{e}-P{p}"


def short_code(area_code: Optional[str], s: int, e: int = 0, p: int = 0) -> str:
    """Code ohne abschliessende Nullen: HO-S1-E2 statt HO-S1-E2-P0."""
    parts = [area_code or "??", f"S{s}"]
    if e or p:
        parts.append(f"E{e}")
    if p:
        parts.append(f"P{p}")
    return "-".join(parts)


def parse_code(text: str) -> tuple[str, int, int, int]:
    """Zerlegt einen Code. Fehlende Stufen werden 0 (z.B. «EL-S2» = EL-S2-E0-P0)."""
    m = _CODE_RE.match((text or "").strip().upper())
    if not m:
        raise HTTPException(400, f"Ungültiger Code: {text!r} (Beispiel: EL-S2-E3-P4)")
    area, s, e, p = m.groups()
    return area, int(s or 0), int(e or 0), int(p or 0)


# ── Nullplaetze ──────────────────────────────────────────────────────────────
async def ensure_structure(db: AsyncSession) -> int:
    """Legt fehlende Nullplaetze an: S0 je Bereich, E0 je Moebel, P0 je Ebene.
    Idempotent, gibt die Anzahl neu angelegter Zeilen zurueck."""
    created = 0

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
    await db.commit()
    return created


async def ensure_structure_if_needed(db: AsyncSession) -> None:
    """Guenstiger Vorab-Check (2 Zaehlabfragen) — nur bei Luecken wird nachgezogen.
    Noetig, weil Standorte auch ueber CSV-Import oder Backup-Restore entstehen."""
    areas = await db.scalar(select(func.count(MachineLocation.id))) or 0
    zero = await db.scalar(select(func.count(InvFurniture.id)).where(InvFurniture.number == 0)) or 0
    if zero < areas:
        await ensure_structure(db)


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
    f = InvFurniture(area_id=area.id, number=number, kind=kind, name=(name or None), note=note)
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
        raise HTTPException(404, f"{area_code}-S{s} gibt es nicht")
    lvl = await db.scalar(select(InvLevel).where(
        InvLevel.furniture_id == furn.id, InvLevel.number == e))
    if not lvl:
        raise HTTPException(404, f"{area_code}-S{s}-E{e} gibt es nicht")
    raise HTTPException(404, f"{area_code}-S{s}-E{e}-P{p} gibt es nicht")


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
