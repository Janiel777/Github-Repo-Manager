# services/github/github_actions.py
import requests

from .github_auth import get_installation_token, get_app_name

def _get_discussion_category_id(owner: str, repo: str, token: str) -> str | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/discussions/categories"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code in (404, 410):
        print(f"[welcome] {owner}/{repo}: Discussions no habilitado ({r.status_code})")
        return None
    r.raise_for_status()
    cats = r.json() or []
    for c in cats:
        if c.get("name", "").lower() == "general":
            return c["id"]
    return cats[0]["id"] if cats else None

def create_welcome_discussion(owner: str, repo: str, installation_id: int, app_name: str | None = None):
    token = get_installation_token(installation_id)
    if not token:
        print(f"[welcome] No se pudo obtener installation token para {owner}/{repo}")
        return
    cat_id = _get_discussion_category_id(owner, repo, token)
    if not cat_id:
        return

    if not app_name:
        try:
            app_name = get_app_name()
        except Exception:
            app_name = "Bot"

    # Título = nombre de la App (como pediste)
    title = app_name
    body = (
        f"¡Hola! Este hilo es el canal de interacción con **{app_name}**.\n\n"
        "• Aquí publicaré avisos y automatizaciones.\n"
        "• Podrás conversar con el bot y (pronto) usar comandos.\n\n"
        "Si necesitas restringir dónde actúa, configura `ALLOWED_OWNERS` en el servidor."
    )
    url = f"https://api.github.com/repos/{owner}/{repo}/discussions"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    payload = {"title": title, "body": body, "category_id": cat_id}
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code not in (201, 202):
        print(f"[welcome] Error creando Discussion en {owner}/{repo}: {r.status_code} {r.text}")
    else:
        print(f"[welcome] Discussion creada en {owner}/{repo}")
