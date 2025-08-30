import os, hmac, hashlib, json
from flask import Flask, request, abort, jsonify
import string

DEBUG_SIG = os.environ.get("DEBUG_SIG", "0") == "1"  # pon DEBUG_SIG=1 en Heroku si quieres ver all
ALLOWED_OWNERS = {s.strip() for s in os.environ.get("ALLOWED_OWNERS", "").split(",") if s.strip()}

# OJO: strip() para evitar \n o espacios
GH_WEBHOOK_SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").strip().encode()

app = Flask(__name__)

# --- helpers de depuración (sin uso si DEBUG_SIG=0) ---
def _debug_log_headers():
    if not DEBUG_SIG:
        return
    print("[hdr] delivery=", request.headers.get("X-GitHub-Delivery"),
          "hook_id=", request.headers.get("X-GitHub-Hook-ID"),
          "target_type=", request.headers.get("X-GitHub-Hook-Installation-Target-Type"),
          "event=", request.headers.get("X-GitHub-Event"),
          "ua=", request.headers.get("User-Agent"),
          "ct=", request.headers.get("Content-Type"))

def _debug_log_signatures(raw_body: bytes, signature_header: str):
    if not DEBUG_SIG:
        return
    try:
        _, recv = signature_header.split("=", 1)
    except ValueError:
        recv = "<invalid>"
    secret_str = os.environ.get("GH_WEBHOOK_SECRET", "").strip()
    codepoints = [f"U+{ord(ch):04X}" for ch in secret_str]
    print(f"[dbg] secret_len={len(secret_str)} codepoints={codepoints}")
    comp = hmac.new(secret_str.encode(), raw_body, hashlib.sha256).hexdigest()
    print(f"[sig] header=sha256={recv}")
    print(f"[sig] computed=sha256={comp}")

def verify_signature(raw_body: bytes, signature_header: str):
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
    computed = hmac.new(GH_WEBHOOK_SECRET, msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_sig, computed):
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

    sig256 = request.headers.get("X-Hub-Signature-256")
    if not sig256:
        if request.headers.get("X-Hub-Signature"):
            print("[warn] Llegó X-Hub-Signature (sha1) en vez de X-Hub-Signature-256")
        abort(401, "Falta X-Hub-Signature-256")

    _debug_log_headers()
    _debug_log_signatures(raw, sig256)  # no imprime nada si DEBUG_SIG=0

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
    # Para correr local (en prod Heroku usa gunicorn del Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
