# services/github/github_events.py
from __future__ import annotations

from typing import Optional, Set
from .github_utils import extract_owner_repo

__all__ = ["handle_github_event"]


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
    """
    Evento: pull_request
    Minimal: solo extrae datos; aquí podrás enchufar lógica luego.
    """
    repo = payload.get("repository", {}) or {}
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    pr = payload.get("pull_request", {}) or {}
    number = pr.get("number") or payload.get("number")
    action = payload.get("action")
    _ = (owner, name, number, action)  # no-op
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

    # eventos no manejados aquí
    return False
