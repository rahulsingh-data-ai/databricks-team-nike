"""MLflow tracing for the referral pipeline."""

from __future__ import annotations

import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import mlflow
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False


class ReferralTracer:
    """Manual MLflow tracer for the referral copilot pipeline."""

    def __init__(self):
        self.run = None
        self.start_time = None

    def start_run(self, query: str):
        if not HAS_MLFLOW:
            return
        try:
            mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "databricks"))
            mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT_NAME", "/referral_copilot/search-pipeline"))
            self.run = mlflow.start_run(run_name=f"search_{query[:30]}")
            self.start_time = time.time()
            mlflow.log_param("query", query)
        except Exception as e:
            logger.warning(f"MLflow start_run failed: {e}")

    def log_agent(self, agent_name: str, latency_ms: float, output_summary: str = ""):
        if not HAS_MLFLOW or not self.run:
            return
        try:
            mlflow.log_metric(f"{agent_name}_latency_ms", latency_ms)
            if output_summary:
                mlflow.log_param(f"{agent_name}_output", output_summary[:250])
        except Exception as e:
            logger.warning(f"MLflow log_agent failed: {e}")

    def log_results(self, result_count: int, top_trust: str, avg_trust_rank: float):
        if not HAS_MLFLOW or not self.run:
            return
        try:
            mlflow.log_metric("result_count", result_count)
            mlflow.log_param("top_trust_signal", top_trust)
            mlflow.log_metric("avg_trust_rank", avg_trust_rank)
        except Exception as e:
            logger.warning(f"MLflow log_results failed: {e}")

    def end_run(self):
        if not HAS_MLFLOW or not self.run:
            return
        try:
            if self.start_time:
                total_ms = (time.time() - self.start_time) * 1000
                mlflow.log_metric("total_latency_ms", total_ms)
            mlflow.end_run()
        except Exception as e:
            logger.warning(f"MLflow end_run failed: {e}")
        finally:
            self.run = None
