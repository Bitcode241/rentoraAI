"""Voucher QR: a per-booking public token + QR image that a skipper can scan to
view the booking (guest, tours, amount to collect) without logging in."""
import io
import secrets

from app.core.logging import get_logger

log = get_logger("voucher-qr")


def get_or_create_token(db, booking) -> str:
    """Return the booking's public voucher token, creating one on first use."""
    if not getattr(booking, "voucher_token", ""):
        booking.voucher_token = secrets.token_urlsafe(16)
        db.commit()
    return booking.voucher_token


def voucher_url(base_url: str, token: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/v/{token}"


def qr_png(data: str, box_size: int = 8, border: int = 2) -> bytes:
    """Generate a QR code PNG for the given data (usually a URL)."""
    import qrcode
    qr = qrcode.QRCode(version=None, box_size=box_size, border=border,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0d2b32", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
