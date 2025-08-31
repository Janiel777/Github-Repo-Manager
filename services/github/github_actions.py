# services/github/github_actions.py
import time
import logging
import requests

from .github_auth import get_installation_token, get_app_name

API = "https://api.github.com"
API_VERSION = "2022-11-28"  # versión estable de REST API

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "repo-manager-bot"
    }

# ---------------------------
#  REST: habilitar Discussions
# ---------------------------
def ensure_discussions_enabled(owner: str, repo: str, token: str) -> bool:
    """
    Comprueba y, si hace falta, activa has_discussions en el repo.
    Requiere permiso: Administration (write).
    """
    # 1) Leer repo
    r = requests.get(f"{API}/repos/{owner}/{repo}", headers=_headers(token), timeout=20)
    if r.status_code == 200:
        if r.json().get("has_discussions"):
            return True
    else:
        logging.warning("[discussions] no pude leer repo %s/%s: %s %s",
                        owner, repo, r.status_code, r.text)
        return False

    # 2) Activar has_discussions
    p = requests.patch(
        f"{API}/repos/{owner}/{repo}",
        headers=_headers(token),
        json={"has_discussions": True},
        timeout=20
    )
    if p.status_code in (200, 202):
        # pequeño delay para que el catálogo de categorías esté listo
        time.sleep(0.8)
        return True

    logging.error("[discussions] activar has_discussions falló en %s/%s: %s %s",
                  owner, repo, p.status_code, p.text)
    return False

# ---------------------------
#  GraphQL helpers
# ---------------------------
def _graphql(token: str, query: str, variables: dict):
    h = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "repo-manager-bot"
    }
    resp = requests.post(f"{API}/graphql", headers=h, json={"query": query, "variables": variables}, timeout=25)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"GraphQL bad JSON ({resp.status_code}): {resp.text}")
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]

def _get_repo_and_category(owner: str, repo: str, token: str, pref_category: str | None = None):
    """
    Devuelve (repositoryId, categoryId, categoryName).
    Elige 'General' si existe; si no, la primera categoría disponible.
    """
    query = """
    query($owner:String!, $name:String!) {
      repository(owner:$owner, name:$name) {
        id
        discussionCategories(first:25) {
          nodes { id name isAnswerable }
        }
      }
    }
    """
    data = _graphql(token, query, {"owner": owner, "name": repo})
    repo_node = data.get("repository")
    if not repo_node:
        raise RuntimeError("Repo no encontrado vía GraphQL")
    categories = repo_node["discussionCategories"]["nodes"]
    if not categories:
        raise RuntimeError("El repo no tiene categorías de Discussions")

    pick = None
    if pref_category:
        for c in categories:
            if c["name"].lower() == pref_category.lower():
                pick = c; break
    if not pick:
        pick = next((c for c in categories if c["name"].lower() == "general"), categories[0])

    return repo_node["id"], pick["id"], pick["name"]

def _already_has_welcome(owner: str, repo: str, token: str, title: str) -> tuple[bool, str | None]:
    """
    Busca si ya existe una discusión con ese título.
    Devuelve (existe, url | None).
    """
    q = """
    query($owner:String!, $name:String!) {
      repository(owner:$owner, name:$name) {
        discussions(first:20, orderBy:{field:CREATED_AT, direction:DESC}) {
          nodes { number title url }
        }
      }
    }
    """
    data = _graphql(token, q, {"owner": owner, "name": repo})
    nodes = data["repository"]["discussions"]["nodes"]
    found = next((d for d in nodes if d["title"] == title), None)
    return (True, found["url"]) if found else (False, None)

# ---------------------------
#  Crear discusión de bienvenida
# ---------------------------
def create_welcome_discussion(
    owner: str,
    repo: str,
    installation_id: int,
    app_name: str | None = None,
    pref_category: str | None = None
) -> tuple[bool, str]:
    """
    Garantiza Discussions habilitado y crea (si no existe) una discusión de bienvenida.
    - owner/repo: destino
    - installation_id: se usa para obtener el installation token
    - app_name: opcional; si no se pasa, se consulta a la API (/app)
    - pref_category: opcional; si existe, se usa esa categoría, si no 'General' o la primera
    Devuelve (ok, url | razón).
    """
    token = get_installation_token(installation_id)
    if not token:
        msg = "No se pudo obtener installation token"
        logging.error("[welcome] %s/%s: %s", owner, repo, msg)
        return False, msg

    # 1) Habilitar Discussions si hace falta
    if not ensure_discussions_enabled(owner, repo, token):
        msg = "No se pudo habilitar Discussions (falta permiso Administration o policy)"
        logging.warning("[welcome] %s/%s: %s", owner, repo, msg)
        return False, msg

    # 2) Título con el nombre de la App
    try:
        app_title = app_name or get_app_name() or "Bot"
    except Exception:
        app_title = app_name or "Bot"
    title = f"{app_title} — canal del bot"

    # 3) Evitar duplicados
    try:
        exists, url = _already_has_welcome(owner, repo, token, title)
        if exists:
            logging.info("[welcome] %s/%s: ya existía (%s)", owner, repo, url)
            return True, url or "Ya existía"
    except Exception as e:
        logging.warning("[welcome] %s/%s: no pude listar discusiones previas: %s", owner, repo, e)

    # 4) Obtener IDs (repo y categoría)
    try:
        repo_id, cat_id, cat_name = _get_repo_and_category(owner, repo, token, pref_category)
    except Exception as e:
        msg = f"Error obteniendo categorías: {e}"
        logging.error("[welcome] %s/%s: %s", owner, repo, msg)
        return False, msg

    # 5) Crear discusión (GraphQL)
    body = (
        f"¡Hola! Este hilo es el **canal oficial** de `{app_title}` en este repo.\n\n"
        "- Aquí el bot publicará avisos y pedirá confirmaciones cuando aplique.\n"
        "- Podrás interactuar con el bot aquí (comandos próximamente).\n\n"
        "_Creado automáticamente al instalar la app._"
    )
    mutation = """
    mutation($repo:ID!, $cat:ID!, $title:String!, $body:String!) {
      createDiscussion(input: {repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) {
        discussion { number url }
      }
    }
    """
    try:
        out = _graphql(token, mutation, {"repo": repo_id, "cat": cat_id, "title": title, "body": body})
        url = out["createDiscussion"]["discussion"]["url"]
        logging.info("[welcome] discusión creada en %s/%s (%s - %s)", owner, repo, cat_name, url)
        return True, url
    except Exception as e:
        msg = f"Error creando discusión: {e}"
        logging.error("[welcome] %s/%s: %s", owner, repo, msg)
        return False, msg
