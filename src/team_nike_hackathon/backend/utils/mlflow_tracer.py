"""MLflow tracing for the referral pipeline.

Tracing is opt-in: set ``MLFLOW_TRACKING_URI`` and
``MLFLOW_EXPERIMENT_NAME`` to enable. If they are unset (typical for
local dev), the tracer becomes a silent no-op so the pipeline still
returns a result.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

try:
    import mlflow  # type: ignore

    HAS_MLFLOW = True
except ImportError:
    mlflow = None  # type: ignore[assignment]
    HAS_MLFLOW = False


MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
MLFLOW_EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", "").strip()


def _tracing_enabled() -> bool:
    return HAS_MLFLOW and bool(MLFLOW_TRACKING_URI) and bool(MLFLOW_EXPERIMENT_NAME)


class ReferralTracer:
    """Manual MLflow tracer. No-op when MLflow env vars are not configured."""

    def __init__(self):
        self.run = None
        self.start_time: float | None = None
        self._enabled = _tracing_enabled()

    def start_run(self, query: str):
        if not self._enabled:
            return
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
            safe_name = (query or "search")[:30].replace("\n", " ")
            self.run = mlflow.start_run(run_name=f"search_{safe_name}")
            self.start_time = time.time()
            mlflow.log_param("query", (query or "")[:250])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MLflow start_run skipped: {e}")
            self._enabled = False

    def log_agent(self, agent_name: str, latency_ms: float, output_summary: str = ""):
        if not self._enabled or not self.run:
            return
        try:
            metric_key = f"{agent_name.replace(' ', '_').lower()}_latency_ms"
            mlflow.log_metric(metric_key, latency_ms)
            if output_summary:
                mlflow.log_param(f"{metric_key}_out", output_summary[:250])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MLflow log_agent skipped: {e}")

    def log_results(self, result_count: int, top_trust: str, avg_trust_rank: float):
        if not self._enabled or not self.run:
            return
        try:
            mlflow.log_metric("result_count", result_count)
            mlflow.log_param("top_trust_signal", top_trust)
            mlflow.log_metric("avg_trust_rank", avg_trust_rank)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MLflow log_results skipped: {e}")

    def end_run(self):
        if not self._enabled or not self.run:
            return
        try:
            if self.start_time is not None:
                mlflow.log_metric(
                    "total_latency_ms", (time.time() - self.start_time) * 1000
                )
            mlflow.end_run()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MLflow end_run skipped: {e}")
        finally:
            self.run = None
