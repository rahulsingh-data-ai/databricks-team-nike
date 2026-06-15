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
    # parser, evidence scorer, recommendation generator). Defaults to the
    # built-in Llama 3.3 70B that ships pre-deployed in every Databricks
    # workspace; override to point at a custom fine-tuned endpoint.
    llm_endpoint: str = Field(default="databricks-meta-llama-3-3-70b-instruct")

    # SQL warehouse used to run search against the Unity Catalog Delta
    # tables. Empty disables Delta search and falls back to Lakebase.
    delta_warehouse_id: str = Field(default="")

    # Fully-qualified Delta table that backs facility search. Schema is
    # the ``facilities_gold`` shape from the referral-copilot pipeline.
    delta_facilities_table: str = Field(
        default="workspace.referral_copilot.facilities_gold"
    )

    @property
    def static_assets_path(self) -> Path:
        return Path(str(resources.files(app_slug))).joinpath("__dist__")

    def __hash__(self) -> int:
        return hash(self.app_name)


# --- Logger ---

logger = logging.getLogger(app_name)
