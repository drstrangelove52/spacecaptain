from datetime import datetime
from typing import Optional
from sqlalchemy import (Integer, String, Boolean, DateTime, Text, JSON,
                        Enum, ForeignKey, UniqueConstraint, Float)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"

class MachineStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"

class PlugType(str, enum.Enum):
    mystrom = "mystrom"
    shelly = "shelly"
    none = "none"

class LogType(str, enum.Enum):
    access_granted = "access_granted"
    access_denied = "access_denied"
    plug_on = "plug_on"
    plug_off = "plug_off"
    guest_created = "guest_created"
    guest_deleted = "guest_deleted"
    machine_created = "machine_created"
    machine_deleted = "machine_deleted"
    permission_granted = "permission_granted"
    permission_revoked = "permission_revoked"
    login = "login"
    guest_login = "guest_login"
    error = "error"
    idle_off = "idle_off"
    session_started = "session_started"
    maintenance_due = "maintenance_due"
    maintenance_done = "maintenance_done"

class SessionEndedBy(str, enum.Enum):
    guest = "guest"
    manager = "manager"
    idle_timeout = "idle_timeout"
    system = "system"


class User(Base):
    __tablename__ = "users"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]           = mapped_column(String(100), nullable=False)
    email:         Mapped[str]           = mapped_column(String(150), nullable=False, unique=True)
    password_hash: Mapped[str]           = mapped_column(String(255), nullable=False)
    role:          Mapped[UserRole]      = mapped_column(Enum(UserRole), default=UserRole.manager)
    phone:         Mapped[Optional[str]] = mapped_column(String(50))
    area:          Mapped[Optional[str]] = mapped_column(String(200))
    is_active:     Mapped[bool]          = mapped_column(Boolean, default=True)
    login_token:   Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Guest(Base):
    __tablename__ = "guests"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]           = mapped_column(String(100), nullable=False)
    username:      Mapped[str]           = mapped_column(String(80), unique=True, nullable=False)
    email:         Mapped[Optional[str]] = mapped_column(String(150), unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    phone:         Mapped[Optional[str]] = mapped_column(String(50))
    note:          Mapped[Optional[str]] = mapped_column(Text)
    is_active:     Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    login_token:   Mapped[Optional[str]]       = mapped_column(String(64), unique=True, nullable=True)
    permissions:   Mapped[list["Permission"]] = relationship("Permission", back_populates="guest", cascade="all, delete-orphan")
    tokens:        Mapped[list["GuestToken"]] = relationship("GuestToken", back_populates="guest", cascade="all, delete-orphan")


class GuestToken(Base):
    __tablename__ = "guest_tokens"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id:   Mapped[int]      = mapped_column(Integer, ForeignKey("guests.id", ondelete="CASCADE"))
    token:      Mapped[str]      = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    guest:      Mapped["Guest"]  = relationship("Guest", back_populates="tokens")


class Machine(Base):
    __tablename__ = "machines"
    id:                 Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:               Mapped[str]             = mapped_column(String(100), nullable=False)
    category:           Mapped[str]             = mapped_column(String(50), default="Sonstiges")
    manufacturer:       Mapped[Optional[str]]   = mapped_column(String(100))
    model:              Mapped[Optional[str]]   = mapped_column(String(100))
    location:           Mapped[Optional[str]]   = mapped_column(String(200))
    status:             Mapped[MachineStatus]   = mapped_column(Enum(MachineStatus), default=MachineStatus.online)
    plug_type:          Mapped[PlugType]        = mapped_column(Enum(PlugType), default=PlugType.none)
    plug_ip:            Mapped[Optional[str]]   = mapped_column(String(50))
    plug_extra:         Mapped[Optional[str]]   = mapped_column(String(255))
    plug_token:         Mapped[Optional[str]]   = mapped_column(String(255))
    idle_power_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    idle_timeout_min:   Mapped[Optional[int]]   = mapped_column(Integer, default=None)
    plug_poll_interval_sec: Mapped[Optional[int]] = mapped_column(Integer, default=60)
    current_guest_id:   Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("guests.id", ondelete="SET NULL"), default=None)
    session_manager_id: Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None)
    session_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    total_hours:        Mapped[float]            = mapped_column(Float, default=0.0)
    comment:            Mapped[Optional[str]]   = mapped_column(Text)
    qr_token:           Mapped[str]             = mapped_column(String(64), unique=True, nullable=False)
    created_at:         Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:         Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    permissions:        Mapped[list["Permission"]] = relationship("Permission", back_populates="machine", cascade="all, delete-orphan")
    current_guest:      Mapped[Optional["Guest"]]  = relationship("Guest", foreign_keys=[current_guest_id])


