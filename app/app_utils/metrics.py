"""Custom metrics and telemetry utilities for Cymbal Operations Agent."""

import logging
import os

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "benson-data-elevate")


class OperationsMetricsTracker:
    """Tracks latency, query status, and anomaly indicators for Cloud Monitoring."""

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or PROJECT_ID
        self._monitoring_client = None

    def _get_client(self):
        if self._monitoring_client is None:
            try:
                from google.cloud import monitoring_v3
                self._monitoring_client = monitoring_v3.MetricServiceClient()
            except Exception as e:
                logger.debug("Cloud Monitoring client not initialized: %s", e)
        return self._monitoring_client

    def record_metric(self, metric_type: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Records a custom metric point for Cloud Monitoring export."""
        labels = labels or {}
        logger.info(
            "METRIC_POINT: type=%s value=%.4f labels=%s",
            metric_type,
            value,
            labels,
        )


metrics_tracker = OperationsMetricsTracker()
