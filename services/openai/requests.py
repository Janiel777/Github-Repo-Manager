import os
import httpx
from openai import OpenAI

_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
_client: OpenAI | None = None

DEFAULT_MAX_OUT = 1500  # fijo


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY")
        # Timeout correcto para httpx (read/default 80s, connect 10s)
        timeout = httpx.Timeout(80.0, connect=10.0)
        _client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
    return _client


def _build_prompt(owner: str, repo: str, pr_number: int,
                  files: list[dict], commits: list[dict]) -> list[dict]:
    # Limita tamaño de diffs para no disparar tokens
    parts = []
    remaining = 20000  # aprox caracteres de parches para el prompt
    for f in files:
        name = f.get("filename", "")
        patch = f.get("patch", "") or ""
        if remaining <= 0:
            parts.append(f"### {name}\n*(truncado por tamaño)*")
            continue
        take = patch[:remaining]
        remaining -= len(take)
        parts.append(f"### {name}\n```diff\n{take}\n```")

    commits_md = "\n".join(f"- {c.get('sha', '')[:7]}: {c.get('message', '')}" for c in commits)

    user_content = (
            f"Repository: {owner}/{repo}\nPR: #{pr_number}\n\n"
            f"Commits:\n{commits_md}\n\n"
            "Changes by file:\n" + "\n\n".join(parts)
    )

    return [
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


def review_pull_request(model: str, owner: str, repo: str, pr_number: int,
                        files: list[dict], commits: list[dict], _opts_ignored: dict) -> str:
    """
    Ejecuta la revisión con el modelo indicado (sin parámetros de usuario).
    - gpt-5 / gpt-5-mini: usar max_output_tokens=DEFAULT_MAX_OUT (no temperature).
    - gpt-4o-mini: usar max_tokens=DEFAULT_MAX_OUT (temperature por defecto del modelo).
    """
    client = get_client()
    messages = _build_prompt(owner, repo, pr_number, files, commits)

    model = (model or "").strip()
    if model not in {"gpt-5", "gpt-5-mini", "gpt-4o-mini"}:
        raise ValueError(f"Modelo no soportado: {model}")

    kwargs = dict(model=model, messages=messages)

    if model.startswith("gpt-5"):
        kwargs["max_output_tokens"] = DEFAULT_MAX_OUT
    else:
        # gpt-4o-mini
        kwargs["max_tokens"] = DEFAULT_MAX_OUT

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
