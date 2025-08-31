# services/github/github_utils.py

def extract_owner_repo(payload: dict):
    """
    Devuelve (owner, repo) si existe; si no hay repo (p. ej. eventos de instalación), devuelve (owner, None).
    """
    owner = None
    repo = None
    if payload.get("repository"):
        owner = payload["repository"]["owner"]["login"]
        repo  = payload["repository"]["name"]
    elif payload.get("organization"):
        owner = payload["organization"]["login"]
    elif payload.get("installation", {}).get("account"):
        owner = payload["installation"]["account"]["login"]
    return owner, repo
