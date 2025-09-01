# services/openai/requests.py
import os
from openai import OpenAI
from .models import MODELS

_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not _OPENAI_KEY:
            raise RuntimeError("Falta OPENAI_API_KEY")
        _client = OpenAI(api_key=_OPENAI_KEY)
    return _client

def run_review(messages: list[dict], model_id: str, max_out: int | None = None, temperature: float | None = None) -> str:
    """
    Ejecuta el modelo elegido con parámetros válidos por familia:
    - gpt-5 / gpt-5-mini: usan max_completion_tokens; NO pasamos temperature.
    - gpt-4o-mini: usa max_tokens y sí acepta temperature.
    """
    if model_id not in {v["id"] for v in MODELS.values()}:
        raise ValueError(f"Modelo no soportado: {model_id}")

    client = _get_client()

    # Defaults conservadores
    if max_out is None:
        max_out = 1200

    # Enrutado por familia
    if model_id in ("gpt-5", "gpt-5-mini"):
        # Estos modelos aceptan max_completion_tokens y (en muchos despliegues) ignoran/limitan temperature.
        resp = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_completion_tokens=max_out,
        )
    elif model_id == "gpt-4o-mini":
        # 4o-mini es chat-completions “clásico”
        kwargs = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_out,
        }
        # temperature opcional/soportada aquí
        if isinstance(temperature, (int, float)):
            kwargs["temperature"] = float(temperature)
        resp = client.chat.completions.create(**kwargs)
    else:
        # fallback genérico
        resp = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_out,
        )

    return (resp.choices[0].message.content or "").strip()
