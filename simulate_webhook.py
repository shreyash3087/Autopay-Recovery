import hashlib, hmac, json, sys, httpx, os
from dotenv import load_dotenv

load_dotenv(override=True)
SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "autopay123")
URL = "http://localhost:8000/razorpay/webhook"

cid = int(sys.argv[1]) if len(sys.argv) > 1 else 1

payload = {
    "event": "subscription.pending",
    "payload": {
        "subscription": {
            "entity": {
                "id": f"sub_simulated_{cid}",
                "plan_id": f"plan_simulated_{cid}",
                "status": "pending",
                "notes": {
                    "customer_id": str(cid),
                    "customer_name": f"Customer {cid}"
                }
            }
        }
    }
}

body = json.dumps(payload, separators=(",", ":")).encode()
sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

print(f"Sending subscription.pending for customer #{cid} to {URL}")
r = httpx.post(URL, content=body, headers={
    "Content-Type": "application/json",
    "x-razorpay-signature": sig
}, timeout=15)
print(f"Status: {r.status_code}")
print(f"Response: {r.text}")
