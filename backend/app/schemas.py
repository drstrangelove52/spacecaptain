from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from app.models import UserRole, MachineStatus, PlugType, LogType


# ── Auth ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    user_id: int
    role: UserRole


# ── User / Lab Manager ────────────────────────────────────
class UserBase(BaseModel):
    name: str
    email: str
    role: UserRole = UserRole.manager
    phone: Optional[str] = None
    area: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    area: Optional[str] = None
    role: Optional[UserRole] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None

class UserOut(UserBase):
    id: int
    is_active: bool
    login_token: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Guest ─────────────────────────────────────────────────
class GuestBase(BaseModel):
    name: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    note: Optional[str] = None

class GuestCreate(GuestBase):
    password: str  # Pflichtfeld beim Erstellen

class GuestUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None  # Leer = nicht ändern
    phone: Optional[str] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None

class GuestOut(GuestBase):
    id: int
    is_active: bool
    created_at: datetime
    permission_count: int = 0
    username: str = ""
    login_token: Optional[str] = None


    class Config:
        from_attributes = True


# ── Machine ───────────────────────────────────────────────
class MachineBase(BaseModel):
    name: str
    category: str = "Sonstiges"
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    status: MachineStatus = MachineStatus.online
    plug_type: PlugType = PlugType.none
    plug_ip: Optional[str] = None
    plug_extra: Optional[str] = None
    plug_token: Optional[str] = None
    idle_power_w: Optional[float] = None
    idle_timeout_min: Optional[int] = None
    plug_poll_interval_sec: Optional[int] = 60
    comment: Optional[str] = None

class MachineCreate(MachineBase):
    pass

class MachineUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    status: Optional[MachineStatus] = None
    plug_type: Optional[PlugType] = None
    plug_ip: Optional[str] = None
    plug_extra: Optional[str] = None
    plug_token: Optional[str] = None
    idle_power_w: Optional[float] = None
    idle_timeout_min: Optional[int] = None
    plug_poll_interval_sec: Optional[int] = None
    comment: Optional[str] = None

class MachineOut(MachineBase):
    id: int
    qr_token: str
    created_at: datetime
    user_count: int = 0
    current_guest_id: Optional[int] = None
    session_manager_id: Optional[int] = None
    session_started_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Permissions ───────────────────────────────────────────
class PermissionOut(BaseModel):
    id: int
    guest_id: int
    machine_id: int
    granted_by: Optional[int]
    granted_at: datetime

    class Config:
        from_attributes = True


# ── QR / Plug ─────────────────────────────────────────────
class QRScanRequest(BaseModel):
    guest_token: str   # Gast-Login-Token (aus QR-Code des Gastes oder Session)
    machine_qr: str    # QR-Token der Maschine

class PlugActionRequest(BaseModel):
    machine_id: int
    action: str  # "on" | "off"

class PlugActionResult(BaseModel):
    success: bool
    message: str
    machine_id: int
    action: str


# ── Log ───────────────────────────────────────────────────
class LogOut(BaseModel):
    id: int
    type: LogType
    guest_id: Optional[int]
    machine_id: Optional[int]
    user_id: Optional[int]
    message: str
    meta: Optional[dict]
    created_at: datetime
    guest_name: Optional[str] = None
    machine_name: Optional[str] = None
    user_name: Optional[str] = None

    class Config:
        from_attributes = True


# ── Dashboard ─────────────────────────────────────────────
class DashboardStats(BaseModel):
    total_guests: int
    active_guests: int
    total_machines: int
    online_machines: int
    total_managers: int
    total_permissions: int
