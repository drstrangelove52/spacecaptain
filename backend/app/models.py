from datetime import datetime, date, time
from typing import Optional
from sqlalchemy import (Integer, String, Boolean, DateTime, Time, Text, JSON,
                        Enum, ForeignKey, UniqueConstraint, Float, Date, Time)
from sqlalchemy.dialects.mysql import INTEGER as UINT
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    power_manager = "power_manager"
    manager = "manager"

class MachineStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"

class PlugType(str, enum.Enum):
    mystrom = "mystrom"
    shelly = "shelly"
    shelly_gen2 = "shelly_gen2"
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
    guest_registered = "guest_registered"
    guest_approved = "guest_approved"
    emergency_triggered = "emergency_triggered"
    emergency_cancelled = "emergency_cancelled"
    settings_changed = "settings_changed"
    announcement_created = "announcement_created"
    announcement_updated = "announcement_updated"
    announcement_deleted = "announcement_deleted"
    ntfy_topic_created = "ntfy_topic_created"
    ntfy_topic_updated = "ntfy_topic_updated"
    ntfy_topic_deleted = "ntfy_topic_deleted"
    queue_joined = "queue_joined"
    queue_left = "queue_left"
    queue_notified = "queue_notified"
    backup_exported = "backup_exported"
    backup_imported = "backup_imported"
    user_created = "user_created"
    user_updated = "user_updated"
    guest_updated = "guest_updated"
    machine_updated = "machine_updated"
    automation_created = "automation_created"
    automation_updated = "automation_updated"
    automation_deleted = "automation_deleted"
    schedule_created = "schedule_created"
    schedule_updated = "schedule_updated"
    schedule_deleted = "schedule_deleted"
    schedule_on = "schedule_on"
    schedule_off = "schedule_off"
    room_opened         = "room_opened"
    room_closed         = "room_closed"
    room_access_denied  = "room_access_denied"
    rule_created = "rule_created"
    rule_updated = "rule_updated"
    rule_deleted = "rule_deleted"
    rule_on      = "rule_on"
    rule_off     = "rule_off"
    system       = "system"

class SessionEndedBy(str, enum.Enum):
    guest = "guest"
    manager = "manager"
    idle_timeout = "idle_timeout"
    system = "system"

class QueueStatus(str, enum.Enum):
    waiting = "waiting"
    notified = "notified"
    done = "done"
    expired = "expired"


