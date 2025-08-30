import os, hmac, hashlib, json
from flask import Flask, request, abort, jsonify

DEBUG_SIG = os.environ.get("DEBUG_SIG", "0") == "1"  # pon DEBUG_SIG=1 en Heroku si quieres ver all
ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}
# ej: ALLOWED_OWNERS="Janiel777,mi-organizacion"

# Variables de entorno (pon GH_WEBHOOK_SECRET en Heroku)
GH_WEBHOOK_SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").encode()

app = Flask(__name__)

def verify_signature(raw_body: bytes, signature_header: str):
    """
    Valida la firma HMAC del webhook (X-Hub-Signature-256).
    Espera formato: 'sha256=<hexdigest>'
    """
    if not GH_WEBHOOK_SECRET:
        abort(500, "Falta GH_WEBHOOK_SECRET en variables de entorno")
    if not signature_header:
        abort(401, "Falta X-Hub-Signature-256")

    try:
        scheme, received_sig = signature_header.split("=", 1)
    except ValueError:
        abort(401, "Formato de firma inválido")

    if scheme.lower() != "sha256":
        abort(401, "Esquema de firma no soportado (se esperaba sha256)")

    computed_sig = hmac.new(GH_WEBHOOK_SECRET, msg=raw_body, digestmod=hashlib.sha256).hexdigest()

    # Logs de depuración (opcionales)
    if DEBUG_SIG:
        # Cabeceras útiles para cruzar en "Recent deliveries" de la App
        print("[hdr] delivery=", request.headers.get("X-GitHub-Delivery"),
              "event=", request.headers.get("X-GitHub-Event"),
              "ua=", request.headers.get("User-Agent"),
              "ct=", request.headers.get("Content-Type"),
              "len=", len(raw_body))
        # Muestra firmas completas (NO dejes esto siempre activo en prod)
        print(f"[sig] header=sha256={received_sig}")
        print(f"[sig] computed=sha256={computed_sig}")

    else:
        # Resumen seguro (solo prefijos) si no estás en debug
        print(f"[sig] recv={received_sig[:10]}… len={len(received_sig)}  comp={computed_sig[:10]}… len={len(computed_sig)}")

    if not hmac.compare_digest(received_sig, computed_sig):
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
    print("[hdr] delivery=", request.headers.get("X-GitHub-Delivery"),
          "hook_id=", request.headers.get("X-GitHub-Hook-ID"),
          "target_type=", request.headers.get("X-GitHub-Hook-Installation-Target-Type"),
          "event=", request.headers.get("X-GitHub-Event"))

    raw = request.get_data()

    # 🔧 2) si falta el header 256, corta con 401 claro
    sig256 = request.headers.get("X-Hub-Signature-256")
    if not sig256:
        # (Opcional) avisa si llegó el header viejo sha1 para diagnosticar:
        if request.headers.get("X-Hub-Signature"):
            print("[warn] Llegó X-Hub-Signature (sha1) en vez de X-Hub-Signature-256")
        abort(401, "Falta X-Hub-Signature-256")

    verify_signature(raw, sig256)

    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = request.get_json(silent=True) or json.loads(raw.decode("utf-8"))

    if event == "ping":
        return jsonify({"msg": "pong"}), 200

    owner, repo = extract_owner_repo(payload)
    if ALLOWED_OWNERS and owner not in ALLOWED_OWNERS:
        return ("", 204)

    print(f"[webhook] {event} from {owner}/{repo}")
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    # Para correr local (en prod Heroku usa gunicorn del Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
