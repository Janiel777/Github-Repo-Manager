from .tokens import count_tokens_messages
from .models import MODELS, estimate_cost

AVAILABLE = ["gpt-5", "gpt-5-mini", "gpt-4o-mini"]

DEFAULT_MAX_OUT = 1500  # fijo

def build_review_messages(pr_title: str, pr_body: str, file_diffs: list[dict], commits: list[dict]) -> list[dict]:
    changes_snippets = []
    for f in file_diffs[:50]:
        patch = f.get("patch", "")
        if not patch:
            continue
        snippet = patch[:4000]
        changes_snippets.append(f"### {f['filename']}\n```\n{snippet}\n```")

    commits_txt = "\n".join([f"- {c.get('sha','')[:7]}: {c.get('message','').strip()}" for c in commits[:30]])

    content = (
        f"# PR: {pr_title}\n\n"
        f"{pr_body or ''}\n\n"
        f"## Commits\n{commits_txt}\n\n"
        f"## Diffs (recortados)\n" + "\n\n".join(changes_snippets)
    )

    return [
        {"role": "system", "content": (
            "Eres un revisor de PRs conciso. Devuelve:\n"
            "1) Resumen claro de cambios.\n"
            "2) Chequeo de buenas prácticas (nombres, documentación, estructura, tests).\n"
            "3) Riesgos lógicos/seguridad y sugerencias accionables.\n"
            "4) Lista de archivos que merecen atención especial.\n"
            "Responde en Markdown."
        )},
        {"role": "user", "content": content},
    ]

def make_price_table(messages: list[dict], max_out: int = DEFAULT_MAX_OUT, cached_ratio: float = 0.0) -> tuple[int, dict]:
    tokens_in = count_tokens_messages(messages)
    prices = {}
    # mapea por id directo
    for model_id in ["gpt-5", "gpt-5-mini", "gpt-4o-mini"]:
        key = [k for k, v in MODELS.items() if v["id"] == model_id][0]
        prices[model_id] = estimate_cost(tokens_in, max_out, key, cached_ratio=cached_ratio)
    return tokens_in, prices

def render_budget_comment(tokens_in: int, prices: dict) -> str:
    return (
        "### 🤖 Presupuesto de análisis con IA (estimado)\n\n"
        "| Modelo | Costo estimado |\n"
        "|---|---|\n"
        f"| gpt-5 | ${prices['gpt-5']:.4f} |\n"
        f"| gpt-5-mini | ${prices['gpt-5-mini']:.4f} |\n"
        f"| gpt-4o-mini | ${prices['gpt-4o-mini']:.4f} |\n\n"
        "Para ejecutar el análisis, comenta en este PR:\n\n"
        "- `/bot review gpt-5`\n"
        "- `/bot review gpt-5-mini`\n"
        "- `/bot review gpt-4o-mini`\n"
    )