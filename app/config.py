"""Central application settings.

All values are read from environment variables / the .env file via
pydantic-settings. No values are hardcoded here — see .env.example for the
full list of keys and sample values.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (app/config.py -> project/).
# Anchoring the .env path here makes loading independent of the current
# working directory (uvicorn, streamlit, tests, etc.).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # --- OpenRouter / LLM ---
    openrouter_api_key: str
    openrouter_base_url: str
    model_cheap: str
    model_smart: str
    openrouter_app_title: str
    openrouter_site_url: str

    # --- Databricks ---
    databricks_server_hostname: str
    databricks_http_path: str
    databricks_token: str
    databricks_catalog: str

    # --- Behaviour ---
    max_repair_attempts: int
    read_only: bool
    result_row_limit: int
    schema_top_tables: int
    api_base_url: str

    @property
    def role_model(self) -> dict[str, str]:
        """Map each agent role to a concrete model id."""
        return {
            "clarifier": self.model_cheap,
            "schema": self.model_cheap,
            "generator": self.model_smart,
            "validator": self.model_cheap,
            "repair": self.model_smart,
            "explainer": self.model_cheap,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
