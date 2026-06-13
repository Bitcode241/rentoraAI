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
    page_url: str = ""
    default_pickup: str = ""
    model_group: str = ""
    booking_priority: int = 100
    out_of_service: bool = False
    calendar_id: str = ""
    active: bool = True
    # External (partner) asset fields
    is_external: bool = False
    owner_name: str = ""
    owner_email: str = ""
    owner_phone: str = ""
    commission_percent: float = 0.0
    payment_direction: str = "you"


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
    page_url: Optional[str] = None
    default_pickup: Optional[str] = None
    model_group: Optional[str] = None
    booking_priority: Optional[int] = None
    out_of_service: Optional[bool] = None
    calendar_id: Optional[str] = None
    active: Optional[bool] = None
    is_external: Optional[bool] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    commission_percent: Optional[float] = None
    payment_direction: Optional[str] = None


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
    passengers: int = 0
    payment_status: Optional[str] = None
    pickup_location: str = ""
    deposit_amount: Optional[float] = None
    notes: str = ""


class BookingUpdate(BaseModel):
    status: Optional[Literal["pending", "confirmed", "cancelled", "completed"]] = None
    notes: Optional[str] = None
    deposit_amount: Optional[float] = None
    total_price: Optional[float] = None
    passengers: Optional[int] = None
    pickup_location: Optional[str] = None
    payment_status: Optional[str] = None
    transfer_note: Optional[str] = None


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
    payment_status: str = "unpaid"
    amount_paid: float = 0.0
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
