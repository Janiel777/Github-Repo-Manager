# services/github/github_actions.py
import requests

API = "https://api.github.com"
API_VERSION = "2022-11-28"

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "repo-manager-bot"
    }

def post_issue_comment(owner: str, repo: str, number: int, token: str, body_md: str) -> int:
    """
    Publica un comentario en PR/Issue. 'number' es el Issue/PR number.
    """
    url = f"{API}/repos/{owner}/{repo}/issues/{number}/comments"
    r = requests.post(url, headers=_headers(token), json={"body": body_md}, timeout=20)
    r.raise_for_status()
    return r.json()["id"]
