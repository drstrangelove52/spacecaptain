"""
Inventar-Modul (Lagerorte & Werkzeug) — siehe docs/inventar-konzept.md.

Alle IDs sind unsigned. Die Tabellen entstehen ueber
Base.metadata.create_all() beim Start; das Modul muss dafuer vor dem Start importiert sein
(siehe main.py).
"""
import enum
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (Integer, String, Boolean, DateTime, Text, Enum, ForeignKey,
                        UniqueConstraint, Float, Date, LargeBinary)
from sqlalchemy.dialects.mysql import INTEGER as UINT, LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FurnitureKind(str, enum.Enum):
    bereich = "bereich"   # nur fuer S0 («im Bereich, in keinem Moebel»)
    schrank = "schrank"
    regal = "regal"
    wand = "wand"
    tisch = "tisch"       # gilt auch fuer Werkbaenke


class InvItemStatus(str, enum.Enum):
    aktiv = "aktiv"
    defekt = "defekt"
    ausgemustert = "ausgemustert"


class InvFurniture(Base):
    __tablename__ = "inv_furniture"
    __table_args__ = (UniqueConstraint("area_id", "number", name="uq_inv_furniture_area_number"),)
    id:        Mapped[int]             = mapped_column(UINT(unsigned=True), primary_key=True, autoincrement=True)
    # Bewusst OHNE DB-Fremdschluessel: machine_locations.id ist je nach Installation signed
    # (vom ORM angelegt) oder unsigned (init.sql) — ein FK wuerde beim Start mit errno 150
    # scheitern. Die Integritaet sichert die Anwendung (services/inventory.remove_empty_area_structure).
    area_id:   Mapped[int]             = mapped_column(UINT(unsigned=True), nullable=False, index=True)
    number:    Mapped[int]             = mapped_column(Integer, nullable=False)   # 0 = «kein Moebel» (S0)
    kind:      Mapped[FurnitureKind]   = mapped_column(Enum(FurnitureKind), default=FurnitureKind.schrank)
    name:      Mapped[Optional[str]]   = mapped_column(String(100), default=None)
    plan_x:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_y:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_w:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_h:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_rot:  Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_floor_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)     # Stockwerk auf dem Plan (ohne DB-FK)
    label_outdated: Mapped[bool]       = mapped_column(Boolean, default=False)
    note:      Mapped[Optional[str]]   = mapped_column(Text, default=None)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)
    levels:    Mapped[list["InvLevel"]]  = relationship("InvLevel", back_populates="furniture",
                                                        cascade="all, delete-orphan",
                                                        order_by="InvLevel.number")


class InvLevel(Base):
    __tablename__ = "inv_levels"
    __table_args__ = (UniqueConstraint("furniture_id", "number", name="uq_inv_levels_furniture_number"),)
    id:           Mapped[int]            = mapped_column(UINT(unsigned=True), primary_key=True, autoincrement=True)
    furniture_id: Mapped[int]            = mapped_column(UINT(unsigned=True), ForeignKey("inv_furniture.id", ondelete="CASCADE"))
    number:       Mapped[int]            = mapped_column(Integer, nullable=False)   # 0 = Ebene unbestimmt (E0)
    label:        Mapped[Optional[str]]  = mapped_column(String(100), default=None)
    furniture:    Mapped["InvFurniture"] = relationship("InvFurniture", back_populates="levels")
    positions:    Mapped[list["InvPosition"]] = relationship("InvPosition", back_populates="level",
                                                             cascade="all, delete-orphan",
                                                             order_by="InvPosition.number")


class InvPosition(Base):
    __tablename__ = "inv_positions"
    __table_args__ = (UniqueConstraint("level_id", "number", name="uq_inv_positions_level_number"),)
    id:       Mapped[int]            = mapped_column(UINT(unsigned=True), primary_key=True, autoincrement=True)
    level_id: Mapped[int]            = mapped_column(UINT(unsigned=True), ForeignKey("inv_levels.id", ondelete="CASCADE"))
    number:   Mapped[int]            = mapped_column(Integer, nullable=False)   # 0 = keine feste Position (P0)
    label:    Mapped[Optional[str]]  = mapped_column(String(100), default=None)
    level:    Mapped["InvLevel"]     = relationship("InvLevel", back_populates="positions")


class InvItem(Base):
    """Werkzeug / Kleingeraet mit genau einem Heimatplatz."""
    __tablename__ = "inv_items"
    id:          Mapped[int]           = mapped_column(UINT(unsigned=True), primary_key=True, autoincrement=True)
    name:        Mapped[str]           = mapped_column(String(150), nullable=False)
    synonyms:    Mapped[Optional[str]] = mapped_column(Text, default=None)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    quantity:    Mapped[int]           = mapped_column(Integer, default=1)
    position_id: Mapped[Optional[int]] = mapped_column(UINT(unsigned=True), ForeignKey("inv_positions.id", ondelete="SET NULL"), default=None)
    status:      Mapped[InvItemStatus] = mapped_column(Enum(InvItemStatus), default=InvItemStatus.aktiv)
    # Optionale Buchhaltungs-/Versicherungsfelder wie bei Maschinen (Neuwert je Stueck). owner_id ohne DB-FK (Typ je Installation)
    serial_number: Mapped[Optional[str]]   = mapped_column(String(100), default=None)
    purchase_date: Mapped[Optional[date]]  = mapped_column(Date, default=None)
    value_new:     Mapped[Optional[float]] = mapped_column(Float, default=None)
    owner_id:      Mapped[Optional[int]]   = mapped_column(Integer, default=None)
    created_at:  Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:  Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    position:    Mapped[Optional["InvPosition"]] = relationship("InvPosition")