class User(Base):
    __tablename__ = "users"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
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
    name:          Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    username:      Mapped[str]           = mapped_column(String(80), unique=True, nullable=False)
    email:         Mapped[Optional[str]] = mapped_column(String(150), unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    phone:         Mapped[Optional[str]] = mapped_column(String(50))
    note:          Mapped[Optional[str]] = mapped_column(Text)
    is_active:        Mapped[bool]          = mapped_column(Boolean, default=True)
    pending_approval: Mapped[bool]          = mapped_column(Boolean, default=False)
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    login_token:   Mapped[Optional[str]]       = mapped_column(String(64), unique=True, nullable=True)
    ntfy_topic:    Mapped[Optional[str]]       = mapped_column(String(80), unique=True, nullable=True)
    permissions:   Mapped[list["Permission"]] = relationship("Permission", back_populates="guest", cascade="all, delete-orphan")


class Machine(Base):
    __tablename__ = "machines"
    id:                 Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:               Mapped[str]             = mapped_column(String(100), unique=True, nullable=False)
    category:           Mapped[str]             = mapped_column(String(50), default="Sonstiges")
    manufacturer:       Mapped[Optional[str]]   = mapped_column(String(100))
    model:              Mapped[Optional[str]]   = mapped_column(String(100))
    serial_number:      Mapped[Optional[str]]   = mapped_column(String(100))
    location:           Mapped[Optional[str]]   = mapped_column(String(200))
    status:             Mapped[MachineStatus]   = mapped_column(Enum(MachineStatus), default=MachineStatus.online)
    plug_type:          Mapped[PlugType]        = mapped_column(Enum(PlugType), default=PlugType.none)
    plug_ip:            Mapped[Optional[str]]   = mapped_column(String(50))
    plug_extra:         Mapped[Optional[str]]   = mapped_column(String(255))
    plug_token:         Mapped[Optional[str]]   = mapped_column(String(255))
    idle_power_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    idle_timeout_min:   Mapped[Optional[int]]   = mapped_column(Integer, default=None)
    plug_poll_interval_sec: Mapped[Optional[int]] = mapped_column(Integer, default=60)
    training_required:      Mapped[bool]           = mapped_column(Boolean, default=True)
    current_guest_id:   Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("guests.id", ondelete="SET NULL"), default=None)
    session_manager_id: Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None)
    session_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    total_hours:        Mapped[float]            = mapped_column(Float, default=0.0)
    comment:            Mapped[Optional[str]]   = mapped_column(Text)
    safety_notes:       Mapped[Optional[str]]   = mapped_column(Text, default=None)
    force_off_on_close: Mapped[bool]            = mapped_column(Boolean, default=False)
    plug_id:            Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("plugs.id", ondelete="SET NULL"), default=None)
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
    manager_id:   Mapped[Optional[int]]   = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None)
    started_at:   Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)
    ended_at:     Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    duration_min: Mapped[Optional[float]] = mapped_column(Float, default=None)
    energy_wh:    Mapped[Optional[float]] = mapped_column(Float, default=None)
    ended_by:     Mapped[Optional[SessionEndedBy]] = mapped_column(Enum(SessionEndedBy), default=None)
    session_source: Mapped[Optional[str]] = mapped_column(String(50), default=None)
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
    is_blocked: Mapped[bool]          = mapped_column(Boolean, default=False)
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


class SystemSettings(Base):
    __tablename__ = "system_settings"
    id:                       Mapped[int]  = mapped_column(Integer, primary_key=True, default=1)
    nfc_writer_url:           Mapped[str]  = mapped_column(String(255), default="")
    jwt_expire_minutes:       Mapped[int]  = mapped_column(Integer, default=480)
    modal_backdrop_input:     Mapped[bool] = mapped_column(Boolean, default=True)
    modal_backdrop_display:   Mapped[bool] = mapped_column(Boolean, default=True)
    queue_reservation_minutes:  Mapped[int] = mapped_column(Integer, default=5)
    display_refresh_seconds:    Mapped[int] = mapped_column(Integer, default=30)
    display_page_size:          Mapped[int] = mapped_column(Integer, default=8)
    dashboard_refresh_seconds:  Mapped[int] = mapped_column(Integer, default=30)
    ticker_text:                Mapped[Optional[str]] = mapped_column(Text, default=None)
    ticker_speed:               Mapped[int] = mapped_column(Integer, default=80)
    ticker_font_size:           Mapped[int] = mapped_column(Integer, default=18)
    announcement:               Mapped[Optional[str]] = mapped_column(Text, default=None)
    announcement_font_size:     Mapped[int] = mapped_column(Integer, default=20)
    agb_text:                   Mapped[Optional[str]] = mapped_column(Text, default=None)
    ntfy_server:                Mapped[str]  = mapped_column(String(255), default="https://ntfy.sh")
    ntfy_token:                 Mapped[Optional[str]] = mapped_column(String(255), default=None)
    emergency_trigger_token:    Mapped[Optional[str]] = mapped_column(String(100), default=None)
    emergency_text:             Mapped[Optional[str]] = mapped_column(Text, default=None)
    emergency_ntfy_message:     Mapped[Optional[str]] = mapped_column(Text, default=None)
    emergency_duration_sec:     Mapped[int]  = mapped_column(Integer, default=0)
    emergency_ntfy_topic_id:    Mapped[Optional[int]] = mapped_column(Integer, default=None)
    emergency_plug_id:          Mapped[Optional[int]] = mapped_column(Integer, default=None)
    emergency_plug2_id:         Mapped[Optional[int]] = mapped_column(Integer, default=None)
    auto_backup_enabled:        Mapped[bool]          = mapped_column(Boolean, default=False)
    auto_backup_hour:           Mapped[int]            = mapped_column(Integer, default=3)
    auto_backup_minute:         Mapped[int]            = mapped_column(Integer, default=0)
    auto_backup_keep:           Mapped[int]            = mapped_column(Integer, default=30)
    space_name:                 Mapped[str]            = mapped_column(String(100), default="")
    room_open:                  Mapped[bool]           = mapped_column(Boolean, default=False)
    room_open_since:            Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    room_open_auto:             Mapped[bool]           = mapped_column(Boolean, default=True)
    guest_token_ttl_hours:      Mapped[int]            = mapped_column(Integer, default=8)
    ts_enabled:                 Mapped[bool]           = mapped_column(Boolean, default=False)
    ts_authkey:                 Mapped[Optional[str]]  = mapped_column(String(255), default=None)
    ts_hostname:                Mapped[str]            = mapped_column(String(100), default="spacecaptain")


