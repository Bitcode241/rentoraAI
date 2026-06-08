"""AI agent loop using an OpenAI-compatible API with function calling.

Enforces business rules through tools. When the model has no API key, a
deterministic rule-based fallback handles availability questions so the
system stays usable and never invents data.
"""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import get_logger
from app.ai import tools

log = get_logger("ai-agent")

SYSTEM_PROMPT = """You are the booking assistant for a vehicle & watercraft rental business
(boats, jet skis, cars, vans).

STRICT RULES — never break these:
- NEVER invent availability. Always call the availability tools to check.
- NEVER invent prices. Use get_prices; every asset has named PACKAGES
  (e.g. boats: "4h", "8h", "Sunset 2h"; jet skis: "30 min", "1h", "2h",
  "Safari 90min", "Safari 120min"). Quote only those exact package prices.
- When creating a booking, pass the package_id the customer chose.
- Never offer an asset whose capacity is below the requested passenger count.
- Do NOT mention licenses or permits to customers under any circumstance.
- ALWAYS reply in the customer's language: {language}. If unsure of the language,
  detect it from their message and match it.
- Confirm availability AND the chosen package price before creating a booking.
- Jet skis are identical units. When several are free, offer the jet ski ONCE
  (mention how many are available if the group needs more than one), do NOT list
  every identical unit separately.
- Transfers (pickup/drop-off): the base is Dubrovnik. There is NO vehicle rental —
  vehicles exist ONLY for transfers. To price a transfer ALWAYS call
  get_transfer_price with the location, passenger count, and round_trip. NEVER use
  any availability tool for vehicles. A car seats up to 3, a van 4-8, van+car for 9+.
  Prices are one-way — set round_trip=true for both directions. Compute and state the
  price immediately; only ask the customer if the location is unknown. Do NOT ask
  irrelevant questions (e.g. number of suitcases). Offer transfer as an optional add-on.
- External/partner boats — THIS IS A STRICT RULE:
  When the guest asks for a SPECIFIC boat by name, find that exact boat in the
  availability results (match the name). If that boat has is_external=true, you
  MUST call request_external_availability for THAT boat. Do NOT offer a different
  boat instead, and do NOT use create_booking. After calling it, tell the guest
  you're checking availability and will confirm shortly. NEVER reveal the boat is
  not ours. If you cannot find the exact named boat in results, say you're
  checking availability for that specific boat — do not silently switch to another.
  Only suggest a different boat if the guest explicitly asks for alternatives.
  Once the owner confirms, the booking is created automatically and the guest is notified.
- Advance-booking rule (lead time): jet skis must be booked at least a couple of
  hours before the start, boats well in advance (several hours), transfers a few
  hours ahead. If a guest asks for a time too soon, politely explain it must be
  booked further in advance and offer the earliest possible slot. The exact hours
  are configured by the business; if a booking attempt is refused for lead time,
  relay that politely.
- Booking OUR OWN boats/jetskis (is_external=false) — ACT, DON'T STALL:
  When the guest has given you a boat name + a date + indicated they want to book
  (e.g. "rezerviraj", "full day", "book it", "I want it"), you have enough. Do NOT
  ask for another confirmation. Pick a sensible default if a small detail is missing:
  if no start time is given for a full/8h day, use 09:00; for a half/4h day use 09:00
  unless they say afternoon (then 13:00). Then immediately call send_deposit_link with
  the boat NAME (asset_name). After the tool returns success, in the SAME reply tell
  the guest the deposit link has been emailed and the booking confirms once paid. If
  the tool returns an error, do NOT tell the guest it was sent — say you're finalizing
  it and a colleague will follow up ([[ESCALATE]]). Only ask the guest a question when
  something essential is genuinely missing (which boat, or which date) — never re-ask
  something they already answered.
- NEVER ask the guest for an "asset ID", "system reference", or any internal id.
  Guests only know boat NAMES. When a guest names a boat (e.g. "Atlantic Marine 750"),
  pass that name as asset_name to the booking tools — they resolve it for you. If a
  tool can't find the boat, re-check the name yourself with find_asset_by_name; do not
  push the lookup onto the guest.
- LANGUAGE: always reply in the SAME language the guest is using in this thread. If the
  thread is in Croatian, stay in Croatian for the whole conversation. Never switch
  languages mid-thread unless the guest does.
- AFTER a boat/jetski booking is confirmed (deposit link sent), ALWAYS offer a
  transfer as a paid add-on in a friendly, professional way: ask if they'd like
  pick-up and drop-off, and make clear it is an EXTRA cost that depends on where
  they are staying. If they tell you their location, call get_transfer_price and
  quote it (note transfer is paid on site / arranged with the skipper). One clear
  offer — helpful, not pushy.
- DEPARTURE LOCATION: boats depart from either Gruz (Obala Stjepana Radića) or
  Lapad (Lapadska obala 4). Tell the guest the departure marina, and ALWAYS collect
  their PHONE NUMBER so our skipper can coordinate the exact meeting point and time
  with them on the day. Ask for the phone politely once while finalizing.
- Be warm, concise and professional. Never promise anything the tools didn't confirm.

ESCALATION (use rarely):
Most inquiries you can handle yourself — including agencies or people booking on
behalf of a guest ("for my client X"): treat these as NORMAL bookings, gather the
boat, date and passenger count, check availability and proceed exactly as for any
guest. Booking for a third party is routine, NOT a reason to escalate.
Only escalate for genuinely tricky cases you cannot resolve with the tools: a
complaint, a refund/cancellation dispute, a clearly unusual or sensitive situation,
or when a tool error blocks you. In those cases end your reply with the marker on
its own line:
[[ESCALATE]]
A human colleague will then take over. When everything is clear and resolved with
tool data, do not include the marker.
IMPORTANT: Presenting available boats/jetskis with prices, or quoting a transfer,
is a COMPLETE and resolved answer — do NOT escalate it. Listing options and inviting
the guest to confirm is exactly your job. Only the rare tricky cases above escalate.
When FACTS are provided to you (availability/prices computed for you), use them and
reply normally — never escalate a reply that is just presenting those facts.

IMPORTANT — DATES AND TIME:
The current date and time (UTC) is: {now}
- Use THIS as "now" for all calculations. Do not assume any other current date.
- Guests write dates in European format DD.MM.YYYY (e.g. "15.6.2026" = 15 June 2026).
- To check the advance-booking (lead time) rule, compute the gap between the
  requested start and the current time above. Example: if now is 6 June and the
  guest asks for 15 June, that is 9 DAYS away — far more than any lead-time of a
  few hours, so the lead-time rule is satisfied. Only refuse for lead time when the
  requested start is genuinely within the small required window from now (hours).
- Always pass dates to tools in ISO format (YYYY-MM-DDTHH:MM:SS+00:00).
"""


