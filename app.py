from flask import Flask, request, abort, jsonify
import os, json

from services.github.github_auth import (
    verify_signature,
    debug_log_headers,
    debug_log_signatures,
)
from services.github.github_utils import extract_owner_repo
from services.github.github_events import handle_github_event

ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}

app = Flask(__name__)

@app.get("/")
def home():
    return "GitHub App running ✅"

@app.post("/webhook")
def webhook():
    raw = request.get_data()
    sig256 = request.headers.get("X-Hub-Signature-256")
    # (verificación de firma, ping, etc. igual que ya tienes)

    event = request.headers.get("X-GitHub-Event", "unknown")
    if event == "ping":
        return jsonify({"msg": "pong"}), 200

    payload = request.get_json(silent=True) or json.loads(raw.decode("utf-8"))

    # 🔹 Despacha a la función padre (retorna True si lo manejó)
    if handle_github_event(event, payload, ALLOWED_OWNERS):
        return jsonify({"ok": True}), 200

    # Si no lo manejó, sigue tu lógica genérica
    owner, repo = extract_owner_repo(payload)
    if ALLOWED_OWNERS and owner not in ALLOWED_OWNERS:
        return ("", 204)

    print(f"[webhook] {event} from {owner}/{repo}")
    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
