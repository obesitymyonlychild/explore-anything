import anthropic

CONSOLE_BILLING = "console.anthropic.com → Settings → Billing"


def describe(e: anthropic.APIError) -> tuple[str, str]:
    """(code, message) for an API error, in words the page can show as-is."""
    if isinstance(e, anthropic.AuthenticationError):
        return "auth", "Anthropic API key missing or invalid. Check ANTHROPIC_API_KEY in .env, then restart."
    if isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e).lower():
        return "out_of_credit", f"Your Anthropic API credit is used up. Top up at {CONSOLE_BILLING}, then retry."
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limited", "Rate limited by the API. Try again in a moment."
    if isinstance(e, anthropic.OverloadedError):
        return "overloaded", "Claude is overloaded right now. Try again in a moment."
    if isinstance(e, anthropic.APIStatusError):
        return "api_error", f"API error {e.status_code}: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "connection", "Couldn't reach the Anthropic API."
    return "api_error", str(e)
