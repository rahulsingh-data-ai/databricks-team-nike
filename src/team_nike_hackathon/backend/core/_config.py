from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..._metadata import app_name, app_slug

# --- Config ---

project_root = Path(__file__).parent.parent.parent.parent.parent
env_file = project_root / ".env"

if env_file.exists():
    load_dotenv(dotenv_path=env_file)


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=env_file,
        env_prefix=f"{app_slug.upper()}_",
        extra="ignore",
        env_nested_delimiter="__",
    )
    app_name: str = Field(default=app_name)

    # Name of the Databricks Model Serving endpoint that re-ranks search
    # results with LLM reasoning + evidence. Empty disables agentic mode.
    matchcare_endpoint: str = Field(default="")

    # Foundation-model endpoint used by the agentic LLM pipeline (query
    # parser, evidence scorer, recommendation generator).
    #
    # On the Nike workspace the default is Claude Sonnet 4-6, which is
    # already ready and high-quality. On a fresh workspace where that
    # endpoint isn't available, override via the
    # TEAM_NIKE_HACKATHON_LLM_ENDPOINT env var (or fall back to the
    # built-in Llama 3.3 70B that ships pre-deployed in every workspace).
    llm_endpoint: str = Field(default="databricks-claude-sonnet-4-6")

    # SQL warehouse used to run search against the Unity Catalog Delta
    # tables. Empty disables Delta search and falls back to Lakebase.
    # Nike default: NikeSoleSql-wdc_glops.
    delta_warehouse_id: str = Field(default="")

    # Fully-qualified Delta table that backs facility search. The ETL in
    # pipelines/etl_pipeline.py writes the same shape regardless of
    # catalog/schema; on Nike we land tables in
    # development.dev_gps_research_insights.*.
    delta_facilities_table: str = Field(
        default="development.dev_gps_research_insights.facilities_gold"
    )

    @property
    def static_assets_path(self) -> Path:
        return Path(str(resources.files(app_slug))).joinpath("__dist__")

    def __hash__(self) -> int:
        return hash(self.app_name)


# --- Logger ---

logger = logging.getLogger(app_name)
