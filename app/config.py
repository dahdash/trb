import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm_token: str | None
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    neshan_key: str | None
    neshan_web_key: str | None


def load() -> Settings:
    return Settings(
        db_path=ROOT / os.environ.get("DB_PATH", "data/torob.db"),
        llm_token=os.environ.get("BOX_API_TOKEN") or None,
        # Off unless asked for: local development uses the rule-based assistant and costs nothing.
        llm_enabled=os.environ.get("LLM_ENABLED") == "1" and bool(os.environ.get("BOX_API_TOKEN")),
        # boxapi is the provider (Q-003); any OpenAI-compatible endpoint works
        llm_base_url=os.environ.get("LLM_BASE_URL") or "https://ai.boxapi.ir/ai/v1",
        llm_model=os.environ.get("LLM_MODEL") or "gpt-5.4-mini",
        neshan_key=os.environ.get("NESHAN_API_KEY") or None,
        # Browser map key (web.…, domain-restricted in the Neshan panel), safe to send to the page (Q-009)
        neshan_web_key=os.environ.get("NESHAN_WEB_API_KEY") or None,
    )


settings = load()
