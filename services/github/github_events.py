# services/github/github_events.py
from __future__ import annotations

import re
from typing import Optional, Set

import requests

from .github_utils import extract_owner_repo
from .github_actions import post_issue_comment
from .github_auth import get_installation_token
from services.openai.planner import build_review_messages, make_price_table, render_budget_comment
from services.openai.requests import run_review
from services.openai.models import MODELS

__all__ = ["handle_github_event"]

API = "https://api.github.com"

def _fetch(token: str, url: str):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=h, timeout=25)
    r.raise_for_status()
    return r.json()


# -----------------------------
# Handlers por evento (mínimos)
# -----------------------------
def _handle_installation_created(payload: dict) -> bool:
    """
    Evento: installation.created
    Se instaló la App y GitHub envía los repos iniciales.
    """
    installation = payload.get("installation", {}) or {}
    account_login = (installation.get("account") or {}).get("login")

    repos = payload.get("repositories", []) or []
    if not repos:
        return True

    for info in repos:
        full = (info.get("full_name") or "").strip()
        if "/" in full:
            owner, repo = full.split("/", 1)
        else:
            owner, repo = account_login, info.get("name")
        # Punto de extensión futuro para inicializar por repo
        _ = (owner, repo)  # no-op
    return True


def _handle_installation_repositories_added(payload: dict) -> bool:
    """
    Evento: installation_repositories.added
    Se añadieron repos a una instalación existente.
    """
    installation = payload.get("installation", {}) or {}
    account_login = (installation.get("account") or {}).get("login")

    repos = payload.get("repositories_added", []) or []
    if not repos:
        return True

    for info in repos:
        full = (info.get("full_name") or "").strip()
        if "/" in full:
            owner, repo = full.split("/", 1)
        else:
            owner, repo = account_login, info.get("name")
        # Punto de extensión futuro para bootstrap del repo añadido
        _ = (owner, repo)  # no-op
    return True


def _handle_pull_request(payload: dict) -> bool:
    repo = payload.get("repository", {}) or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    pr = payload.get("pull_request", {}) or {}
    number = pr.get("number") or payload.get("number")
    installation_id = (payload.get("installation") or {}).get("id")
    action = payload.get("action")

    if action not in ("opened", "synchronize", "ready_for_review"):
        return True

    token = get_installation_token(installation_id)
    files   = _fetch(token, f"{API}/repos/{owner}/{name}/pulls/{number}/files")
    commits = _fetch(token, f"{API}/repos/{owner}/{name}/pulls/{number}/commits")

    messages = build_review_messages(pr.get("title",""), pr.get("body",""), files, commits)
    tokens_in, prices = make_price_table(messages, max_out=1200, cached_ratio=0.0)
    body = render_budget_comment(tokens_in, prices)
    post_issue_comment(owner, name, number, token, body)
    return True


_CMD_REVIEW = re.compile(
    r"^/bot\s+review\s+([A-Za-z0-9\-\.]+)(?:\s+max:(\d+))?(?:\s+temp:([0-9]*\.?[0-9]+))?\s*$",
    re.IGNORECASE
)

def _handle_issue_comment(payload: dict) -> bool:
    issue = payload.get("issue") or {}
    # Sólo atendemos comentarios en PRs
    if not issue.get("pull_request"):
        return True

    if payload.get("action") != "created":
        return True

    comment = payload.get("comment") or {}
    text = (comment.get("body") or "").strip()
    if not text.lower().startswith("/bot"):
        return True

    repo = payload.get("repository") or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    number = issue.get("number")
    installation_id = (payload.get("installation") or {}).get("id")
    token = get_installation_token(installation_id)

    # Ayuda / modelos
    if text.lower().startswith("/bot models") or text.lower().startswith("/bot help"):
        models_txt = ", ".join(sorted({v['id'] for v in MODELS.values()}))
        post_issue_comment(owner, name, number, token,
                           f"Modelos disponibles: `{models_txt}`\n\nEjemplo: `/bot review gpt-5-mini max:1500`")
        return True

    m = _CMD_REVIEW.match(text)
    if not m:
        post_issue_comment(owner, name, number, token,
                           "Comando no reconocido. Usa `/bot review <modelo> [max:N] [temp:X]` "
                           "o `/bot models` para ver opciones.")
        return True

    model_id = m.group(1)
    max_out  = int(m.group(2)) if m.group(2) else None
    temp_str = m.group(3)
    temperature = float(temp_str) if temp_str else None

    # Reconstruir contexto del PR
    pr      = _fetch(token, f"{API}/repos/{owner}/{name}/pulls/{number}")
    files   = _fetch(token, f"{API}/repos/{owner}/{name}/pulls/{number}/files")
    commits = _fetch(token, f"{API}/repos/{owner}/{name}/pulls/{number}/commits")
    messages = build_review_messages(pr.get("title",""), pr.get("body",""), files, commits)

    try:
        review_md = run_review(messages, model_id=model_id, max_out=max_out, temperature=temperature)
    except Exception as e:
        post_issue_comment(owner, name, number, token, f"❌ Error ejecutando el análisis: `{e}`")
        return True

    post_issue_comment(owner, name, number, token, f"### 🤖 Revisión ({model_id})\n\n{review_md}")
    return True

# -----------------------------
# Dispatcher (función PADRE)
# -----------------------------
def handle_github_event(event: str, payload: dict, allowed_owners: Optional[Set[str]] = None) -> bool:
    """
    Devuelve True si el evento fue manejado aquí; False si el caller debe hacer otra cosa.
    Aplica el filtro de owners UNA sola vez, usando extract_owner_repo(...).
    """
    owner, _ = extract_owner_repo(payload)  # (owner, repo o None)
    if allowed_owners and (not owner or owner not in allowed_owners):
        return True  # ignorado silenciosamente

    action = payload.get("action")

    if event == "installation" and action == "created":
        return _handle_installation_created(payload)

    if event == "installation_repositories" and action == "added":
        return _handle_installation_repositories_added(payload)

    if event == "pull_request":
        return _handle_pull_request(payload)

    if event == "issue_comment":
        return _handle_issue_comment(payload)

    # eventos no manejados aquí
    return False
