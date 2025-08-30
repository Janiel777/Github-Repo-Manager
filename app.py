import os, hmac, hashlib, json
from flask import Flask, request, abort, jsonify

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

@app.get("/")
def home():
    return "GitHub App running ✅"

@app.post("/webhook")
def webhook():
    # 1) validar firma
    raw = request.get_data()
    signature = request.headers.get("X-Hub-Signature-256", "")
    verify_signature(raw, signature)

    # 2) leer evento y payload
    event = request.headers.get("X-GitHub-Event", "unknown")
    try:
        payload = request.get_json(silent=True) or json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}

    # 3) comportamiento mínimo
    if event == "ping":
        # GitHub envía ping al registrar/actualizar la App
        return jsonify({"msg": "pong"}), 200

    # Por ahora solo logueamos el nombre del evento
    print(f"[webhook] event={event} delivery={request.headers.get('X-GitHub-Delivery')}")

    return jsonify({"ok": True, "event": event}), 200

if __name__ == "__main__":
    # Para correr local (en prod Heroku usa gunicorn del Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