class MachineSession(Base):
    __tablename__ = "machine_sessions"
    id:           Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:   Mapped[int]             = mapped_column(Integer, ForeignKey("machines.id", ondelete="CASCADE"))
    guest_id:     Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("guests.id", ondelete="SET NULL"))
    started_at:   Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    ended_at:     Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    duration_min: Mapped[Optional[float]] = mapped_column(Float, default=None)
    energy_wh:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    ended_by:     Mapped[Optional[SessionEndedBy]] = mapped_column(Enum(SessionEndedBy), default=None)
    machine:      Mapped["Machine"]       = relationship("Machine")
    guest:        Mapped[Optional["Guest"]] = relationship("Guest")


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("guest_id", "machine_id"),)
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("guests.id", ondelete="CASCADE"))
    machine_id: Mapped[int]           = mapped_column(Integer, ForeignKey("machines.id", ondelete="CASCADE"))
    granted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    guest:      Mapped["Guest"]       = relationship("Guest", back_populates="permissions")
    machine:    Mapped["Machine"]     = relationship("Machine", back_populates="permissions")


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    type:       Mapped[LogType]       = mapped_column(Enum(LogType), nullable=False)
    guest_id:   Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("guests.id", ondelete="SET NULL"))
    machine_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("machines.id", ondelete="SET NULL"))
    user_id:    Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    message:    Mapped[str]           = mapped_column(Text, nullable=False)
    meta:       Mapped[Optional[dict]]= mapped_column(JSON)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


class MaintenanceInterval(Base):
    __tablename__ = "maintenance_intervals"
    id:               Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:       Mapped[int]             = mapped_column(Integer, ForeignKey("machines.id", ondelete="CASCADE"))
    name:             Mapped[str]             = mapped_column(String(200), nullable=False)
    description:      Mapped[Optional[str]]   = mapped_column(Text)
    interval_hours:   Mapped[Optional[float]] = mapped_column(Float, default=None)   # nach X Betriebsstunden
    interval_days:    Mapped[Optional[int]]   = mapped_column(Integer, default=None)  # nach X Tagen
    warning_hours:    Mapped[Optional[float]] = mapped_column(Float, default=None)   # Warnung X h vorher
    warning_days:     Mapped[Optional[int]]   = mapped_column(Integer, default=None)  # Warnung X Tage vorher
    is_active:        Mapped[bool]            = mapped_column(Boolean, default=True)
    created_at:       Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    machine:          Mapped["Machine"]       = relationship("Machine")
    records:          Mapped[list["MaintenanceRecord"]] = relationship(
                          "MaintenanceRecord", back_populates="interval",
                          cascade="all, delete-orphan", order_by="MaintenanceRecord.performed_at.desc()"
                      )


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    id:                   Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    interval_id:          Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("maintenance_intervals.id", ondelete="SET NULL"), nullable=True)
    name:                 Mapped[Optional[str]]   = mapped_column(String(200), nullable=True)
    machine_id:           Mapped[int]             = mapped_column(Integer, ForeignKey("machines.id", ondelete="CASCADE"))
    performed_by:         Mapped[int]             = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    performed_at:         Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    hours_at_execution:   Mapped[Optional[float]] = mapped_column(Float, default=None)
    notes:                Mapped[Optional[str]]   = mapped_column(Text)
    created_at:           Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    interval:             Mapped[Optional["MaintenanceInterval"]] = relationship("MaintenanceInterval", back_populates="records")
    machine:              Mapped["Machine"]            = relationship("Machine")
    performer:            Mapped[Optional["User"]]     = relationship("User")