class DeviceSchedule(Base):
    __tablename__ = "device_schedules"
    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:       Mapped[int]            = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"))
    name:             Mapped[str]            = mapped_column(String(100), default="")
    days:             Mapped[str]            = mapped_column(String(20), nullable=False)   # "1,2,3,4,5"
    time_on:          Mapped[time]           = mapped_column(Time, nullable=False)
    time_off:         Mapped[time]           = mapped_column(Time, nullable=False)
    require_room_open: Mapped[bool]          = mapped_column(Boolean, default=True)
    enabled:          Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:       Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)
    machine:          Mapped["Machine"]      = relationship("Machine")


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:              Mapped[str]           = mapped_column(String(100), default="")
    action_type:       Mapped[str]           = mapped_column(String(20), default="machine")  # machine | room_open | room_close | notify
    target_machine_id: Mapped[Optional[int]] = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=True, default=None)
    off_delay_sec:     Mapped[int]           = mapped_column(Integer, default=0)
    enabled:           Mapped[bool]          = mapped_column(Boolean, default=True)
    notify_topic_id:   Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("ntfy_topics.id", ondelete="SET NULL"), nullable=True, default=None)
    notify_message:    Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at:        Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    target_machine: Mapped[Optional["Machine"]]  = relationship("Machine", foreign_keys=[target_machine_id])
    conditions:     Mapped[list["RuleCondition"]] = relationship("RuleCondition", back_populates="rule", cascade="all, delete-orphan")


class RuleCondition(Base):
    """Eine Bedingung innerhalb einer AutomationRule (AND-Verknüpfung).

    Typen:
      power          – source_machine_id, power_on_w, power_off_w
      schedule       – days ("1,2,3"), time_on, time_off
      room_open      – (keine zusätzlichen Felder)
      session_active – (keine zusätzlichen Felder)
    """
    __tablename__ = "rule_conditions"
    id:                Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id:           Mapped[int]            = mapped_column(Integer, ForeignKey("automation_rules.id", ondelete="CASCADE"))
    type:              Mapped[str]            = mapped_column(String(30), nullable=False)
    # power
    source_machine_id: Mapped[Optional[int]]  = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="SET NULL"), default=None)
    power_on_w:        Mapped[Optional[float]] = mapped_column(Float, default=None)
    power_off_w:       Mapped[Optional[float]] = mapped_column(Float, default=None)
    # schedule
    days:              Mapped[Optional[str]]  = mapped_column(String(20), default=None)
    time_on:           Mapped[Optional[time]] = mapped_column(Time, default=None)
    time_off:          Mapped[Optional[time]] = mapped_column(Time, default=None)
    # (room_open und session_active brauchen keine zusätzlichen Felder)
    rule:           Mapped["AutomationRule"] = relationship("AutomationRule", back_populates="conditions")
    source_machine: Mapped[Optional["Machine"]] = relationship("Machine", foreign_keys=[source_machine_id])


