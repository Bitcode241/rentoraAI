"""Seed the REAL fleet (boats + jet skis) with per-asset price packages.

Run once after migrations:
    python -m scripts.seed_fleet            # add fleet if empty
    python -m scripts.seed_fleet --reset    # wipe assets+packages and reload

Vehicles (Vito vans, E-class cars) are intentionally NOT added as bookable
assets — they are transfer-only and will be modeled as add-ons later.

Deposit is 30% on everything (deposit_percent=30). The rest is paid on arrival.
Jet skis: requires_license is True by law but show_license_to_customer=False,
so the AI/website never mention it to customers (per owner instruction).
"""
import sys
from app.core.database import SessionLocal, Base, engine
from app.models.asset import Asset
from app.models.package import RentalPackage
from app.models.transfer import TransferZone
from app.core.logging import get_logger

log = get_logger("seed-fleet")

# name, capacity, [ (package_name, duration_min, price, guided) ]
BOATS = [
    ("Barracuda 545 (1)", 8, [("4h", 240, 350.0, False), ("8h", 480, 500.0, False), ("Sunset 2h", 120, 250.0, False)]),
    ("Barracuda 545 (2)", 8, [("4h", 240, 350.0, False), ("8h", 480, 500.0, False), ("Sunset 2h", 120, 250.0, False)]),
    ("4K Marine", 10, [("4h", 240, 450.0, False), ("8h", 480, 600.0, False), ("Sunset 2h", 120, 350.0, False)]),
    ("Gaia 670", 9, [("4h", 240, 370.0, False), ("8h", 480, 570.0, False), ("Sunset 2h", 120, 330.0, False)]),
    ("Atlantic Marine 670", 9, [("4h", 240, 400.0, False), ("8h", 480, 550.0, False), ("Sunset 2h", 120, 350.0, False)]),
    ("Atlantic Marine 750", 11, [("4h", 240, 450.0, False), ("8h", 480, 700.0, False), ("Sunset 2h", 120, 400.0, False)]),
]

JETSKI_PACKAGES = [
    ("30 min", 30, 90.0, False),
    ("1h", 60, 140.0, False),
    ("2h", 120, 250.0, False),
    ("Safari 90min (guided)", 90, 250.0, True),
    ("Safari 120min (guided)", 120, 350.0, True),
]
JETSKI_COUNT = 6
JETSKI_CAPACITY = 2  # Yamaha VX: max 2 people per jet

# name, car_price, van_price (one-way EUR), sort_order
TRANSFER_ZONES = [
    ("Lokalno (Dubrovnik)", 25.0, 35.0, 1),
    ("Sheraton", 35.0, 45.0, 2),
    ("ACI Marina Komolac", 35.0, 45.0, 3),
    ("Zračna luka (Airport)", 55.0, 75.0, 4),
]


def _make_asset(db, name, atype, capacity, packages, requires_license=False,
                show_license=True):
    asset = Asset(
        name=name, asset_type=atype, capacity=capacity,
        deposit=0.0, deposit_percent=30.0,
        requires_license=requires_license,
        show_license_to_customer=show_license,
        location="Dubrovnik", description=f"{name}",
    )
    db.add(asset)
    db.flush()  # get asset.id
    for (pname, dur, price, guided) in packages:
        db.add(RentalPackage(asset_id=asset.id, name=pname, duration_minutes=dur,
                             price=price, guided=guided))
    return asset


def seed_fleet(reset: bool = False):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if reset:
            db.query(RentalPackage).delete()
            db.query(Asset).delete()
            db.commit()
            log.info("fleet_reset")

        if db.query(Asset).count() > 0:
            log.info("fleet_exists_skipping", count=db.query(Asset).count())
            print("Fleet already present. Use --reset to reload.")
            return

        for (name, cap, pkgs) in BOATS:
            _make_asset(db, name, "boat", cap, pkgs)

        for i in range(1, JETSKI_COUNT + 1):
            _make_asset(db, f"Yamaha VX ({i})", "jetski", JETSKI_CAPACITY,
                        JETSKI_PACKAGES, requires_license=True, show_license=False)

        db.commit()
        # Transfer zones (idempotent: only add if missing)
        for (zname, car, van, order) in TRANSFER_ZONES:
            if not db.query(TransferZone).filter(TransferZone.name == zname).first():
                db.add(TransferZone(name=zname, car_price=car, van_price=van,
                                    sort_order=order))
        db.commit()

        boats = db.query(Asset).filter(Asset.asset_type == "boat").count()
        jetski = db.query(Asset).filter(Asset.asset_type == "jetski").count()
        pkgs = db.query(RentalPackage).count()
        zones = db.query(TransferZone).count()
        log.info("fleet_seeded", boats=boats, jetski=jetski, packages=pkgs, zones=zones)
        # build the tour catalog (one id per tour) from the seeded packages
        try:
            from app.services import tour_service
            tours = tour_service.seed_catalog_from_packages(db)
        except Exception:
            tours = 0
        print(f"Seeded {boats} boats + {jetski} jet skis, {pkgs} packages, "
              f"{zones} transfer zones, {tours} tours.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_fleet(reset="--reset" in sys.argv)
