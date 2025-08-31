# services/openai/requests.py
from __future__ import annotations

import os
import textwrap
from typing import List, Dict, Any, Optional

from openai import OpenAI

_MODEL = "gpt-5-mini"  # fijo: solo usamos gpt-5-mini
_API_KEY = os.environ.get("OPENAI_API_KEY")

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """Singleton del cliente OpenAI (requiere OPENAI_API_KEY)."""
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno")
        _client = OpenAI(api_key=_API_KEY)
    return _client


def _trim_text(s: str, max_chars: int) -> str:
    if not s:
        return ""
    return s if len(s) <= max_chars else s[: max(0, max_chars - 1000)] + "\n\n[…truncado…]\n"


def build_pr_prompt(
    pr_details: Dict[str, Any],
    pr_files: List[Dict[str, str]],
    pr_commits: List[Dict[str, str]],
    security_findings: Optional[Dict[str, List[str]]] = None,
) -> str:
    """
    Crea el prompt para revisión de PR.
    - pr_details = {title, body, author, number, base, head}
    - pr_files   = [{filename, patch}]
    - pr_commits = [{sha, message, author}]
    - security_findings = {"filenames":[...], "matches":[...]} (opcional)
    """
    files_block = []
    for f in pr_files:
        patch = f.get("patch") or ""
        files_block.append(
            f"### {f.get('filename')}\n"
            f"```diff\n{_trim_text(patch, 6000)}\n```\n"
        )
    files_text = "\n".join(files_block) if files_block else "_(sin cambios legibles por diff)_"

    commits_block = []
    for c in pr_commits:
        sha = (c.get("sha") or "")[:7]
        msg = (c.get("message") or "").strip().replace("\r", "")
        commits_block.append(f"- **{sha}**: {msg}")
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

    sec_block = ""
    if security_findings and (security_findings.get("filenames") or security_findings.get("matches")):
        examples = "\n".join(f"  - {m}" for m in security_findings.get("matches", [])[:10])
        sec_block = (
            "\n\n**Detección preliminar de posibles secretos:**\n"
            f"- Archivos: {', '.join(security_findings.get('filenames', [])) or '—'}\n"
            f"- Líneas (ejemplos):\n{examples if examples else '  - —'}\n"
        )

    instrucciones = textwrap.dedent("""
    Eres un revisor de código experto. Devuelve **un único bloque Markdown** con:

    1. **Resumen del PR**: qué se implementó/cambió (2–6 bullets).
    2. **Buenas prácticas**: documentación mínima, nombres claros, estilo consistente, manejo de errores, tests. Usa ✔️/⚠️/❌ con ejemplos concretos.
    3. **Revisión de lógica**: posibles errores, edge cases, regresiones; si todo luce correcto, explícalo.
    4. **Acciones sugeridas**: pasos concretos (tests, refactors, validaciones).

    Si hay cualquier indicio de secretos o archivos sensibles:
    - di explícitamente que **no deben versionarse** y sugiere añadirlos a **.gitignore**;
    - recomienda **rotar** credenciales y, si aplica, limpiar el historial.
    Cita rutas y líneas relevantes cuando sea posible.
    """)

    return f"{instrucciones}\n\n---\n\n{pr_intro}{sec_block}"


def review_pull_request(
    pr_details: Dict[str, Any],
    pr_files: List[Dict[str, str]],
    pr_commits: List[Dict[str, str]],
    security_findings: Optional[Dict[str, List[str]]] = None,
    *,
    model: Optional[str] = None,              # se ignora (si lo llaman desde fuera)
    temperature: Optional[float] = None,      # se ignora (gpt-5-mini usa default)
    max_tokens_out: int = 1200,
) -> str:
    """
    Llama a gpt-5-mini y devuelve Markdown con el análisis de la revisión.
    - Usa 'max_completion_tokens' (no 'max_tokens').
    - No envía 'temperature' (usa el default del modelo).
    """
    prompt = build_pr_prompt(pr_details, pr_files, pr_commits, security_findings)
    client = _get_client()

    messages = [
        {"role": "system", "content": "Eres un revisor de código senior, preciso y conciso."},
        {"role": "user", "content": prompt},
    ]

    resp = client.chat.completions.create(
        model=_MODEL,
        messages=messages,
        max_completion_tokens=max_tokens_out,
        # sin temperature → el modelo usa su default
    )
    return resp.choices[0].message.content.strip()
