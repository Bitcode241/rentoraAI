"""myPOS Checkout integration (alternative to Stripe).

Two things matter for safety here:

1. Every request we send is signed with our private key, and
2. every notification we receive is verified against myPOS's public key.

Without (2) anyone could POST "payment succeeded" to our endpoint. The verify
step is therefore not optional — if the signature does not check out we ignore
the callback entirely.
"""
import base64
from urllib.parse import urlencode

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# hosted checkout endpoints
LIVE_URL = "https://mypos.com/vmp/checkout"
SANDBOX_URL = "https://mypos.com/vmp/checkout-test"


def enabled() -> bool:
    """True when the owner has filled in the myPOS credentials."""
    return bool(getattr(settings, "mypos_sid", "")
                and getattr(settings, "mypos_wallet", "")
                and getattr(settings, "mypos_private_key", ""))


def is_sandbox() -> bool:
    return bool(getattr(settings, "mypos_sandbox", True))


def checkout_url() -> str:
    return SANDBOX_URL if is_sandbox() else LIVE_URL


def _concat(params: dict) -> str:
    """myPOS signs the '-' joined, base64'd values in the documented order."""
    parts = [str(v) for v in params.values()]
    return base64.b64encode("-".join(parts).encode()).decode()


def sign(params: dict) -> str:
    """Sign the request with our RSA private key (SHA-256)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key_pem = (getattr(settings, "mypos_private_key", "") or "").replace("\\n", "\n")
    if not key_pem:
        raise ValueError("myPOS private key not configured")
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    signature = key.sign(_concat(params).encode(), padding.PKCS1v15(),
                         hashes.SHA256())
    return base64.b64encode(signature).decode()


def verify_notification(params: dict, signature: str) -> bool:
    """Verify a Purchase Notify callback really came from myPOS.

    Returns False on any problem — a malformed or unverified callback must never
    be treated as a successful payment.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature
    pub_pem = (getattr(settings, "mypos_public_key", "") or "").replace("\\n", "\n")
    if not pub_pem or not signature:
        log.warning("mypos_verify_missing_key_or_signature")
        return False
    try:
        pub = serialization.load_pem_public_key(pub_pem.encode())
        pub.verify(base64.b64decode(signature), _concat(params).encode(),
                   padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError) as e:
        log.warning("mypos_signature_invalid", error=str(e)[:200])
        return False


def build_purchase(booking, asset_name: str, amount: float, guest_email: str = "",
                   guest_name: str = "", order_id: str = "",
                   group_booking_ids: list = None) -> dict:
    """Build the signed form we POST the guest to, to reach myPOS Checkout.

    Returns {url, fields, order_id} — the caller renders a tiny auto-submitting
    form (myPOS Checkout expects a form POST, not a redirect with a token).
    """
    if not enabled():
        return {"error": "mypos_not_configured",
                "message": "myPOS nije postavljen (nedostaju podaci)."}
    if amount <= 0:
        return {"error": "no_deposit", "message": "Iznos je 0."}

    base = (settings.public_base_url or "").rstrip("/")
    oid = order_id or f"RENT-{booking.id}"
    first, _, last = (guest_name or "").partition(" ")
    # NOTE: order matters — myPOS signs the concatenated values in this sequence.
    params = {
        "IPCmethod": "IPCPurchase",
        "IPCVersion": "1.4",
        "IPCLanguage": "en",
        "SID": settings.mypos_sid,
        "WalletNumber": settings.mypos_wallet,
        "Amount": f"{amount:.2f}",
        "Currency": getattr(settings, "stripe_currency", "EUR").upper(),
        "OrderID": oid,
        "URL_OK": f"{base}/pay/success?provider=mypos&order={oid}",
        "URL_Cancel": f"{base}/pay/cancel?booking={booking.id}",
        "URL_Notify": f"{base}/api/payments/mypos/notify",
        "CardTokenRequest": "0",
        "PaymentParametersRequired": "1",
        "CustomerEmail": guest_email or "",
        "CustomerFirstNames": first or "Guest",
        "CustomerFamilyName": last or "-",
        "CustomerPhone": "",
        "CustomerCountry": "HRV",
        "CustomerCity": "",
        "CustomerZIPCode": "",
        "CustomerAddress": "",
        "Note": f"Rezervacija #{booking.id} — {asset_name}"[:255],
        "CartItems": "1",
        "Article_1": f"Depozit — {asset_name}"[:100],
        "Quantity_1": "1",
        "Price_1": f"{amount:.2f}",
        "Currency_1": getattr(settings, "stripe_currency", "EUR").upper(),
        "Amount_1": f"{amount:.2f}",
        "KeyIndex": str(getattr(settings, "mypos_key_index", 1)),
    }
    try:
        signature = sign(params)
    except Exception as e:  # pragma: no cover
        log.warning("mypos_sign_failed", error=str(e)[:200])
        return {"error": "mypos_sign_failed", "message": str(e)}
    fields = dict(params)
    fields["Signature"] = signature
    log.info("mypos_purchase_built", booking_id=booking.id, order=oid,
             amount=amount, sandbox=is_sandbox())
    return {"url": checkout_url(), "fields": fields, "order_id": oid}


def parse_notification(form: dict) -> dict:
    """Pull the useful bits out of a verified Purchase Notify callback."""
    status = str(form.get("Status", ""))
    return {
        "order_id": form.get("OrderID", ""),
        "amount": float(form.get("Amount") or 0),
        "currency": form.get("Currency", "EUR"),
        "ipc_trnref": form.get("IPC_Trnref", ""),
        "status": status,
        # myPOS uses "0" for success on the notify callback
        "paid": status == "0",
    }
