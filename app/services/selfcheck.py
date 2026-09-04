"""Self-check — a health sweep the owner can run any time.

It exercises the parts guests actually touch (catalog, availability, pricing,
payment config, email, notifications) and reports what is broken or risky
*before* a guest runs into it. Read-only: it never creates bookings or charges.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)

OK, WARN, FAIL = "ok", "warn", "fail"


def _c(name, status, detail="", fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def run_checks(db: Session) -> dict:
    from app.models.asset import Asset
    from app.models.booking import Booking
    from app.models.tour_type import TourType
    from app.models.package import RentalPackage
    from app.services import settings_service, meeting_service
    from app.core.config import settings

    checks = []

    # ---- fleet ----
    for atype, label in (("jetski", "Jetovi"), ("boat", "Brodovi")):
        units = db.query(Asset).filter(
            Asset.asset_type == atype,
            Asset.active == True,  # noqa: E712
            Asset.out_of_service == False).all()  # noqa: E712
        tours = db.query(TourType).filter(
            TourType.asset_type == atype,
            TourType.active == True).all()  # noqa: E712
        if not units:
            checks.append(_c(f"{label} — flota", WARN, "Nema aktivnih jedinica.",
                             "Dodaj ih u Flota ili makni iz ponude."))
            continue
        if not tours:
            checks.append(_c(f"{label} — katalog tura", FAIL,
                             f"{len(units)} jedinica, ali nijedna tura.",
                             "Dodaj ture u Ture — bez toga widget ne nudi ništa."))
            continue
        # every unit should offer every catalog tour
        missing = []
        tour_names = {t.name for t in tours}
        for u in units:
            have = {p.name for p in db.query(RentalPackage).filter(
                RentalPackage.asset_id == u.id).all()}
            gap = tour_names - have
            if gap:
                missing.append(f"{u.name} ({len(gap)})")
        if missing:
            checks.append(_c(f"{label} — usklađenost s katalogom", FAIL,
                             "Jedinice bez svih tura: " + ", ".join(missing[:4]),
                             "Ture → 'Uskladi jedinice s katalogom'."))
        else:
            checks.append(_c(f"{label} — usklađenost s katalogom", OK,
                             f"{len(units)} jedinica × {len(tours)} tura."))
        # prices sane?
        bad = [t.name for t in tours if (t.price or 0) <= 0]
        if bad:
            checks.append(_c(f"{label} — cijene", FAIL,
                             "Ture bez cijene: " + ", ".join(bad[:4]),
                             "Postavi cijenu u Ture."))
        # orphan packages (left over after renames)
        unit_ids = [u.id for u in units]
        orphans = {p.name for p in db.query(RentalPackage).filter(
            RentalPackage.asset_id.in_(unit_ids)).all()} - tour_names
        if orphans:
            checks.append(_c(f"{label} — zaostale ture", WARN,
                             "Nisu u katalogu: " + ", ".join(list(orphans)[:4]),
                             "Ture → 'Uskladi jedinice s katalogom'."))

    # ---- payments ----
    from app.services import payment_service
    provider = payment_service.active_provider(db)
    if provider == "stripe":
        if not settings.stripe_enabled():
            checks.append(_c("Naplata", FAIL, "Stripe ključ nije postavljen.",
                             "Upiši STRIPE_SECRET_KEY u .env."))
        elif settings.stripe_secret_key.startswith("sk_test"):
            checks.append(_c("Naplata", WARN, "Stripe je u TEST modu.",
                             "Za prave goste treba sk_live_ ključ."))
        else:
            has_hook = bool(getattr(settings, "stripe_webhook_secret", ""))
            checks.append(_c("Naplata", OK if has_hook else FAIL,
                             "Stripe LIVE" + ("" if has_hook else " — ali NEMA webhook secreta!"),
                             "" if has_hook else "Bez webhooka plaćanja se neće potvrditi."))
    else:
        from app.services import mypos_service
        checks.append(_c("Naplata", WARN if mypos_service.is_sandbox() else OK,
                         f"myPOS ({'sandbox' if mypos_service.is_sandbox() else 'live'})",
                         "Prebaci na live kad testiraš." if mypos_service.is_sandbox() else ""))

    # ---- public URL (used in links, QR, redirects) ----
    base = (settings.public_base_url or "").strip()
    if not base.startswith("https://"):
        checks.append(_c("Javna adresa", FAIL, f"PUBLIC_BASE_URL = '{base or '—'}'",
                         "Mora biti https adresa — inače pucaju linkovi i QR."))
    else:
        checks.append(_c("Javna adresa", OK, base))

    # ---- guest communication ----
    try:
        from app.integrations.email_imap import MultiMailboxManager
        mgr = MultiMailboxManager.from_db(db)
        checks.append(_c("Email gostima", OK if mgr.enabled else WARN,
                         "Sandučić spojen." if mgr.enabled else "Nije spojen mail.",
                         "" if mgr.enabled else "Bez toga gost ne dobiva potvrdu."))
    except Exception as e:
        checks.append(_c("Email gostima", WARN, f"Provjera nije uspjela: {str(e)[:80]}"))

    pts = meeting_service.get_meeting_points(db)
    wa = meeting_service.get_whatsapp_number(db)
    if not pts:
        checks.append(_c("Lokacije polaska", WARN, "Nema unesenih lokacija.",
                         "Postavke → Lokacije: gost ne zna gdje doći."))
    elif not any(p.get("primary") for p in pts):
        checks.append(_c("Lokacije polaska", WARN, "Nijedna nije glavna."))
    else:
        checks.append(_c("Lokacije polaska", OK, f"{len(pts)} lokacija."))
    checks.append(_c("WhatsApp broj", OK if wa else WARN, wa or "Nije upisan.",
                     "" if wa else "Postavke → Lokacije."))

    # ---- business identity (needed on vouchers/invoices) ----
    if not settings_service.get(db, "business_oib", ""):
        checks.append(_c("OIB tvrtke", WARN, "Nije upisan.",
                         "Potreban za partnerske vaučere."))
    else:
        checks.append(_c("OIB tvrtke", OK, "Upisan."))

    # ---- data integrity ----
    now = datetime.now(timezone.utc)

    def _aware(dt):
        """DB rows may be naive; treat those as UTC so comparisons work."""
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    future = [b for b in db.query(Booking).filter(
        Booking.status != "cancelled").all()
        if _aware(b.start_datetime) and _aware(b.start_datetime) >= now]
    # double-booked units
    clashes = []
    by_asset = {}
    for b in future:
        by_asset.setdefault(b.asset_id, []).append(b)
    for aid, bs in by_asset.items():
        bs.sort(key=lambda x: _aware(x.start_datetime))
        for i in range(len(bs) - 1):
            if _aware(bs[i].end_datetime) > _aware(bs[i + 1].start_datetime):
                clashes.append(f"#{bs[i].id}/#{bs[i+1].id}")
    checks.append(_c("Dvostruke rezervacije", FAIL if clashes else OK,
                     ", ".join(clashes[:5]) if clashes else "Nema preklapanja.",
                     "Otvori te rezervacije i pomakni jednu." if clashes else ""))

    # bookings with money problems
    weird = [b.id for b in future
             if ((b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0))
             > (b.total_price or 0) + 0.01]
    checks.append(_c("Preplaćene rezervacije", WARN if weird else OK,
                     f"ID: {weird[:5]}" if weird else "Nema.",
                     "Provjeri iznose — možda dvostruki upis." if weird else ""))

    # unpaid bookings starting soon
    soon = [b.id for b in future
            if _aware(b.start_datetime) <= now + timedelta(days=2)
            and ((b.amount_paid or 0) + (getattr(b, "cash_collected", 0) or 0)) <= 0]
    checks.append(_c("Neplaćeno, a uskoro", WARN if soon else OK,
                     f"{len(soon)} rezervacija bez ijedne uplate" if soon else "Nema.",
                     "Pošalji link za plaćanje." if soon else ""))

    # ---- notifications ----
    from app.models.push import PushSubscription
    n_dev = db.query(PushSubscription).count()
    checks.append(_c("Obavijesti na telefon", OK if n_dev else WARN,
                     f"{n_dev} uređaj(a)." if n_dev else "Nijedan uređaj.",
                     "" if n_dev else "Postavke → Obavijesti."))

    fails = sum(1 for c in checks if c["status"] == FAIL)
    warns = sum(1 for c in checks if c["status"] == WARN)
    log.info("selfcheck_run", checks=len(checks), fails=fails, warns=warns)
    return {
        "at": now,
        "checks": checks,
        "total": len(checks),
        "fails": fails,
        "warns": warns,
        "healthy": fails == 0,
    }
