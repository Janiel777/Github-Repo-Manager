# app.py
import os
import time

from flask import Flask, request, jsonify
from services.github.github_auth import verify_signature
from services.github.github_events import handle_github_event

# (opcional) filtra por owners permitidos: "UserA,OrgB"
ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}
PROCESSED: dict[str, float] = {}  # id -> timestamp

app = Flask(__name__)

@app.get("/")
def home():
    return "GitHub App running ✅"

@app.post("/webhook")@app.post("/webhook")
def webhook():
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if delivery_id and delivery_id in PROCESSED:
        return jsonify({"ok": True, "dup": True}), 200
    if delivery_id:
        PROCESSED[delivery_id] = time.time()

    raw = request.get_data()
    verify_signature(raw, request.headers.get("X-Hub-Signature-256", ""))

    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = request.json or {}

    handled = handle_github_event(event, payload, ALLOWED_OWNERS or None)
    return jsonify({"ok": True, "event": event, "handled": bool(handled)}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
