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

def _extract_text(choice) -> str:
    """Soporta content=str o content=[{type,text}, ...]."""
    msg = choice.message
    if isinstance(msg.content, str) and msg.content:
        return msg.content
    # content parts (nuevo formato en algunos modelos)
    if isinstance(msg.content, list):
        parts = []
        for p in msg.content:
            # campos típicos: {"type": "output_text"|"text", "text": "..."}
            t = (p.get("text") if isinstance(p, dict) else None) or ""
            parts.append(t)
        return "".join(parts).strip()
    # si hay campo refusal, inclúyelo para que se vea el motivo
    ref = getattr(msg, "refusal", None)
    return (ref or "").strip()

def review_pull_request(model: str, owner: str, repo: str, pr_number: int,
                        files: list[dict], commits: list[dict], opts: dict) -> str:
    """
    Ejecuta la revisión con el modelo indicado.
    Modelos esperados: 'gpt-5', 'gpt-5-mini', 'gpt-4o-mini'
    - gpt-5 / gpt-5-mini: usar max_completion_tokens (no temperature).
    - gpt-4o-mini: usar temperature (opcional) y max_tokens (opcional).
    """
    client = get_client()
    messages = _build_prompt(owner, repo, pr_number, files, commits)

    model = (model or "").strip()
    if model not in {"gpt-5", "gpt-5-mini", "gpt-4o-mini"}:
        raise ValueError(f"Modelo no soportado: {model}")

    # Siempre pedimos texto plano para evitar contenido vacío por "content parts"
    kwargs = dict(
        model=model,
        messages=messages,
        response_format={"type": "text"},
    )

    # Parametrización por modelo
    if model.startswith("gpt-5"):
        # 👉 clave correcta para gpt-5/gpt-5-mini
        if "max" in opts:
            try:
                kwargs["max_completion_tokens"] = int(opts["max"])
            except Exception:
                pass
        elif "max:salida" in opts:
            try:
                kwargs["max_completion_tokens"] = int(opts["max:salida"])
            except Exception:
                pass
        # no setear temperature: usar la del modelo
    else:
        # gpt-4o-mini
        if "temp" in opts:
            try:
                kwargs["temperature"] = float(opts["temp"])
            except Exception:
                pass
        if "max" in opts:
            try:
                kwargs["max_tokens"] = int(opts["max"])
            except Exception:
                pass

    resp = client.chat.completions.create(**kwargs)

    # Extrae texto de forma robusta (string o "content parts")
    msg = resp.choices[0].message
    content = msg.content
    if not content and isinstance(msg.content, list):
        try:
            content = "".join(
                (part.get("text", "") if isinstance(part, dict) else str(part))
                for part in msg.content
            ).strip()
        except Exception:
            content = ""

    return content or ""
