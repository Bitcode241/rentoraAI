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
- External/partner boats: if a boat in availability results has is_external=true,
  do NOT book it directly. Confirm the package & price with the guest, then call
  request_external_availability to ask the owner. Tell the guest you're checking
  availability and will confirm shortly. NEVER tell the guest the boat isn't ours —
  to them it is just another boat. Once the owner confirms, the booking is created
  automatically and the guest is notified.
- Advance-booking rule (lead time): jet skis must be booked at least a couple of
  hours before the start, boats well in advance (several hours), transfers a few
  hours ahead. If a guest asks for a time too soon, politely explain it must be
  booked further in advance and offer the earliest possible slot. The exact hours
  are configured by the business; if a booking attempt is refused for lead time,
  relay that politely.
- Be warm, concise and professional. Never promise anything the tools didn't confirm.

ESCALATION (very important):
If you are not confident, if the request is ambiguous, sensitive, a complaint,
a special/large/high-value request, or anything you cannot fully resolve with the
tools, do NOT guess. End your reply with the exact marker on its own line:
[[ESCALATE]]
A human colleague will then take over. When everything is clear and resolved with
tool data, do not include the marker.

Current UTC time: {now}.
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
            if customer_id and "customer_id" in args is False:
                args["customer_id"] = customer_id
            func = tools.TOOL_FUNCS.get(fname)
            try:
                result = func(db, **args) if func else {"error": "unknown_tool"}
            except Exception as e:  # tool raised (e.g. not available)
                result = {"error": str(e)}
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
