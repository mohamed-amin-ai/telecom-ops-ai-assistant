"""Structured JSON logs (with a per-request id) and optional Sentry error tracking."""
import contextvars
import json
import logging
import os

from .config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if settings.log_json
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def setup_sentry() -> bool:
    """No-op unless SENTRY_DSN is set. Request bodies (user questions) and the API-key
    header are never sent."""
    if not settings.sentry_dsn:
        return False
    import sentry_sdk
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,  # frame vars would include headers/API keys and bodies
        environment=os.getenv("ENVIRONMENT", "production"),
        release=os.getenv("RELEASE"),
        event_scrubber=EventScrubber(denylist=[*DEFAULT_DENYLIST, "x-api-key", "x_api_key"]),
    )
    return True
