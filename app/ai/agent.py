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
- AFTER a boat/jetski booking is confirmed (deposit link sent), offer a transfer as
  a paid add-on: ask if they'd like pick-up/drop-off, and make clear it's an EXTRA
  cost that depends on their location (where they're staying). If they give a location,
  call get_transfer_price and quote it. Keep it light — one friendly offer, don't push.
- Ask for the guest's PHONE NUMBER once, politely, when finalizing a booking (so the
  team can reach them on the day). If they decline or don't give it, proceed anyway.
- Be warm, concise and professional. Never promise anything the tools didn't confirm.

ESCALATION (very important):
If you are not confident, if the request is ambiguous, sensitive, a complaint,
a special/large/high-value request, or anything you cannot fully resolve with the
tools, do NOT guess. End your reply with the exact marker on its own line:
[[ESCALATE]]
A human colleague will then take over. When everything is clear and resolved with
tool data, do not include the marker.

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
              customer_id: int | None = None, max_steps: int = 6) -> dict:
    client = _client()
    if client is None:
        return _fallback(db, message, language, customer_id)

    sys = SYSTEM_PROMPT.format(language=language, now=datetime.now(timezone.utc).isoformat())
    history = [{"role": "system", "content": sys}]
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

    return {"reply": "I need a moment — a colleague will follow up shortly.",
            "needs_human": True, "actions": actions}


def _fallback(db: Session, message: str, language: str, customer_id):
    """Deterministic handler when no LLM key is set. Never invents data."""
    log.info("ai_fallback_used")
    reply = ("Thanks for your message! Our assistant is currently in basic mode. "
             "A team member will review your request and reply shortly. "
             "You can also browse availability through our team directly.")
    return {"reply": reply, "needs_human": True, "actions": []}
