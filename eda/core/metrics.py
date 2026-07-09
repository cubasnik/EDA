"""
Prometheus metrics - the EDA equivalent of the PM Server microservice
(Prometheus-based performance monitoring, as commonly found in EDA platforms).

Module-level (process-global) collectors so they survive Store resets in
tests and are shared by every request/background task in this process.
"""
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

ACTIVATIONS_CREATED = Counter(
    "eda_activations_created_total", "Total number of activations created"
)

ACTIVATIONS_TERMINAL = Counter(
    "eda_activations_terminal_total",
    "Activations that reached a terminal state",
    ["state"],
)

ACTIVATION_DURATION = Histogram(
    "eda_activation_duration_seconds",
    "Wall-clock time from activation creation to reaching a terminal state",
)

ACTIVATIONS_IN_PROGRESS = Gauge(
    "eda_activations_in_progress",
    "Activations currently being processed by the engine (not terminal)",
)

ALARMS_RAISED = Counter(
    "eda_alarms_raised_total", "Alarms raised by the fault-management layer", ["severity"]
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "generate_latest",
    "ACTIVATIONS_CREATED",
    "ACTIVATIONS_TERMINAL",
    "ACTIVATION_DURATION",
    "ACTIVATIONS_IN_PROGRESS",
    "ALARMS_RAISED",
]