def _client():
    if not settings.openai_api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def run_agent(db: Session, message: str, language: str = "en",
              customer_id: int | None = None, max_steps: int = 8,
              facts: str = "") -> dict:
    client = _client()
    if client is None:
        return _fallback(db, message, language, customer_id)

    sys = SYSTEM_PROMPT.format(language=language, now=datetime.now(timezone.utc).isoformat())
    history = [{"role": "system", "content": sys}]
    if facts:
        # Code-computed facts (availability, prices). The AI MUST use these as the
        # source of truth and may only rephrase tone — never change boats/prices.
        history.append({"role": "system", "content": facts})
    if customer_id:
        history.append({"role": "system",
                        "content": f"The customer_id is {customer_id}."})
    history.append({"role": "user", "content": message})

    actions = []
    needs_human = False

    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=settings.openai_model, messages=history,
            tools=tools.TOOL_SCHEMAS, tool_choice="auto", temperature=0.2)
        choice = resp.choices[0]
        msg = choice.message
        history.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            reply = msg.content or ""
            escalate = "[[ESCALATE]]" in reply
            reply = reply.replace("[[ESCALATE]]", "").strip()
            return {"reply": reply, "needs_human": needs_human or escalate,
                    "actions": actions}

        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            # auto-fill customer_id if the tool needs it and the AI didn't provide it
            if customer_id and not args.get("customer_id"):
                args["customer_id"] = customer_id
            func = tools.TOOL_FUNCS.get(fname)
            try:
                result = func(db, **args) if func else {"error": "unknown_tool"}
            except Exception as e:  # tool raised (e.g. not available)
                result = {"error": str(e)}
                needs_human = True
            # If a booking/payment tool returned an error, flag for human so we
            # never tell the guest something succeeded when it didn't.
            if isinstance(result, dict) and result.get("error") and fname in (
                    "send_deposit_link", "request_external_availability",
                    "create_booking"):
                needs_human = True
            actions.append({"tool": fname, "args": args, "result": result})
            history.append({"role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str)})

    # Loop ended without the AI writing a final text reply (it kept calling tools
    # until max_steps). Force ONE last call with tools DISABLED so the model MUST
    # produce a text answer to the guest. This guarantees a reply every time.
    try:
        history.append({"role": "system",
                        "content": "Now write your final reply to the guest in their "
                                    "language, using the tool results above. If a deposit "
                                    "payment link (payment_url) was created, include it as "
                                    "a clickable link and state the deposit amount. Do not "
                                    "call any tools — just write the message."})
        final = client.chat.completions.create(
            model=settings.openai_model, messages=history, temperature=0.2)
        reply = (final.choices[0].message.content or "").strip()
        escalate = "[[ESCALATE]]" in reply
        reply = reply.replace("[[ESCALATE]]", "").strip()
        if reply:
            return {"reply": reply, "needs_human": needs_human or escalate,
                    "actions": actions}
    except Exception as e:
        log.warning("final_reply_failed", error=str(e))

    # Last-resort safety net: if we created a deposit link, build the reply in code
    # so the guest always gets it even if the model produced nothing.
    for act in reversed(actions):
        if act["tool"] == "send_deposit_link":
            r = act["result"]
            if isinstance(r, dict) and r.get("payment_url"):
                reply = _deposit_reply(language, r)
                return {"reply": reply, "needs_human": False, "actions": actions}
            break
    return {"reply": "I need a moment — a colleague will follow up shortly.",
            "needs_human": True, "actions": actions}


def _deposit_reply(language: str, r: dict) -> str:
    """Build a clean confirmation+link reply if the AI didn't write one itself.
    Always includes a transfer up-sell offer and asks for a contact phone, so these
    happen reliably (in code) even when the model skips them."""
    asset = r.get("asset", "")
    deposit = r.get("deposit_amount", 0)
    total = r.get("total_price", 0)
    url = r.get("payment_url", "")
    lang = (language or "en").lower()[:2]
    if lang == "hr":
        return (f"Pozdrav,\n\nVaša rezervacija za {asset} je spremna. Za potvrdu "
                f"molimo uplatu depozita od {deposit:.2f} EUR (ukupna cijena "
                f"{total:.2f} EUR, ostatak na licu mjesta).\n\n"
                f"Sigurna poveznica za uplatu:\n{url}\n\n"
                f"Rezervacija se potvrđuje automatski nakon uplate.\n\n"
                f"Trebate li prijevoz do plovila (dolazak i/ili odlazak)? Možemo "
                f"organizirati transfer uz doplatu ovisno o lokaciji gdje odsjedate — "
                f"javite nam adresu pa šaljemo cijenu. Molimo i Vaš broj telefona "
                f"kako bi se naš skiper mogao dogovoriti oko točnog mjesta i vremena "
                f"polaska. Hvala!")
    if lang == "de":
        return (f"Hallo,\n\nIhre Buchung für {asset} ist bereit. Zur Bestätigung "
                f"zahlen Sie bitte die Anzahlung von {deposit:.2f} EUR (Gesamtpreis "
                f"{total:.2f} EUR, Rest vor Ort).\n\n"
                f"Sicherer Zahlungslink:\n{url}\n\n"
                f"Die Buchung wird nach Zahlung automatisch bestätigt.\n\n"
                f"Benötigen Sie einen Transfer zum Boot (Hin- und/oder Rückfahrt)? "
                f"Gegen Aufpreis je nach Unterkunft möglich — senden Sie uns Ihre "
                f"Adresse für den Preis. Bitte teilen Sie uns auch Ihre Telefonnummer "
                f"mit, damit unser Skipper Treffpunkt und Zeit abstimmen kann. Danke!")
    return (f"Hello,\n\nYour booking for {asset} is ready. To confirm, please pay the "
            f"deposit of {deposit:.2f} EUR (total {total:.2f} EUR, balance on site).\n\n"
            f"Secure payment link:\n{url}\n\n"
            f"The booking confirms automatically once the deposit is paid.\n\n"
            f"Would you like a transfer to the boat (pick-up and/or drop-off)? We can "
            f"arrange it for an extra fee depending on where you're staying — send us "
            f"your address and we'll share the price. Please also share your phone "
            f"number so our skipper can coordinate the exact meeting point and time. "
            f"Thank you!")


def _fallback(db: Session, message: str, language: str, customer_id):
    """Deterministic handler when no LLM key is set. Never invents data."""
    log.info("ai_fallback_used")
    reply = ("Thanks for your message! Our assistant is currently in basic mode. "
             "A team member will review your request and reply shortly. "
             "You can also browse availability through our team directly.")
    return {"reply": reply, "needs_human": True, "actions": []}
