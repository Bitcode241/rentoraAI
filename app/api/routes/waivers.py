from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.booking import Booking
from app.models.waiver import WaiverTemplate
from app.services import waiver_service

router = APIRouter(prefix="/api/waivers", tags=["waivers"])
public_router = APIRouter(tags=["waivers-public"])


def _tpl_out(t: WaiverTemplate) -> dict:
    return {"id": t.id, "asset_type": t.asset_type, "lang": t.lang,
            "title": t.title or "", "body": t.body or "",
            "version": t.version, "require_document": bool(t.require_document),
            "active": bool(t.active), "updated_at": t.updated_at}


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = (db.query(WaiverTemplate)
            .order_by(WaiverTemplate.asset_type, WaiverTemplate.lang).all())
    return {"languages": list(waiver_service.LANGS),
            "templates": [_tpl_out(t) for t in rows]}


@router.put("/templates")
def save_template(payload: dict, db: Session = Depends(get_db),
                  _=Depends(get_current_user)):
    from app.services import audit
    asset_type = (payload.get("asset_type") or "").strip()
    lang = (payload.get("lang") or "en").strip()[:5]
    if not asset_type:
        raise HTTPException(400, "Odaberi tip (jetski/boat/transfer).")
    t = waiver_service.save_template(
        db, asset_type=asset_type, lang=lang,
        title=(payload.get("title") or "").strip()[:200],
        body=payload.get("body") or "",
        require_document=bool(payload.get("require_document", True)),
        template_id=payload.get("id"))
    audit.record(db, "waiver_template_saved",
                 actor=getattr(_, "username", "admin"), entity="waiver",
                 entity_id=t.id,
                 detail=f"{asset_type}/{lang} — verzija {t.version}")
    return {"ok": True, "template": _tpl_out(t)}


@router.get("/booking/{booking_id}")
def booking_waiver(booking_id: int, db: Session = Depends(get_db),
                   _=Depends(get_current_user)):
    """Signing status + link/QR for one booking."""
    from app.core.config import settings
    b = db.get(Booking, booking_id)
    if not b:
        raise HTTPException(404, "Rezervacija nije pronađena.")
    sig = waiver_service.signature_for(db, booking_id)
    token = sig.token if sig else waiver_service.sign_token(db, booking_id)
    base = (settings.public_base_url or "").rstrip("/")
    return {
        "booking_id": booking_id,
        "signed": bool(sig),
        "url": f"{base}/w/{booking_id}-{token}",
        "signature": None if not sig else {
            "signer_name": sig.signer_name,
            "signer_document": sig.signer_document,
            "signed_at": sig.signed_at,
            "version": sig.template_version,
            "title": sig.title_snapshot,
            "body": sig.body_snapshot,
            "signature_png": sig.signature_png,
        },
    }


# ---------- public signing page (no login — guest opens it on the spot) ----------

@public_router.get("/w/{ref}")
def sign_page(ref: str, lang: str = "", db: Session = Depends(get_db)):
    from app.models.asset import Asset
    from app.models.customer import Customer
    try:
        booking_id = int(str(ref).split("-")[0])
    except (ValueError, IndexError):
        return HTMLResponse("<p>Neispravan link.</p>", status_code=400)
    b = db.get(Booking, booking_id)
    if not b:
        return HTMLResponse("<p>Rezervacija nije pronađena.</p>", status_code=404)
    a = db.get(Asset, b.asset_id) if b.asset_id else None
    c = db.get(Customer, b.customer_id) if b.customer_id else None
    atype = (a.asset_type if a else "jetski")
    lang = (lang or "en")[:2]
    tpl = waiver_service.get_template(db, atype, lang)
    existing = waiver_service.signature_for(db, booking_id)
    if existing:
        return HTMLResponse(_done_html(existing))
    if not tpl or not (tpl.body or "").strip():
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:30px'>Uvjeti još nisu "
            "postavljeni. Javite se osoblju.</p>")
    return HTMLResponse(_sign_html(ref, tpl, b, c, lang))


