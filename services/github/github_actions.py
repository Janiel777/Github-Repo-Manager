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

def post_comment(owner: str, repo: str, issue_number: int, token: str, body_md: str) -> int:
    url = f"{API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    r = requests.post(url, headers=_headers(token), json={"body": body_md}, timeout=25)
    r.raise_for_status()
    return r.json()["id"]

def update_comment(owner: str, repo: str, comment_id: int, token: str, body_md: str) -> None:
    url = f"{API}/repos/{owner}/{repo}/issues/comments/{comment_id}"
    r = requests.patch(url, headers=_headers(token), json={"body": body_md}, timeout=25)
    r.raise_for_status()

def fetch_pr_files(owner: str, repo: str, number: int, token: str) -> list[dict]:
    """Devuelve [{filename, patch}] de /pulls/{number}/files (paginado)."""
    items: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            f"{API}/repos/{owner}/{repo}/pulls/{number}/files",
            headers=_headers(token),
            params={"per_page": 100, "page": page},
            timeout=25,
        )
        r.raise_for_status()
        batch = r.json()
        for it in batch:
            items.append({"filename": it.get("filename", ""), "patch": it.get("patch", "")})
        if len(batch) < 100:
            break
        page += 1
    return items

def fetch_pr_commits(owner: str, repo: str, number: int, token: str) -> list[dict]:
    """Devuelve [{sha, message, author}] de /pulls/{number}/commits (paginado)."""
    items: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            f"{API}/repos/{owner}/{repo}/pulls/{number}/commits",
            headers=_headers(token),
            params={"per_page": 100, "page": page},
            timeout=25,
        )
        r.raise_for_status()
        batch = r.json()
        for it in batch:
            commit = it.get("commit", {}) or {}
            items.append({
                "sha": it.get("sha", ""),
                "message": (commit.get("message") or "").strip(),
                "author": ((commit.get("author") or {}).get("name") or ""),
            })
        if len(batch) < 100:
            break
        page += 1
    return items