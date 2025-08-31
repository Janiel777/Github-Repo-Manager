# services/github/github_events.py
from __future__ import annotations

import os
import logging
from typing import Iterable, Tuple, Optional, Set

from .github_actions import create_welcome_discussion

__all__ = ["handle_github_event"]

# Personalización opcional por env:
# - APP_PUBLIC_NAME: sobrescribe el nombre mostrado en el título de la discusión
# - WELCOME_DISCUSSION_CATEGORY: intenta usar esa categoría si existe (si no, usa "General" o la primera)
_APP_PUBLIC_NAME = os.environ.get("APP_PUBLIC_NAME")  # p.ej. "Repo Manager Bot"
_WELCOME_CATEGORY = os.environ.get("WELCOME_DISCUSSION_CATEGORY")  # p.ej. "Announcements"


# -----------------------------
# Helpers internos
# -----------------------------
def _iter_repos_from_installation(payload: dict) -> Iterable[Tuple[str, str]]:
    """
    Devuelve (owner, repo) para los repos afectados en eventos de instalación.
    Soporta tanto 'installation.created' como 'installation_repositories.added'.
    """
    # installation.created -> 'repositories'
    if "repositories" in payload:
        account_login = payload["installation"]["account"]["login"]
        for info in payload.get("repositories", []):
            full = info.get("full_name") or ""
            if "/" in full:
                yield tuple(full.split("/", 1))
            else:
                # fallback por si viniera sin full_name
                yield account_login, info["name"]

    # installation_repositories.added -> 'repositories_added'
    if "repositories_added" in payload:
        account_login = payload["installation"]["account"]["login"]
        for info in payload.get("repositories_added", []):
            full = info.get("full_name") or ""
            if "/" in full:
                yield tuple(full.split("/", 1))
            else:
                yield account_login, info["name"]


def _owner_permitido(owner: Optional[str], allowed_owners: Optional[Set[str]]) -> bool:
    if not allowed_owners:
        return True
    return bool(owner) and owner in allowed_owners


def _welcome_in_repos(payload: dict, allowed_owners: Optional[Set[str]]) -> bool:
    """
    Crea (o asegura) la discusión de bienvenida en cada repo del payload.
    Devuelve True si se procesó el evento (aunque algún repo falle).
    """
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    if not installation_id:
        logging.warning("[welcome] payload sin installation.id; nada que hacer")
        return True

    any_repo = False
    for owner, repo in _iter_repos_from_installation(payload):
        any_repo = True
        if not _owner_permitido(owner, allowed_owners):
            continue
        try:
            ok, msg = create_welcome_discussion(
                owner=owner,
                repo=repo,
                installation_id=installation_id,
                app_name=_APP_PUBLIC_NAME,
                pref_category=_WELCOME_CATEGORY,
            )
            if ok:
                logging.info("[welcome] %s/%s ✅ %s", owner, repo, msg)
            else:
                logging.warning("[welcome] %s/%s ⚠️ %s", owner, repo, msg)
        except Exception as e:
            logging.exception("[welcome] %s/%s error: %s", owner, repo, e)

    if not any_repo:
        logging.info("[welcome] evento sin repos en la carga; nada que hacer")
    return True


# -----------------------------
# Handlers por evento
# -----------------------------
def _handle_installation_created(payload: dict, allowed_owners: Optional[Set[str]]) -> bool:
    """installation.created → crea/asegura la Discussion de bienvenida en cada repo instalado."""
    return _welcome_in_repos(payload, allowed_owners)


def _handle_installation_repositories_added(payload: dict, allowed_owners: Optional[Set[str]]) -> bool:
    """installation_repositories.added → crea/asegura la Discussion en repos añadidos."""
    return _welcome_in_repos(payload, allowed_owners)


# -----------------------------
# Función PADRE (única exportada)
# -----------------------------
def handle_github_event(event: str, payload: dict, allowed_owners: Optional[Set[str]] = None) -> bool:
    """
    Dispatcher de eventos. Devuelve True si el evento fue manejado aquí,
    False para que el caller aplique su lógica genérica.
    """
    action = payload.get("action")

    if event == "installation" and action == "created":
        return _handle_installation_created(payload, allowed_owners)

    if event == "installation_repositories" and action == "added":
        return _handle_installation_repositories_added(payload, allowed_owners)

    # (aquí podrás ir sumando más handlers específicos en el futuro)
    return False
