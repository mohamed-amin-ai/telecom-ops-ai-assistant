"""OpenTelemetry spans around the agent's steps. A no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is
set (then spans go to that OTLP/HTTP collector), so it costs nothing when unused. Span
attributes carry names, counts and outcomes only -- never prompts, answers or KPI values."""
import contextlib
import logging
import os

log = logging.getLogger("tracing")
_tracer = None


def setup_tracing(exporter=None) -> bool:
    """Configure the global tracer. `exporter` is for tests; otherwise OTLP/HTTP from env."""
    global _tracer
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if exporter is None and not endpoint:
        return False
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )

        provider = TracerProvider(resource=Resource.create(
            {"service.name": os.getenv("OTEL_SERVICE_NAME", "telecom-ops-assistant")}))
        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        _tracer = provider.get_tracer("telecom-ops-assistant")
        return True
    except Exception as e:  # noqa: BLE001 -- tracing must never take the service down
        log.warning("tracing disabled: %s: %s", type(e).__name__, e)
        _tracer = None
        return False


def reset() -> None:
    global _tracer
    _tracer = None


@contextlib.contextmanager
def span(name: str, **attrs):
    """`with span("tool.kpi_profile", tool="kpi_profile") as s: ... s.set("outcome", "ok")`"""
    if _tracer is None:
        yield _Noop()
        return
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            sp.set_attribute(k, v)
        try:
            yield _Live(sp)
        except Exception as e:
            sp.set_attribute("error.type", type(e).__name__)
            raise


class _Noop:
    def set(self, key, value):
        pass


class _Live:
    def __init__(self, sp):
        self._sp = sp

    def set(self, key, value):
        self._sp.set_attribute(key, value)
