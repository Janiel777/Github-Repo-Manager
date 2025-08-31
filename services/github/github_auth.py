# services/github/github_auth.py
import os, time, base64, hmac, hashlib
import requests, jwt
from flask import abort, request

# Debug opcional (habilita con DEBUG_SIG=1 en tus vars de entorno)
DEBUG_SIG = os.environ.get("DEBUG_SIG", "0") == "1"

# Webhook secret para validar firmas de GitHub (HMAC-SHA256)
_GH_WEBHOOK_SECRET_STR = os.environ.get("GH_WEBHOOK_SECRET", "").strip()
_GH_WEBHOOK_SECRET = _GH_WEBHOOK_SECRET_STR.encode()

# Credenciales de la App para autenticarte ante GitHub (JWT → installation token)
_GH_APP_ID = os.environ.get("GH_APP_ID")  # p.ej. "123456"
_PK_PEM = os.environ.get("GH_PRIVATE_KEY_PEM")
_PK_B64 = os.environ.get("GH_PRIVATE_KEY_B64")

# Cache simple por instalación: {installation_id: {"token": str, "exp_epoch": int}}
_token_cache: dict[int, dict] = {}

# ----------------------------
# Debug helpers (opcionales)
# ----------------------------
def debug_log_headers():
    """Imprime encabezados útiles del webhook (solo si DEBUG_SIG=1)."""
    if not DEBUG_SIG:
        return
    print(
        "[hdr] delivery=", request.headers.get("X-GitHub-Delivery"),
        "hook_id=", request.headers.get("X-GitHub-Hook-ID"),
        "target_type=", request.headers.get("X-GitHub-Hook-Installation-Target-Type"),
        "event=", request.headers.get("X-GitHub-Event"),
        "ua=", request.headers.get("User-Agent"),
        "ct=", request.headers.get("Content-Type")
    )

def debug_log_signatures(raw_body: bytes, signature_header: str):
    """Imprime firma recibida vs calculada (solo si DEBUG_SIG=1)."""
    if not DEBUG_SIG:
        return
    try:
        _, recv = signature_header.split("=", 1)
    except ValueError:
        recv = "<invalid>"
    codepoints = [f"U+{ord(ch):04X}" for ch in _GH_WEBHOOK_SECRET_STR]
    comp = hmac.new(_GH_WEBHOOK_SECRET, raw_body, hashlib.sha256).hexdigest()
    print(f"[dbg] secret_len={len(_GH_WEBHOOK_SECRET_STR)} codepoints={codepoints}")
    print(f"[sig] header=sha256={recv}")
    print(f"[sig] computed=sha256={comp}")

# ----------------------------
# Verificación de firma
# ----------------------------
def verify_signature(raw_body: bytes, signature_header: str):
    """Valida 'X-Hub-Signature-256: sha256=<hexdigest>' y corta con 401 si no cuadra."""
    if not _GH_WEBHOOK_SECRET:
        abort(500, "Falta GH_WEBHOOK_SECRET en variables de entorno")
    if not signature_header:
        abort(401, "Falta X-Hub-Signature-256")
    try:
        scheme, received_sig = signature_header.split("=", 1)
    except ValueError:
        abort(401, "Formato de firma inválido")
    if scheme.lower() != "sha256":
        abort(401, "Esquema de firma no soportado (se esperaba sha256)")
    computed = hmac.new(_GH_WEBHOOK_SECRET, msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_sig, computed):
        abort(401, "Firma inválida")

# ----------------------------
# JWT de App y token de instalación
# ----------------------------
def _load_private_key() -> str:
    if _PK_PEM:
        return _PK_PEM
    if _PK_B64:
        return base64.b64decode(_PK_B64).decode("utf-8")
    abort(500, "Falta GH_PRIVATE_KEY_PEM o GH_PRIVATE_KEY_B64")

def _make_app_jwt() -> str:
    if not _GH_APP_ID:
        abort(500, "Falta GH_APP_ID")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": _GH_APP_ID}
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")

def get_installation_token(installation_id: int) -> str:
    """Devuelve un installation token válido (cacheado hasta su expiración)."""
    from datetime import datetime, timezone
    entry = _token_cache.get(installation_id)
    if entry and time.time() < entry["exp_epoch"] - 60:
        return entry["token"]

    headers = {"Authorization": f"Bearer {_make_app_jwt()}",
               "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    resp = requests.post(url, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    token = data["token"]
    # expires_at: ISO8601 → epoch
    exp_epoch = int(datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp())
    _token_cache[installation_id] = {"token": token, "exp_epoch": exp_epoch}
    return token
