import asyncio, hashlib, hmac, json, os, uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from app import db

load_dotenv()
VAPI_KEY    = os.getenv("VAPI_PRIVATE_KEY", "")
ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")
PHONE_ID    = os.getenv("VAPI_PHONE_NUMBER_ID", "")
SECRET      = os.getenv("WEBHOOK_SECRET", "change-me")
PUBLIC_URL  = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
DEMO_MODE   = os.getenv("DEMO_MODE", "1") == "1"
RZP_ID      = os.getenv("RAZORPAY_KEY_ID", "")
RZP_SECRET  = os.getenv("RAZORPAY_KEY_SECRET", "")

MAX_ATTEMPTS = 3
IST          = ZoneInfo("Asia/Kolkata")
NO_ANSWER    = {"customer-did-not-answer", "customer-busy", "voicemail"}

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR   = os.path.join(ROOT, "static")
MAILER       = os.path.join(ROOT, "scripts", "mailer.js")

app = FastAPI()
db.init()
verified, tries, calls = {}, {}, {}


def get(cid):
    with db.conn() as c:
        r = c.execute("select * from customers where id=?", (cid,)).fetchone()
    return dict(r) if r else None


def all_customers():
    with db.conn() as c:
        return [dict(r) for r in c.execute("select * from customers order by id")]


def update(cid, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.conn() as c:
        c.execute(f"update customers set {sets} where id=?", (*fields.values(), cid))


def call_allowed(cust):
    if cust["dnc"]:
        return "Customer asked not to be called"
    if cust["status"] in ("recovered", "calling"):
        return f"Status is {cust['status']}"
    if cust["attempts"] >= MAX_ATTEMPTS:
        return "Max attempts reached"
    if not DEMO_MODE and not (9 <= datetime.now(IST).hour < 20):
        return "Outside calling hours (9am to 8pm IST)"
    return None


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/customers")
def customers():
    return all_customers()


@app.post("/api/call/{cid}")
async def place_call(cid: int):
    cust = get(cid)
    if not cust:
        raise HTTPException(404, "Unknown customer")
    why = call_allowed(cust)
    if why:
        raise HTTPException(400, why)
    body = {
        "assistantId": ASSISTANT_ID,
        "phoneNumberId": PHONE_ID,
        "customer": {"number": cust["phone"], "name": cust["name"]},
        "assistantOverrides": {
            "variableValues": {"customer_id": str(cid), "first_name": cust["name"].split()[0]}
        },
    }
    async with httpx.AsyncClient(timeout=30) as h:
        r = await h.post("https://api.vapi.ai/call", json=body, headers={"Authorization": f"Bearer {VAPI_KEY}"})
    if r.status_code >= 300:
        raise HTTPException(502, f"Vapi error: {r.text[:300]}")
    calls[r.json().get("id")] = cid
    verified[cid], tries[cid] = False, 0
    update(cid, status="calling", attempts=cust["attempts"] + 1, notes="Call placed")
    return {"ok": True}


@app.post("/api/retry")
async def retry():
    done = []
    for c in all_customers():
        if c["status"] == "no_answer" and call_allowed(c) is None:
            try:
                await place_call(c["id"])
                done.append(c["id"])
            except HTTPException:
                pass
    return {"retried": done}


@app.post("/api/reset")
def reset():
    db.init(reset=True)
    with db.conn() as c:
        c.execute("update customers set status='active', attempts=0, promised_date='', notes='', pay_link='', dnc=0")
    verified.clear(), tries.clear(), calls.clear()
    return {"ok": True}


@app.post("/vapi/webhook")
async def vapi_webhook(req: Request):
    if req.headers.get("x-vapi-secret") != SECRET:
        raise HTTPException(401, "Bad secret")
    msg = (await req.json()).get("message", {})
    kind = msg.get("type")
    if kind == "tool-calls":
        results = []
        for tc in msg.get("toolCallList") or msg.get("toolCalls") or []:
            fn   = tc.get("function", {})
            name = tc.get("name") or fn.get("name")
            args = tc.get("arguments") or fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            try:
                out = await run_tool(name, args)
            except Exception as e:
                out = {"error": str(e)}
            results.append({"toolCallId": tc.get("id"), "result": json.dumps(out)})
        return {"results": results}
    if kind == "end-of-call-report":
        finish_call(msg)
    return {"ok": True}


async def run_tool(name, a):
    cid  = int(a.get("customer_id") or 0)
    cust = get(cid)
    if not cust:
        return {"error": "unknown customer"}

    if name == "verify_identity":
        if tries.get(cid, 0) >= 2:
            return {"verified": False, "locked": True}
        if "".join(ch for ch in str(a.get("postal_code", "")) if ch.isdigit()) == cust["postal"]:
            verified[cid] = True
            return {"verified": True}
        tries[cid] = tries.get(cid, 0) + 1
        if tries[cid] >= 2:
            update(cid, status="verification_failed", notes="Failed identity check twice")
        return {"verified": False, "locked": tries[cid] >= 2}

    if name in ("get_payment_details", "send_payment_link") and not verified.get(cid):
        return {"error": "customer not verified"}

    if name == "get_payment_details":
        return {"amount_inr": cust["amount"], "plan": cust["plan"],
                "failure_reason": cust["reason"], "due_date": cust["due"]}

    if name == "send_payment_link":
        link = await make_link(cust)
        update(cid, pay_link=link, status="link_sent", notes="Payment link sent to email")
        return {"sent": True, "channel": "email"}

    if name == "log_outcome":
        if cust["status"] == "recovered":
            return {"logged": True}
        o = a.get("outcome", "")
        f = {"notes": str(a.get("notes", ""))[:300]}
        if o == "promised_date":
            f.update(status="promised", promised_date=str(a.get("promised_date", "")))
        elif o == "disputed":
            f.update(status="disputed")
        elif o == "do_not_call":
            f.update(status="do_not_call", dnc=1)
        elif o == "link_sent":
            f.update(status="link_sent")
        else:
            f.update(status="no_resolution")
        update(cid, **f)
        return {"logged": True}

    if name == "escalate_to_human":
        update(cid, status="escalated", notes="Human needed: " + str(a.get("reason", ""))[:200])
        return {"escalated": True}

    return {"error": "unknown tool"}


def finish_call(msg):
    call = msg.get("call", {})
    cid  = calls.get(call.get("id"))
    if cid is None:
        v   = (call.get("assistantOverrides") or {}).get("variableValues") or {}
        cid = int(v["customer_id"]) if v.get("customer_id") else None
    if cid is None:
        return
    cust   = get(cid)
    reason = msg.get("endedReason", "")
    if cust["status"] == "calling":
        update(cid, status="no_answer" if reason in NO_ANSWER else "no_resolution", notes=f"Call ended: {reason}")
    summary = (msg.get("analysis") or {}).get("summary") or msg.get("summary")
    if summary:
        update(cid, notes=summary[:300])


async def make_link(cust):
    link  = f"{PUBLIC_URL}/pay/{cust['id']}"
    email = cust.get("email") or os.getenv("DEMO_EMAIL", "")
    if RZP_ID and RZP_SECRET:
        body = {
            "amount": cust["amount"] * 100, "currency": "INR",
            "reference_id": f"autopay-{cust['id']}-{uuid.uuid4().hex[:6]}",
            "description": f"{cust['plan']} autopay recovery",
            "customer": {"name": cust["name"], "contact": cust["phone"], "email": email},
            "notify": {"sms": False, "email": True},
        }
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.post("https://api.razorpay.com/v1/payment_links", json=body, auth=(RZP_ID, RZP_SECRET))
        if r.status_code < 300:
            link = r.json()["short_url"]
    await send_email(email, cust["name"], cust["plan"], cust["amount"], link)
    return link


async def send_email(to_email, name, plan, amount, link):
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", MAILER, str(to_email), str(name), str(plan), str(amount), str(link),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ROOT,
        )
        stdout, _ = await proc.communicate()
        if stdout:
            print(f"[Email] {stdout.decode().strip()}")
    except Exception as e:
        print(f"[Email Error] {e}")


