"""
Inventar-Modul (Lagerorte & Werkzeug) — siehe docs/inventar-konzept.md.

Alle IDs sind unsigned. Die Tabellen entstehen ueber
Base.metadata.create_all() beim Start; das Modul muss dafuer vor dem Start importiert sein
(siehe main.py).
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (Integer, String, Boolean, DateTime, Text, Enum, ForeignKey,
                        UniqueConstraint, Float)
from sqlalchemy.dialects.mysql import INTEGER as UINT
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
    plan_x:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_y:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_h:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    plan_rot:     Mapped[Optional[float]] = mapped_column(Float, default=None)