class InvPlacement(Base):
    """Maschine im Raum: optional «steht auf» einem Moebel, spaeter Platz im Bauplan (Etappe 4).
    Keine DB-Fremdschluessel auf machines (Typ je Installation signed/unsigned); beim Loeschen einer Maschine
    raeumt der machines-Router auf, verwaiste Zeilen werden ignoriert."""
    __tablename__ = "inv_placements"
    machine_id:   Mapped[int]             = mapped_column(UINT(unsigned=True), primary_key=True, autoincrement=False)
    furniture_id: Mapped[Optional[int]]   = mapped_column(UINT(unsigned=True), ForeignKey("inv_furniture.id", ondelete="SET NULL"), default=None)
    # optional: auf welcher Ebene des Moebels (z.B. Regal 1 › Ebene 3); nur mit furniture_id gueltig
    level_id:     Mapped[Optional[int]]   = mapped_column(UINT(unsigned=True), ForeignKey("inv_levels.id", ondelete="SET NULL"), default=None)
    plan_x:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_y:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_h:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_rot:     Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_floor_id: Mapped[Optional[int]]  = mapped_column(Integer, default=None)


class InvPlan(Base):
    """Der Raum des Bauplans (eine Zeile, id=1): Name und Grundflaeche in cm."""
    __tablename__ = "inv_plan"
    id:        Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=False)
    name:      Mapped[str]   = mapped_column(String(100), default="Makerspace")
    width_cm:  Mapped[float] = mapped_column(Float, default=1500.0)
    height_cm: Mapped[float] = mapped_column(Float, default=1000.0)
    wall_cm:   Mapped[float] = mapped_column(Float, default=0.0)          # Standard-Wanddicke (0 = nur Umriss), aussen um die Raum-Innenflaeche


class InvFloor(Base):
    """Stockwerk des Bauplans (z.B. «EG», «OG»). Mindestens eines; das erste entsteht automatisch."""
    __tablename__ = "inv_floors"
    id:         Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Hintergrund-Grundriss zum Abpausen (Bild in inv_floor_images): Lage und Groesse in cm, Deckkraft 0..1
    bg_x:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    bg_y:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    bg_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    bg_h:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    bg_opacity: Mapped[float]           = mapped_column(Float, default=0.5)
    bg_rot:     Mapped[float]           = mapped_column(Float, default=0.0)      # Drehung des Bildes in Grad um seine Mitte
    # Sichtbarer Ausschnitt des Bildes als Anteile (0..1) der Bildkanten, die weggeschnitten werden (z.B. Bemassung am Rand)
    bg_crop_l:  Mapped[float]           = mapped_column(Float, default=0.0)
    bg_crop_t:  Mapped[float]           = mapped_column(Float, default=0.0)
    bg_crop_r:  Mapped[float]           = mapped_column(Float, default=0.0)
    bg_crop_b:  Mapped[float]           = mapped_column(Float, default=0.0)
    bg_version: Mapped[int]             = mapped_column(Integer, default=0)      # 0 = kein Bild; steigt bei jedem Hochladen (Cache)


class InvRoom(Base):
    """Raum, Treppe, Tuer oder Durchgang auf einem Stockwerk (cm): Rechteck, Raeume optional als Vieleck (`points`). Eine Treppe zeigt sich zusaetzlich auf `link_floor_id`.
    Keine DB-Fremdschluessel (Integritaet im App-Code)."""
    __tablename__ = "inv_rooms"
    id:            Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    floor_id:      Mapped[int]             = mapped_column(Integer, nullable=False, index=True)
    name:          Mapped[str]             = mapped_column(String(100), nullable=False)
    kind:          Mapped[str]             = mapped_column(String(10), default="raum")      # raum | treppe
    plan_x:        Mapped[float]           = mapped_column(Float, default=0.0)
    plan_y:        Mapped[float]           = mapped_column(Float, default=0.0)
    plan_w:        Mapped[float]           = mapped_column(Float, default=300.0)
    plan_h:        Mapped[float]           = mapped_column(Float, default=300.0)
    plan_rot:      Mapped[float]           = mapped_column(Float, default=0.0)
    link_floor_id: Mapped[Optional[int]]   = mapped_column(Integer, default=None)
    # Eckpunkte eines Raums als JSON [[x, y], …] in cm; leer = Rechteck. plan_x/y/w/h bleiben die Umgebung (bbox) der Punkte.
    points:        Mapped[Optional[str]]   = mapped_column(Text, default=None)
    # Spiegelung (Tueren): Bit 1 = Anschlag links/rechts, Bit 2 = Aufschlag auf die andere Wandseite
    flip:          Mapped[int]             = mapped_column(Integer, default=0)
    wall_cm:       Mapped[Optional[float]] = mapped_column(Float, default=None)     # eigene Wanddicke dieses Raums; leer = Standard des Gebaeudes


class InvFloorImage(Base):
    """Das hochgeladene Grundriss-Bild eines Stockwerks (JPEG, max. ~2400 px, in der DB gespeichert)."""
    __tablename__ = "inv_floor_images"
    floor_id:     Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=False)
    data:         Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False)
    content_type: Mapped[str]   = mapped_column(String(30), default="image/jpeg")
