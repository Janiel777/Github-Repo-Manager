# services/github/github_events.py
from __future__ import annotations

import re
from typing import Optional, Set

import requests

from .github_utils import extract_owner_repo
from .github_actions import post_comment, update_comment, fetch_pr_files, fetch_pr_commits
from .github_auth import get_installation_token
from services.openai.planner import build_review_messages, make_price_table, render_budget_comment
from services.openai.requests import review_pull_request
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
    post_comment(owner, name, number, token, body)
    return True


_CMD_REVIEW = re.compile(
    r"^/bot\s+review\s+([A-Za-z0-9\-\.]+)(?:\s+max:(\d+))?(?:\s+temp:([0-9]*\.?[0-9]+))?\s*$",
    re.IGNORECASE
)

def _parse_bot_command(body: str) -> tuple[str, list[str], dict]:
    """
    Devuelve (cmd, args, opts) para líneas tipo:
      /bot review gpt-5-mini max:1500 temp:0.8
    """
    body = (body or "").strip()
    if not body.startswith("/bot "):
        return "", [], {}
    parts = body.split()
    # /bot <cmd> [args...] [k:v ...]
    cmd = parts[1] if len(parts) > 1 else ""
    args = []
    opts = {}
    for token in parts[2:]:
        if ":" in token:
            k, v = token.split(":", 1)
            opts[k.strip().lower()] = v.strip()
        else:
            args.append(token.strip())
    return cmd.lower(), args, opts

def _handle_issue_comment(payload: dict) -> bool:
    """
    Ejecuta /bot review <modelo> solo en PRs. Corre la revisión inline
    y actualiza el comentario placeholder con el resultado o con el error.
    """
    action = payload.get("action")
    if action != "created":
        return True  # ignoramos edits/deletes

    issue = payload.get("issue") or {}
    # Solo si el "issue" es un PR (GitHub manda este campo cuando es PR)
    if not issue.get("pull_request"):
        return True  # comentario en issue normal: ignorar

    comment = payload.get("comment") or {}
    body = comment.get("body", "")
    cmd, args, opts = _parse_bot_command(body)

    # Aceptamos solo "/bot review <modelo>"
    if cmd != "review":
        return True  # otros comandos o nada => no-op

    model = (args[0] if args else "").strip()
    if not model:
        # Responder ayuda mínima
        owner, repo = extract_owner_repo(payload)
        installation_id = (payload.get("installation") or {}).get("id")
        token = get_installation_token(installation_id)
        post_comment(owner, repo, issue["number"], token,
                     "❌ Debes indicar el modelo. Ej: `/bot review gpt-5-mini`")
        return True

    # Contexto
    owner, repo = extract_owner_repo(payload)
    pr_number = issue["number"]
    installation_id = (payload.get("installation") or {}).get("id")
    token = get_installation_token(installation_id)

    # Placeholder
    placeholder_id = post_comment(
        owner, repo, pr_number, token,
        f"🧠 Ejecutando revisión con **{model}**…\n\n*(esto puede tardar unos segundos)*"
    )

    try:
        # Cargar contexto del PR
        files = fetch_pr_files(owner, repo, pr_number, token)
        commits = fetch_pr_commits(owner, repo, pr_number, token)

        # Ejecutar la revisión (tu función debe devolver Markdown)
        review_md = review_pull_request(model, owner, repo, pr_number, files, commits, opts)

        if not review_md or not review_md.strip():
            review_md = "⚠️ La revisión no produjo contenido."

        update_comment(owner, repo, placeholder_id, token, f"### Revisión ({model})\n\n{review_md}")
    except Exception as e:
        update_comment(owner, repo, placeholder_id, token, f"❌ Error ejecutando la revisión: `{e}`")

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
