from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- Auth ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str
    password: str
    email: str = ""
    role: Literal["admin", "staff"] = "staff"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    role: str
    active: bool


# ---------- Asset ----------
class PackageBase(BaseModel):
    name: str
    duration_minutes: int
    price: float = 0.0
    guided: bool = False
    description: str = ""
    active: bool = True


class PackageCreate(PackageBase):
    asset_id: int


class PackageOut(PackageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_id: int


class AssetBase(BaseModel):
    name: str
    asset_type: Literal["boat", "jetski", "car", "van"]
    capacity: int = 1
    description: str = ""
    price_hour: float = 0.0
    price_half_day: float = 0.0
    price_full_day: float = 0.0
    deposit: float = 0.0
    deposit_percent: float = 0.0
    requires_license: bool = False
    show_license_to_customer: bool = True
    fuel_policy: str = "full-to-full"
    location: str = ""
    calendar_id: str = ""
    active: bool = True


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None
    price_hour: Optional[float] = None
    price_half_day: Optional[float] = None
    price_full_day: Optional[float] = None
    deposit: Optional[float] = None
    deposit_percent: Optional[float] = None
    requires_license: Optional[bool] = None
    show_license_to_customer: Optional[bool] = None
    fuel_policy: Optional[str] = None
    location: Optional[str] = None
    calendar_id: Optional[str] = None
    active: Optional[bool] = None


class AssetOut(AssetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    packages: List[PackageOut] = Field(default_factory=list)


# ---------- Customer ----------
class CustomerBase(BaseModel):
    full_name: str
    phone: str = ""
    email: str = ""
    country: str = ""
    language: str = "en"
    notes: str = ""


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    notes: Optional[str] = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- Booking ----------
class BookingCreate(BaseModel):
    asset_id: int
    customer_id: int
    start_datetime: datetime
    end_datetime: datetime
    package_id: Optional[int] = None
    source: Literal["email", "whatsapp", "admin", "ai"] = "admin"
    notes: str = ""


class BookingUpdate(BaseModel):
    status: Optional[Literal["pending", "confirmed", "cancelled", "completed"]] = None
    notes: Optional[str] = None


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_id: int
    customer_id: int
    start_datetime: datetime
    end_datetime: datetime
    total_price: float
    deposit_amount: float
    package_id: Optional[int] = None
    package_name: str = ""
    status: str
    source: str
    notes: str
    calendar_event_id: str
    created_at: datetime


# ---------- Availability ----------
class AvailabilityQuery(BaseModel):
    asset_type: Literal["boat", "jetski", "car", "van"]
    passengers: int = 1
    start_datetime: datetime
    end_datetime: datetime


class AvailabilityResult(BaseModel):
    asset: AssetOut
    available: bool
    quote: Optional[dict] = None


# ---------- Messaging ----------
class MessageCreate(BaseModel):
    customer_id: int
    channel: Literal["email", "whatsapp"]
    body: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    channel: str
    direction: str
    body: str
    created_at: datetime


# ---------- AI ----------
class AIChatRequest(BaseModel):
    customer_id: Optional[int] = None
    channel: Literal["email", "whatsapp", "admin"] = "admin"
    message: str
    language: Optional[str] = None


class AIChatResponse(BaseModel):
    reply: str
    needs_human: bool
    actions: List[dict] = Field(default_factory=list)
