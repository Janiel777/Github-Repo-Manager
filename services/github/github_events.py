# services/github/github_events.py
from __future__ import annotations

import re
import threading
from typing import Optional, Set

import requests

from .github_utils import extract_owner_repo
from .github_actions import post_comment, update_comment, fetch_pr_files, fetch_pr_commits
from .github_auth import get_installation_token
from services.openai.planner import build_review_messages, make_price_table, render_budget_comment
from services.openai.requests import review_pull_request


__all__ = ["handle_github_event"]

API = "https://api.github.com"

def _fetch(token: str, url: str):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=h, timeout=25)
    r.raise_for_status()
    return r.json()

def _run_review_job(
    installation_id: int,
    owner: str, repo: str, pr_number: int,
    model: str, opts: dict, placeholder_id: int
) -> None:
    """Corre en background: carga contexto, llama OpenAI y actualiza el comentario."""
    try:
        token = get_installation_token(installation_id)
        files   = fetch_pr_files(owner, repo, pr_number, token)
        commits = fetch_pr_commits(owner, repo, pr_number, token)

        review_md = review_pull_request(model, owner, repo, pr_number, files, commits, opts)
        if not review_md or not review_md.strip():
            review_md = "⚠️ La revisión no produjo contenido."

        update_comment(owner, repo, placeholder_id, token, body_md=f"**Revisión ({model})**\n\n{review_md}")
    except Exception as e:
        # Nunca dejes al usuario con un placeholder vacío
        try:
            token = token if 'token' in locals() else get_installation_token(installation_id)
            update_comment(
                owner, repo, placeholder_id, token,
                body_md=f"**Error ejecutando la revisión:** `{e}`"
            )
        except Exception:
            pass


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
    Evento: issue_comment.created/edited
    Comandos soportados (en comentarios de PR):
      /bot review gpt-5
      /bot review gpt-5-mini
      /bot review gpt-4o-mini  max:1200 temp:0.7
    """
    action = payload.get("action")
    if action not in ("created", "edited"):
        return True

    comment = payload.get("comment", {}) or {}
    body = (comment.get("body") or "").strip()
    if not body.startswith("/bot"):
        return True

    issue = payload.get("issue", {}) or {}

    # Solo aceptamos en PRs (issue->pull_request presente)
    if "pull_request" not in issue:
        owner, repo = extract_owner_repo(payload)
        if owner and repo:
            # Intento de comentar en issue normal o discussion: informamos
            installation_id = payload.get("installation", {}).get("id")
            if installation_id:
                token = get_installation_token(installation_id)
                post_comment(owner, repo, issue.get("number"), token,
                             "Este comando solo funciona en *Pull Requests*.")
        return True

    # Parseo del comando
    # /bot review <modelo> [max:<n>] [temp:<x>]
    parts = body.split()
    if len(parts) < 3 or parts[1] != "review":
        return True

    model = parts[2].strip()
    opts: dict = {}
    for p in parts[3:]:
        if p.startswith("max:"):
            try:
                opts["max_output_tokens"] = int(p.split(":", 1)[1])
            except Exception:
                pass
        elif p.startswith("temp:"):
            try:
                opts["temperature"] = float(p.split(":", 1)[1])
            except Exception:
                pass

    repo_node = payload.get("repository", {}) or {}
    owner = (repo_node.get("owner") or {}).get("login")
    repo = repo_node.get("name")
    pr_number = issue.get("number")
    installation_id = payload.get("installation", {}).get("id")

    token = get_installation_token(installation_id)
    placeholder_id = post_comment(
        owner, repo, pr_number, token,
        body_md=f"🔄 Ejecutando revisión con **{model}**...\n\n*(esto puede tardar unos segundos)*"
    )

    # 🔸 Lanza la revisión en background y responde YA al webhook
    threading.Thread(
        target=_run_review_job,
        args=(installation_id, owner, repo, pr_number, model, opts, placeholder_id),
        daemon=True
    ).start()

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
