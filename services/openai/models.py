from __future__ import annotations

# Tabla de modelos y precios (USD por 1 millón de tokens)
MODELS = {
    "gpt5": {
        "id": "gpt-5",
        "encoding": "o200k_base",
        "in_per_mtok": 1.25,   # input $/1M
        "out_per_mtok": 10.00, # output $/1M
    },
    "gpt5mini": {
        "id": "gpt-5-mini",
        "encoding": "o200k_base",
        "in_per_mtok": 0.25,
        "out_per_mtok": 1.25,
    },
    "gpt4omini": {
        "id": "gpt-4o-mini",
        "encoding": "o200k_base",
        "in_per_mtok": 0.15,
        "out_per_mtok": 0.60,
    },
}

def model_from_id(model_id: str) -> dict | None:
    for k, v in MODELS.items():
        if v["id"] == model_id:
            return v
    return None

def estimate_cost(tokens_in: int, max_out: int, model_key: str, cached_ratio: float = 0.0) -> float:
    """
    tokens_in: estimación de entrada
    max_out: tope de salida (peor caso)
    cached_ratio: fracción de entrada facturable con cache-hit (0..1).
    """
    m = MODELS[model_key]
    billable_in = max(tokens_in * (1.0 - max(0.0, min(1.0, cached_ratio))), 0)
    cost_in  = (billable_in / 1_000_000.0) * m["in_per_mtok"]
    cost_out = (max_out   / 1_000_000.0) * m["out_per_mtok"]
    return cost_in + cost_out
