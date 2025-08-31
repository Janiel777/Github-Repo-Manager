# services/openai/requests.py
import os
import textwrap
from typing import List, Dict, Any, Optional

from openai import OpenAI

_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")

_client: Optional[OpenAI] = None

def _get_client() -> OpenAI:
    """
    Devuelve un cliente OpenAI singleton. Lanza excepción si falta la API key.
    """
    global _client
    if _client is None:
        if not _OPENAI_KEY:
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno")
        _client = Client(api_key=_OPENAI_KEY)  # type: ignore[name-defined]
    return _client

# Compat con typing sin importar Client de tipos
try:
    from openai import OpenAI as Client  # alias más legible
except Exception:
    Client = object  # fallback para type hints


def _trim_text(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[: max(0, max_chars - 1000)] + "\n\n[…truncado…]\n"

def build_pr_prompt(
    pr_details: Dict[str, Any],
    pr_files: List[Dict[str, str]],
    pr_commits: List[Dict[str, str]],
) -> str:
    """
    Crea el prompt para revisión: resumen + buenas prácticas + revisión de lógica.
    pr_details = {title, body, author, number, base, head}
    pr_files   = [{filename, patch}]
    pr_commits = [{sha, message, author}]
    """
    files_block = []
    for f in pr_files:
        patch = f.get("patch") or ""
        # cortar diffs MUY grandes; suficiente para análisis estático
        files_block.append(
            f"### {f.get('filename')}\n"
            f"```diff\n{_trim_text(patch, 6000)}\n```\n"
        )
    files_text = "\n".join(files_block) if files_block else "_(sin cambios legibles por diff)_"

    commits_block = []
    for c in pr_commits:
        commits_block.append(f"- **{c.get('sha', '')[:7]}**: {c.get('message', '').strip()}")
    commits_text = "\n".join(commits_block) if commits_block else "_(sin commits listados)_"

    pr_intro = textwrap.dedent(f"""
    Pull Request **#{pr_details.get('number')}**  
    Título: **{pr_details.get('title','')}**  
    Autor: **{pr_details.get('author','')}**  
    Base → Head: **{pr_details.get('base','')}** → **{pr_details.get('head','')}**

    Descripción:
    {pr_details.get('body') or '_(sin descripción)_'}

    Commits incluidos:
    {commits_text}

    Cambios (diffs relevantes):
    {files_text}
    """).strip()

    instrucciones = textwrap.dedent("""
    Eres un revisor de código experto. Debes entregar **un solo bloque en Markdown** con estas secciones:

    1. **Resumen del PR**: qué se implementó/cambió exactamente, en lenguaje natural (2–6 bullets).
    2. **Buenas prácticas** (checklist breve): documentación mínima, nombres claros, consistencia de estilo, manejo de errores, tests/tipo de cobertura si aplica. Indica ✔️/⚠️/❌ y ejemplos concretos.
    3. **Revisión de lógica**: señala posibles errores, edge cases, regresiones y contratos rotos. Si todo luce correcto, explícalo.
    4. **Acciones sugeridas** (bullets): pasos concretos para mejorar o validar (tests, refactors, validaciones, etc.).

    Sé específico, cita rutas de archivo y fragmentos relevantes del diff. Evita divagar.
    """)

    return f"{instrucciones}\n\n---\n\n{pr_intro}"


def review_pull_request(
    pr_details: Dict[str, Any],
    pr_files: List[Dict[str, str]],
    pr_commits: List[Dict[str, str]],
) -> str:
    """
    Llama al modelo y devuelve Markdown con el análisis de la revisión.
    """
    prompt = build_pr_prompt(pr_details, pr_files, pr_commits)
    client = _get_client()
    resp = client.chat.completions.create(
        model=_OPENAI_MODEL,
        temperature=0.2,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": "Eres un revisor de código senior, preciso y conciso."},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content.strip()