class NtfyTopic(Base):
    __tablename__ = "ntfy_topics"
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:         Mapped[Optional[str]]  = mapped_column(String(50), unique=True, nullable=True, default=None)
    topic:       Mapped[str]           = mapped_column(String(200), nullable=False)
    title:       Mapped[str]           = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:  Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


class EmergencyState(Base):
    __tablename__ = "emergency_state"
    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, default=1)
    active:       Mapped[bool]          = mapped_column(Boolean, default=False)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class MachineCategory(Base):
    __tablename__ = "machine_categories"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str]           = mapped_column(String(50), unique=True, nullable=False)
    icon:       Mapped[str]           = mapped_column(String(10), default="🔧")
    sort_order: Mapped[int]           = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


class MachineLocation(Base):
    __tablename__ = "machine_locations"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    sort_order: Mapped[int]           = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


class Plug(Base):
    __tablename__ = "plugs"
    id:                     Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:                   Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    plug_type:              Mapped[str]           = mapped_column(String(20), nullable=False)
    plug_ip:                Mapped[str]           = mapped_column(String(50), nullable=False)
    plug_token:             Mapped[Optional[str]] = mapped_column(String(255), default=None)
    notes:                  Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at:             Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


class MachinePlug(Base):
    """Junction-Tabelle: Maschine ↔ Plug (many-to-many).
    sort_order=0 = Primär-Plug (wird für Monitoring/machine-Felder genutzt)."""
    __tablename__ = "machine_plugs"
    __table_args__ = (UniqueConstraint("machine_id", "plug_id"),)
    id:         Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"))
    plug_id:    Mapped[int] = mapped_column(Integer, ForeignKey("plugs.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class MachineAutomation(Base):
    """Schaltet Ziel-Maschine automatisch basierend auf Leistungsaufnahme der Quell-Maschine."""
    __tablename__ = "machine_automations"
    id:                Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_machine_id: Mapped[int]   = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"))
    target_machine_id: Mapped[int]   = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"))
    on_threshold_w:    Mapped[float] = mapped_column(Float, nullable=False)
    off_threshold_w:   Mapped[float] = mapped_column(Float, nullable=False)
    off_delay_sec:     Mapped[int]   = mapped_column(Integer, default=30)
    enabled:           Mapped[bool]  = mapped_column(Boolean, default=True)
    created_at:        Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source_machine:    Mapped["Machine"] = relationship("Machine", foreign_keys=[source_machine_id])
    target_machine:    Mapped["Machine"] = relationship("Machine", foreign_keys=[target_machine_id])


class MachineQueue(Base):
    __tablename__ = "machine_queue"
    id:          Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id:  Mapped[int]          = mapped_column(UINT(unsigned=True), ForeignKey("machines.id", ondelete="CASCADE"))
    guest_id:    Mapped[int]          = mapped_column(UINT(unsigned=True), ForeignKey("guests.id", ondelete="CASCADE"))
    status:      Mapped[QueueStatus]  = mapped_column(Enum(QueueStatus), default=QueueStatus.waiting)
    joined_at:   Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    expires_at:  Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    machine:     Mapped["Machine"]    = relationship("Machine")
    guest:       Mapped["Guest"]      = relationship("Guest")



class Announcement(Base):
    __tablename__ = "announcements"
    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    text:               Mapped[str]            = mapped_column(Text, nullable=False)
    is_active:          Mapped[bool]           = mapped_column(Boolean, default=True)
    is_recurring:       Mapped[bool]           = mapped_column(Boolean, default=False)
    # einmalig
    start_at:           Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_at:             Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # wiederkehrend
    recur_days:         Mapped[Optional[str]]  = mapped_column(String(20), nullable=True)   # "0,1,2,3,4"
    recur_start_time:   Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    recur_end_time:     Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    recur_valid_from:   Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    recur_valid_until:  Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    display_type:       Mapped[str]            = mapped_column(String(20), default="banner")  # "banner" | "ticker"
    created_at:         Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)


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
