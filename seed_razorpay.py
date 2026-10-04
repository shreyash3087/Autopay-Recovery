import os, sys
import httpx
from dotenv import load_dotenv
import db

load_dotenv()
AUTH = (os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"])
API = "https://api.razorpay.com/v1"

ids = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
with db.conn() as c:
    rows = {r["id"]: dict(r) for r in c.execute("select * from customers")}

for cid in ids:
    cust = rows[cid]
    plan = httpx.post(f"{API}/plans", auth=AUTH, timeout=30, json={
        "period": "monthly", "interval": 1,
        "item": {"name": cust["plan"], "amount": cust["amount"] * 100, "currency": "INR"},
    })
    if plan.status_code >= 300:
        sys.exit(f"Plan error for #{cid}: {plan.text}")
    sub = httpx.post(f"{API}/subscriptions", auth=AUTH, timeout=30, json={
        "plan_id": plan.json()["id"], "total_count": 12, "quantity": 1, "customer_notify": 0,
        "notes": {"customer_id": str(cid), "customer_name": cust["name"]},
    })
    if sub.status_code >= 300:
        sys.exit(f"Subscription error for #{cid}: {sub.text}")
    j = sub.json()
    print(f"#{cid} {cust['name']}: {j['id']}\n   authenticate here: {j['short_url']}")
