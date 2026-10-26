import uuid
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

# Single-user MVP: every row belongs to this user (seeded by the first migration).
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://explore:explore@localhost:5433/explore"
    test_database_url: str = "postgresql+asyncpg://explore:explore@localhost:5433/explore_test"

    anthropic_api_key: str = ""
    chat_model: str = "claude-opus-5-5"
    chat_effort: str = "low"  # M6: ~1 s to first text, half the cost of medium (evals/p0_cards.md)
    chat_max_tokens: int = 16000
    chat_fallbacks: bool = True  # server-side refusal fallback (fallbacks="default")
    light_model: str = "claude-haiku-5-5"

    # Spend limits in USD for the app's own calls (0 = no limit). Evals use run_cards.py --max-cost.
    daily_budget_usd: float = 2.0
    monthly_budget_usd: float = 20.0

    prompts_dir: Path = REPO_ROOT / "prompts"
    profile_path: Path = REPO_ROOT / "config" / "profile.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()
