"""What an API call cost, computed from the `usage` block the API returns.

Prices are $ per million tokens (Anthropic first-party rates, cached 2026-10). Update them here when
pricing changes; nothing else hard-codes a price. Cache writes cost 1.25x input (5-minute TTL) or
2x (1-hour TTL); cache reads are listed per model.
"""

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-opus-5": Price(input=5.00, output=25.00, cache_read=0.50),
    "claude-opus-4-8": Price(input=5.00, output=25.00, cache_read=0.50),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01),
}
# Claude Haiku 5.5 charges more once a prompt passes 100K tokens.
HAIKU_LONG = Price(input=0.50, output=2.50, cache_read=0.05)
LONG_PROMPT_TOKENS = 100_000

# Unknown model (e.g. a new fallback target): assume the priciest model we know, so budgets err safe.
FALLBACK_PRICE = Price(input=10.00, output=50.00, cache_read=1.00)


def price_for(model: str, prompt_tokens: int = 0) -> Price:
    if model == "claude-haiku-5-5" and prompt_tokens > LONG_PROMPT_TOKENS:
        return HAIKU_LONG
    price = PRICES.get(model)
    if price is None:
        log.warning("no price for model %r; using the conservative fallback price", model)
        return FALLBACK_PRICE
    return price


def _cost_of(model: str, u: dict[str, Any]) -> float:
    inp = u.get("input_tokens", 0) or 0
    read = u.get("cache_read_input_tokens", 0) or 0
    created = u.get("cache_creation", {}) or {}
    write_1h = created.get("ephemeral_1h_input_tokens", 0) or 0
    write_5m = created.get("ephemeral_5m_input_tokens", 0) or 0
    if not created:  # older usage shape: only the total is reported, assume the 5-minute TTL
        write_5m = u.get("cache_creation_input_tokens", 0) or 0
    out = u.get("output_tokens", 0) or 0  # includes thinking tokens

    p = price_for(model, inp + read + write_5m + write_1h)
    dollars = inp * p.input + read * p.cache_read + write_5m * p.input * 1.25 + write_1h * p.input * 2 + out * p.output
    return dollars / 1_000_000


def cost_usd(model: str, usage: dict[str, Any]) -> float:
    """Total cost of one request. With server-side fallbacks, each attempt is billed separately
    (listed in `usage.iterations`), possibly at a different model's rates."""
    iterations = usage.get("iterations") or []
    if not iterations:
        return _cost_of(model, usage)
    total = 0.0
    for it in iterations:
        it_model = it.get("model") or model
        total += _cost_of(it_model, it)
    return total
