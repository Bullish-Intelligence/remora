"""App-level wiring & support."""

from remora.core.services.broker import HumanInputBroker
from remora.core.services.lifecycle import RemoraLifecycle
from remora.core.services.metrics import Metrics
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchService, SearchServiceProtocol


def __getattr__(name: str):
    if name == "FileReconciler":
        from remora.code.reconciler import FileReconciler

        return FileReconciler
    if name == "RuntimeServices":
        from remora.core.services.container import RuntimeServices

        return RuntimeServices
    if name == "ActorPool":
        from remora.core.agents.runner import ActorPool

        return ActorPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