@app.get("/pay/{cid}", response_class=HTMLResponse)
def pay_page(cid: int):
    c = get(cid)
    if not c:
        raise HTTPException(404)
    return f"""<meta name="viewport" content="width=device-width,initial-scale=1">
<body style="font-family:sans-serif;max-width:420px;margin:40px auto;padding:0 16px">
<h2>PayEase</h2><p>Hi {c['name']}, your {c['plan']} payment of Rs {c['amount']} is pending.</p>
<form method="post" action="/pay/{cid}"><button style="padding:12px 20px;font-size:16px">Pay Rs {c['amount']} (demo)</button></form></body>"""


@app.post("/pay/{cid}", response_class=HTMLResponse)
def pay_confirm(cid: int):
    update(cid, status="recovered", notes="Paid via payment link")
    return "<meta name='viewport' content='width=device-width,initial-scale=1'><h3 style='font-family:sans-serif;padding:24px'>Payment received. Thank you.</h3>"


async def auto_call(cid):
    update(cid, status="payment_failed", notes="Razorpay reported a failed autopay charge")
    try:
        await place_call(cid)
    except HTTPException as e:
        update(cid, notes=f"Auto call skipped: {e.detail}")


@app.post("/razorpay/webhook")
async def rzp_webhook(req: Request):
    raw    = await req.body()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if secret:
        good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, req.headers.get("x-razorpay-signature", "")):
            raise HTTPException(401, "Bad signature")
    data    = json.loads(raw)
    event   = data.get("event", "")
    payload = data.get("payload", {})

    if event == "payment_link.paid":
        ref = (payload.get("payment_link", {}).get("entity") or {}).get("reference_id", "")
        if ref.startswith("autopay-"):
            update(int(ref.split("-")[1]), status="recovered", notes="Paid via Razorpay link")

    sub   = (payload.get("subscription") or {}).get("entity") or {}
    notes = sub.get("notes") if isinstance(sub.get("notes"), dict) else {}
    cid   = int(notes.get("customer_id") or 0)
    if cid and get(cid):
        if event in ("subscription.pending", "subscription.halted"):
            asyncio.create_task(auto_call(cid))
        elif event == "subscription.charged":
            update(cid, status="active", notes="Autopay charge succeeded")
    return {"ok": True}
