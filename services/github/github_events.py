# services/github/github_events.py
from typing import Iterable, Tuple, Optional, Set
from .github_actions import create_welcome_discussion

__all__ = ["handle_github_event"]

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


# -----------------------------
# Handlers por evento
# -----------------------------
def _handle_installation_created(payload: dict, allowed_owners: Optional[Set[str]]) -> bool:
    """installation.created → crea Discussion de bienvenida en cada repo instalado."""
    installation_id = payload["installation"]["id"]
    for owner, repo in _iter_repos_from_installation(payload):
        if not _owner_permitido(owner, allowed_owners):
            continue
        try:
            create_welcome_discussion(owner, repo, installation_id)
        except Exception as e:
            print(f"[welcome] Error {owner}/{repo}: {e}")
    return True


def _handle_installation_repositories_added(payload: dict, allowed_owners: Optional[Set[str]]) -> bool:
    """installation_repositories.added → crea Discussion de bienvenida en repos añadidos."""
    installation_id = payload["installation"]["id"]
    for owner, repo in _iter_repos_from_installation(payload):
        if not _owner_permitido(owner, allowed_owners):
            continue
        try:
            create_welcome_discussion(owner, repo, installation_id)
        except Exception as e:
            print(f"[welcome] Error {owner}/{repo}: {e}")
    return True


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

    # (aquí podrás ir sumando más handlers específicos)
    return False
