"""Estimated cost of a model call.

List prices in US dollars per million tokens, checked on the date below:
Mistral on https://mistral.ai/news/mistral-small-4/ and Gemini on
https://ai.google.dev/gemini-api/docs/pricing. They change and must be checked
again before relying on them. The free plans of both providers cost nothing
but are rate limited.
"""

from __future__ import annotations

PRICES_CHECKED_ON = "2026-10-20"

# model -> (input, output) in USD per million tokens
PRICES: dict[str, tuple[float, float]] = {
    "mistral-small": (0.15, 0.60),  # Mistral Small 4
    "ministral-14b": (0.20, 0.20),
    "ministral-8b": (0.15, 0.15),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    # Introductory price until 31 December 2026.
    "gemini-3.8-flash": (0.75, 3.75),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """None for a model without a known price (including the scripted provider)."""
    for name in sorted(PRICES, key=len, reverse=True):
        if model == name or model.startswith(f"{name}-"):
            price_in, price_out = PRICES[name]
            return round((input_tokens * price_in + output_tokens * price_out) / 1e6, 6)
    return None
