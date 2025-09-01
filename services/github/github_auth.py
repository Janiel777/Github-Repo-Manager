# services/github/github_auth.py
import os, time, base64, hmac, hashlib
from datetime import datetime
import requests, jwt
from flask import abort

# Webhook secret (HMAC)
_GH_WEBHOOK_SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").strip().encode()

# Credenciales de la App
_GH_APP_ID = os.environ.get("GH_APP_ID")           # p.ej. "123456"
_PK_B64   = os.environ.get("GH_PRIVATE_KEY_B64")   # clave privada PEM en base64

# Cache simple: {installation_id: {"token": str, "exp_epoch": int}}
_token_cache: dict[int, dict] = {}


# ----------------------------
# Verificación de firma (webhook)
# ----------------------------
def verify_signature(raw_body: bytes, signature_header: str) -> None:
    if not _GH_WEBHOOK_SECRET:
        abort(500, "Falta GH_WEBHOOK_SECRET")
    if not signature_header:
        abort(401, "Falta X-Hub-Signature-256")
    try:
        scheme, received_sig = signature_header.split("=", 1)
    except ValueError:
        abort(401, "Formato de firma inválido")
    if scheme.lower() != "sha256":
        abort(401, "Esquema de firma no soportado (sha256)")
    computed = hmac.new(_GH_WEBHOOK_SECRET, msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_sig, computed):
        abort(401, "Firma inválida")


# ----------------------------
# JWT de App + token de instalación
# ----------------------------
def _load_private_key() -> str:
    if _PK_B64:
        return base64.b64decode(_PK_B64).decode("utf-8")
    abort(500, "Falta GH_PRIVATE_KEY_B64")

def _make_app_jwt() -> str:
    if not _GH_APP_ID:
        abort(500, "Falta GH_APP_ID")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": _GH_APP_ID}
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")

def get_installation_token(installation_id: int) -> str:
    entry = _token_cache.get(installation_id)
    if entry and time.time() < entry["exp_epoch"] - 60:
        return entry["token"]

    headers = {
        "Authorization": f"Bearer {_make_app_jwt()}",
        "Accept": "application/vnd.github+json",
    }
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    resp = requests.post(url, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    token = data["token"]
    exp_epoch = int(datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp())
    _token_cache[installation_id] = {"token": token, "exp_epoch": exp_epoch}
    return token
