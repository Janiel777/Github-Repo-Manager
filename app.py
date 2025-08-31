from flask import Flask, request, abort, jsonify
import os, json

from services.github.github_auth import (
    verify_signature,
    debug_log_headers,
    debug_log_signatures,
)
from services.github.github_utils import extract_owner_repo

ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}

app = Flask(__name__)

@app.get("/")
def home():
    return "GitHub App running ✅"

@app.post("/webhook")
def webhook():
    raw = request.get_data()

    sig256 = request.headers.get("X-Hub-Signature-256")
    if not sig256:
        if request.headers.get("X-Hub-Signature"):
            print("[warn] Llegó X-Hub-Signature (sha1) en vez de X-Hub-Signature-256")
        abort(401, "Falta X-Hub-Signature-256")

    # Debug opcional
    debug_log_headers()
    debug_log_signatures(raw, sig256)

    # Verificación real
    verify_signature(raw, sig256)

    event = request.headers.get("X-GitHub-Event", "unknown")
    if event == "ping":
        return jsonify({"msg": "pong"}), 200

    payload = request.get_json(silent=True) or json.loads(raw.decode("utf-8"))
    owner, repo = extract_owner_repo(payload)
    if ALLOWED_OWNERS and owner not in ALLOWED_OWNERS:
        return ("", 204)

    print(f"[webhook] {event} from {owner}/{repo}")
    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