@public_router.post("/w/{ref}")
async def submit_signature(ref: str, request: Request,
                           db: Session = Depends(get_db)):
    from app.models.asset import Asset
    form = dict(await request.form())
    try:
        booking_id = int(str(ref).split("-")[0])
        token = str(ref).split("-", 1)[1]
    except (ValueError, IndexError):
        return HTMLResponse("<p>Neispravan link.</p>", status_code=400)
    b = db.get(Booking, booking_id)
    if not b:
        return HTMLResponse("<p>Rezervacija nije pronađena.</p>", status_code=404)
    if waiver_service.signature_for(db, booking_id):
        return HTMLResponse(_done_html(waiver_service.signature_for(db, booking_id)))
    a = db.get(Asset, b.asset_id) if b.asset_id else None
    lang = (form.get("lang") or "en")[:2]
    tpl = waiver_service.get_template(db, (a.asset_type if a else "jetski"), lang)
    try:
        sig = waiver_service.record_signature(
            db, booking_id=booking_id, template=tpl,
            signer_name=form.get("name", ""),
            signer_document=form.get("document", ""),
            signer_birth=form.get("birth", ""),
            signature_png=form.get("signature", ""),
            lang=lang,
            ip=(request.client.host if request.client else ""),
            token=token)
    except ValueError as e:
        return HTMLResponse(f"<p style='font-family:sans-serif;padding:30px'>"
                            f"{e}<br><a href=''>Natrag</a></p>", status_code=400)
    return HTMLResponse(_done_html(sig))


