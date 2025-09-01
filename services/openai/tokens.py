# services/openai/tokens.py
from __future__ import annotations
import tiktoken

# Encodings que probamos. Si alguno no existe en tu versión de tiktoken, lo omitimos.
_ENCODING_CANDIDATES = ["o200k_base", "cl100k_base", "p50k_base", "r50k_base"]

def _encodings():
    encs = []
    for name in _ENCODING_CANDIDATES:
        try:
            encs.append(tiktoken.get_encoding(name))
        except Exception:
            pass
    if not encs:  # fallback mínimo
        encs.append(tiktoken.get_encoding("cl100k_base"))
    return encs

def count_tokens_text(text: str) -> int:
    text = text or ""
    mx = 0
    for enc in _encodings():
        try:
            mx = max(mx, len(enc.encode(text)))
        except Exception:
            continue
    return mx

def count_tokens_messages(messages: list[dict]) -> int:
    """
    Estimación conservadora para chat-completions:
    sumamos tokens del contenido y añadimos un pequeño overhead (+4 por mensaje, +2 final).
    """
    total = 0
    for m in messages or []:
        role = m.get("role", "user") or ""
        content = m.get("content", "") or ""
        total += count_tokens_text(f"{role}: {content}") + 4
    return total + 2
