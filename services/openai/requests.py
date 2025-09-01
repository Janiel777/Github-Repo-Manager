# services/openai/requests.py
import os

from httpx import Timeout
from openai import OpenAI
from .models import MODELS

_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY")
        # Timeouts conservadores para evitar colgarnos
        _client = OpenAI(api_key=api_key, timeout=Timeout(connect=10.0, read=30.0, write=30.0))
    return _client


def _build_prompt(owner: str, repo: str, pr_number: int,
                  files: list[dict], commits: list[dict]) -> list[dict]:
    # Limita tamaño de diffs para no disparar tokens
    parts = []
    remaining = 20000  # caracteres de parches (aprox) para el prompt
    for f in files:
        name = f.get("filename", "")
        patch = f.get("patch", "") or ""
        if remaining <= 0:
            parts.append(f"### {name}\n*(truncado por tamaño)*")
            continue
        take = patch[:remaining]
        remaining -= len(take)
        parts.append(f"### {name}\n```diff\n{take}\n```")

    commits_md = "\n".join(
        f"- {c.get('sha', '')[:7]}: {c.get('message', '')}" for c in commits
    )

    user_content = (
            f"Repository: {owner}/{repo}\nPR: #{pr_number}\n\n"
            f"Commits:\n{commits_md}\n\n"
            "Changes by file:\n" + "\n\n".join(parts)
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior code reviewer. Provide a concise but thorough review:\n"
                "- Summarize the intent of the PR.\n"
                "- Check best practices (naming, docs, tests, structure).\n"
                "- Check security/privacy (secrets committed, .gitignore issues).\n"
                "- Spot logic or edge-case issues.\n"
                "Return Markdown with headings and bullet points."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    return messages


def review_pull_request(model: str, owner: str, repo: str, pr_number: int,
                        files: list[dict], commits: list[dict], opts: dict) -> str:
    """
    Ejecuta la revisión con el modelo indicado.
    Modelos esperados: 'gpt-5', 'gpt-5-mini', 'gpt-4o-mini'
    - gpt-5 / gpt-5-mini: usar max_output_tokens (no temperature).
    - gpt-4o-mini: usar temperature (opcional) y max_tokens (opcional).
    """
    client = get_client()
    messages = _build_prompt(owner, repo, pr_number, files, commits)

    model = (model or "").strip()
    if model not in {"gpt-5", "gpt-5-mini", "gpt-4o-mini"}:
        raise ValueError(f"Modelo no soportado: {model}")

    kwargs = dict(model=model, messages=messages)

    # Parametrización por modelo
    if model.startswith("gpt-5"):
        # max_output_tokens (si el usuario pasó 'max' o 'max:salida')
        if "max" in opts:
            try:
                kwargs["max_output_tokens"] = int(opts["max"])
            except Exception:
                pass
        elif "max:salida" in opts:
            try:
                kwargs["max_output_tokens"] = int(opts["max:salida"])
            except Exception:
                pass
        # temperatura: dejar por defecto para gpt-5
    else:
        # gpt-4o-mini
        if "temp" in opts:
            try:
                kwargs["temperature"] = float(opts["temp"])
            except Exception:
                pass
        if "temp:0.2" in opts:  # por si llega con formato raro
            try:
                kwargs["temperature"] = float(opts["temp:0.2"])
            except Exception:
                pass
        if "max" in opts:
            try:
                kwargs["max_tokens"] = int(opts["max"])
            except Exception:
                pass

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