def _done_html(sig) -> str:
    from app.core.timeutil import fmt_local
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Potpisano</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f6f9fb;color:#0f2230;display:grid;place-items:center;min-height:100vh;margin:0}}
.b{{background:#fff;border-radius:16px;padding:34px 26px;max-width:400px;text-align:center;
box-shadow:0 8px 30px rgba(16,40,56,.09);margin:16px}}
.i{{width:64px;height:64px;border-radius:50%;background:#1a8a5a;color:#fff;display:grid;
place-items:center;font-size:32px;margin:0 auto 16px}}</style></head>
<body><div class="b"><div class="i">✓</div>
<h2 style="margin:0 0 6px">Hvala, potpisano</h2>
<p style="color:#6a7e8c;margin:0">{sig.signer_name}<br>
<span style="font-size:13px">{fmt_local(sig.signed_at)}</span></p>
<p style="font-size:12px;color:#9fb0bb;margin-top:18px">Možete zatvoriti ovu stranicu.</p>
</div></body></html>"""


def _sign_html(ref, tpl, booking, customer, lang) -> str:
    t = {
        "en": ("Before you go out", "Full name", "ID / passport number",
               "Date of birth", "Sign below with your finger", "Clear",
               "I have read and accept", "Confirm & sign"),
        "hr": ("Prije izlaska", "Ime i prezime", "Broj osobne / putovnice",
               "Datum rođenja", "Potpišite prstom ispod", "Očisti",
               "Pročitao sam i prihvaćam", "Potvrdi i potpiši"),
        "de": ("Vor der Abfahrt", "Vor- und Nachname", "Ausweis-/Passnummer",
               "Geburtsdatum", "Unterschreiben Sie unten", "Löschen",
               "Ich habe gelesen und akzeptiere", "Bestätigen & unterschreiben"),
    }.get(lang, None) or {
        "en": ("Before you go out", "Full name", "ID / passport number",
               "Date of birth", "Sign below with your finger", "Clear",
               "I have read and accept", "Confirm & sign")}["en"]
    head, l_name, l_doc, l_birth, l_sign, l_clear, l_accept, l_btn = t
    prefill = (customer.full_name if customer and customer.full_name
               and "@" not in (customer.full_name or "") else "")
    doc_field = "" if not tpl.require_document else f"""
      <label>{l_doc}</label><input name="document" required>"""
    body_html = (tpl.body or "").replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{tpl.title or head}</title><style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f6f9fb;color:#0f2230;margin:0;padding:16px}}
.wrap{{max-width:520px;margin:0 auto}}
.card{{background:#fff;border-radius:14px;padding:20px;margin-bottom:14px;
box-shadow:0 2px 12px rgba(16,40,56,.06)}}
h1{{font-size:20px;margin:0 0 4px}}
.terms{{white-space:pre-wrap;font-size:13.5px;line-height:1.55;max-height:38vh;
overflow:auto;border:1px solid #e3ebef;border-radius:10px;padding:12px;background:#fbfdfe}}
label{{display:block;font-size:12px;color:#6a7e8c;margin:12px 0 4px;font-weight:600}}
input{{width:100%;padding:12px;border:1px solid #d6e2e8;border-radius:9px;font-size:16px}}
canvas{{width:100%;height:170px;border:2px dashed #c3d3db;border-radius:10px;
background:#fff;touch-action:none;display:block}}
.row{{display:flex;gap:10px;align-items:center;margin-top:8px}}
button{{font-size:15px;padding:13px 18px;border-radius:10px;border:0;cursor:pointer}}
.go{{background:#0f2230;color:#fff;width:100%;font-weight:700;margin-top:14px}}
.go:disabled{{opacity:.45}}
.cl{{background:#eef4f7;color:#0f2230}}
.chk{{display:flex;gap:10px;align-items:flex-start;margin-top:14px;font-size:14px}}
.chk input{{width:auto;margin-top:3px}}
.err{{color:#c0392b;font-size:13px;margin-top:8px}}</style></head>
<body><div class="wrap">
<div class="card">
  <h1>{tpl.title or head}</h1>
  <div style="font-size:12.5px;color:#6a7e8c;margin-bottom:10px">
    Rezervacija #{booking.id} · {booking.package_name or ''}</div>
  <div class="terms">{body_html}</div>
</div>
<form class="card" method="post" id="f">
  <input type="hidden" name="lang" value="{lang}">
  <input type="hidden" name="signature" id="sig">
  <label>{l_name}</label><input name="name" required value="{prefill}">
  {doc_field}
  <label>{l_birth}</label><input name="birth" placeholder="dd.mm.yyyy.">
  <label>{l_sign}</label>
  <canvas id="c"></canvas>
  <div class="row"><button type="button" class="cl" onclick="clr()">{l_clear}</button></div>
  <label class="chk"><input type="checkbox" id="ok" required> {l_accept}</label>
  <button class="go" type="submit">{l_btn}</button>
  <div class="err" id="e"></div>
</form></div>
<script>
const c=document.getElementById('c'),x=c.getContext('2d');
let drawing=false,dirty=false;
function fit(){{const r=c.getBoundingClientRect();c.width=r.width*2;c.height=r.height*2;
  x.scale(2,2);x.lineWidth=2.2;x.lineCap='round';x.strokeStyle='#0f2230';}}
fit();window.addEventListener('resize',()=>{{const d=c.toDataURL();fit();}});
function pos(e){{const r=c.getBoundingClientRect();const p=e.touches?e.touches[0]:e;
  return [p.clientX-r.left,p.clientY-r.top];}}
function start(e){{e.preventDefault();drawing=true;dirty=true;const[a,b]=pos(e);
  x.beginPath();x.moveTo(a,b);}}
function move(e){{if(!drawing)return;e.preventDefault();const[a,b]=pos(e);x.lineTo(a,b);x.stroke();}}
function end(){{drawing=false;}}
c.addEventListener('mousedown',start);c.addEventListener('mousemove',move);
window.addEventListener('mouseup',end);
c.addEventListener('touchstart',start);c.addEventListener('touchmove',move);
c.addEventListener('touchend',end);
function clr(){{x.clearRect(0,0,c.width,c.height);dirty=false;}}
document.getElementById('f').addEventListener('submit',function(ev){{
  const e=document.getElementById('e');
  if(!dirty){{ev.preventDefault();e.textContent='Potpis je obavezan.';return;}}
  if(!document.getElementById('ok').checked){{ev.preventDefault();
    e.textContent='Morate prihvatiti uvjete.';return;}}
  document.getElementById('sig').value=c.toDataURL('image/png');
}});
</script></body></html>"""
