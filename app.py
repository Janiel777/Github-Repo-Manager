import os, hmac, hashlib, json
from flask import Flask, request, abort, jsonify

ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}
# ej: ALLOWED_OWNERS="Janiel777,mi-organizacion"

# Variables de entorno (pon GH_WEBHOOK_SECRET en Heroku)
GH_WEBHOOK_SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").encode()

app = Flask(__name__)

def verify_signature(raw_body: bytes, signature_header: str):
    """Valida la firma HMAC del webhook (X-Hub-Signature-256)."""
    if not GH_WEBHOOK_SECRET:
        abort(500, "Falta GH_WEBHOOK_SECRET en variables de entorno")
    if not signature_header:
        abort(401, "Falta X-Hub-Signature-256")
    mac = hmac.new(GH_WEBHOOK_SECRET, msg=raw_body, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        abort(401, "Firma inválida")

def extract_owner_repo(payload):
    owner = None; repo = None
    if payload.get("repository"):
        owner = payload["repository"]["owner"]["login"]
        repo  = payload["repository"]["name"]
    elif payload.get("organization"):
        owner = payload["organization"]["login"]
    elif payload.get("installation", {}).get("account"):
        owner = payload["installation"]["account"]["login"]
    return owner, repo

@app.get("/")
def home():
    return "GitHub App running ✅"

@app.post("/webhook")
def webhook():
    raw = request.get_data()
    verify_signature(raw, request.headers.get("X-Hub-Signature-256",""))
    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = request.get_json(silent=True) or json.loads(raw.decode("utf-8"))

    if event == "ping":
        return jsonify({"msg": "pong"}), 200

    owner, repo = extract_owner_repo(payload)
    if ALLOWED_OWNERS and owner not in ALLOWED_OWNERS:
        # Silenciosamente ignoramos eventos de cuentas no permitidas
        return ("", 204)

    # ... aquí tu lógica real para eventos permitidos ...
    print(f"[webhook] {event} from {owner}/{repo}")
    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    # Para correr local (en prod Heroku usa gunicorn del Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
