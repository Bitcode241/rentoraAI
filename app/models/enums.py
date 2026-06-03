import enum


class AssetType(str, enum.Enum):
    boat = "boat"
    jetski = "jetski"
    car = "car"
    van = "van"


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class Channel(str, enum.Enum):
    email = "email"
    whatsapp = "whatsapp"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class Source(str, enum.Enum):
    email = "email"
    whatsapp = "whatsapp"
    admin = "admin"
    ai = "ai"
