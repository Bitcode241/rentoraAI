"""Tour catalog service.

The catalog (TourType) is the single source of truth for a tour: one row, one id,
one price — regardless of how many physical units exist. Editing a catalog tour
propagates the price/duration to every matching per-unit package so availability
keeps working. Reports group bookings by tour_type_id.
"""
from sqlalchemy.orm import Session

from app.models.tour_type import TourType
from app.models.asset import Asset
from app.models.package import RentalPackage
from app.core.logging import get_logger

log = get_logger("tours")


def list_tours(db: Session, asset_type: str = "", active_only: bool = False):
    q = db.query(TourType)
    if asset_type:
        q = q.filter(TourType.asset_type == asset_type)
    if active_only:
        q = q.filter(TourType.active == True)  # noqa: E712
    return q.order_by(TourType.asset_type, TourType.sort_order, TourType.id).all()


def match_tour_id(db: Session, asset_type: str, name: str, duration: int):
    """Find the catalog tour id that matches a per-unit package (by name+duration)."""
    t = (db.query(TourType)
         .filter(TourType.asset_type == asset_type,
                 TourType.name == name,
                 TourType.duration_minutes == duration)
         .first())
    return t.id if t else None


def sync_tour_to_units(db: Session, tour: TourType):
    """Push a catalog tour's price/duration onto every matching per-unit package,
    and create the package on units that don't have it yet. Keeps availability
    working while the catalog stays the single source of truth for pricing."""
    units = (db.query(Asset)
             .filter(Asset.asset_type == tour.asset_type)
             .all())
    for u in units:
        pkg = (db.query(RentalPackage)
               .filter(RentalPackage.asset_id == u.id,
                       RentalPackage.name == tour.name)
               .first())
        if pkg:
            pkg.price = tour.price
            pkg.duration_minutes = tour.duration_minutes
            pkg.guided = tour.guided
            pkg.description = tour.description or ""
        else:
            db.add(RentalPackage(
                asset_id=u.id, name=tour.name,
                duration_minutes=tour.duration_minutes, price=tour.price,
                guided=tour.guided, description=tour.description or ""))
    db.commit()


def remove_tour_from_units(db: Session, asset_type: str, name: str):
    """Delete the matching per-unit packages by asset_type + tour name.
    Takes plain values (not an ORM object) to avoid autoflushing a throwaway
    TourType into the session."""
    units = db.query(Asset).filter(Asset.asset_type == asset_type).all()
    unit_ids = [u.id for u in units]
    if unit_ids:
        (db.query(RentalPackage)
         .filter(RentalPackage.asset_id.in_(unit_ids),
                 RentalPackage.name == name)
         .delete(synchronize_session=False))
        db.commit()


def seed_catalog_from_packages(db: Session):
    """One-time: build the catalog from existing per-unit packages (deduped by
    name+duration per asset type). Safe to run repeatedly — skips existing."""
    seen = set()
    created = 0
    rows = (db.query(RentalPackage, Asset)
            .join(Asset, RentalPackage.asset_id == Asset.id)
            .all())
    for pkg, asset in rows:
        key = (asset.asset_type, pkg.name, pkg.duration_minutes)
        if key in seen:
            continue
        seen.add(key)
        exists = (db.query(TourType)
                  .filter(TourType.asset_type == asset.asset_type,
                          TourType.name == pkg.name,
                          TourType.duration_minutes == pkg.duration_minutes)
                  .first())
        if exists:
            continue
        db.add(TourType(
            asset_type=asset.asset_type, name=pkg.name,
            duration_minutes=pkg.duration_minutes, price=pkg.price,
            guided=pkg.guided, description=pkg.description or "",
            sort_order=pkg.duration_minutes))
        created += 1
    db.commit()
    log.info("tour_catalog_seeded", created=created)
    return created


def backfill_booking_tour_ids(db: Session):
    """Link existing bookings to catalog tours by matching name+asset_type."""
    from app.models.booking import Booking
    updated = 0
    bookings = db.query(Booking).filter(Booking.tour_type_id.is_(None)).all()
    for b in bookings:
        if not b.package_name:
            continue
        asset = db.get(Asset, b.asset_id)
        if not asset:
            continue
        t = (db.query(TourType)
             .filter(TourType.asset_type == asset.asset_type,
                     TourType.name == b.package_name)
             .first())
        if t:
            b.tour_type_id = t.id
            updated += 1
    db.commit()
    return updated


def tour_report(db: Session, asset_type: str = ""):
    """Sales per tour: count + revenue, grouped by canonical tour id."""
    from app.models.booking import Booking
    tours = list_tours(db, asset_type)
    out = []
    for t in tours:
        rows = db.query(Booking).filter(Booking.tour_type_id == t.id).all()
        paid_rows = [b for b in rows if (b.payment_status in ("deposit_paid", "paid"))]
        revenue = sum(b.total_price or 0 for b in paid_rows)
        deposits = sum(b.amount_paid or 0 for b in paid_rows)
        out.append({
            "tour_id": t.id,
            "name": t.name,
            "asset_type": t.asset_type,
            "price": t.price,
            "bookings": len(paid_rows),
            "revenue": round(revenue, 2),
            "deposits_collected": round(deposits, 2),
            "active": t.active,
        })
    return out
