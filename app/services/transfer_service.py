"""Transfer pricing service.

Vehicle selection by passenger count, then sum the vehicle prices for the zone.
  <= 3        -> 1 car
  4 .. 8      -> 1 van
  9 .. 11     -> 1 van (8) + remainder in 1 car
  12+         -> as many vans as needed, last leftover (<=3) may use a car

One-way price by default; round_trip doubles it.
"""
from sqlalchemy.orm import Session
from app.models.transfer import TransferZone

CAR_CAP = 3
VAN_CAP = 8


def plan_vehicles(passengers: int) -> dict:
    """Return how many vans and cars are needed for a group."""
    if passengers <= 0:
        return {"vans": 0, "cars": 0}
    if passengers <= CAR_CAP:
        return {"vans": 0, "cars": 1}
    if passengers <= VAN_CAP:
        return {"vans": 1, "cars": 0}

    # 9+ : fill vans, then handle the remainder
    vans = passengers // VAN_CAP
    remainder = passengers % VAN_CAP
    cars = 0
    if remainder == 0:
        pass
    elif remainder <= CAR_CAP:
        cars = 1                      # leftover small group -> a car (cheaper)
    else:
        vans += 1                     # leftover too big for a car -> another van
    return {"vans": vans, "cars": cars}


def quote_transfer(zone: TransferZone, passengers: int,
                   round_trip: bool = False) -> dict:
    plan = plan_vehicles(passengers)
    one_way = plan["vans"] * zone.van_price + plan["cars"] * zone.car_price
    total = one_way * (2 if round_trip else 1)
    return {
        "zone": zone.name,
        "passengers": passengers,
        "vehicles": plan,
        "direction": "round_trip" if round_trip else "one_way",
        "price_one_way": round(one_way, 2),
        "total_price": round(total, 2),
        "currency": "EUR",
    }


def find_zone(db: Session, name: str) -> TransferZone | None:
    """Case-insensitive lookup by zone name."""
    if not name:
        return None
    n = name.strip().lower()
    for z in db.query(TransferZone).filter(TransferZone.active.is_(True)).all():
        if z.name.lower() == n or n in z.name.lower() or z.name.lower() in n:
            return z
    return None


def list_zones(db: Session) -> list:
    zones = db.query(TransferZone).filter(TransferZone.active.is_(True))\
        .order_by(TransferZone.sort_order).all()
    return [{"id": z.id, "name": z.name, "car_price": z.car_price,
             "van_price": z.van_price} for z in zones]
