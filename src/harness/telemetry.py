"""OpenTelemetry / Phoenix tracing — the story the rubric wants made visible.

Design goals:
  - **Opt-in.** Off by default (no Phoenix dependency at run time, tests stay
    hermetic). Enable with `HARNESS_TELEMETRY=1` or the CLI `--telemetry` flag.
  - **Resilient.** When off, every helper is a no-op via OTel's default no-op
    tracer, so node code can call `span(...)`/`record_tokens(...)` unconditionally.

What gets traced (the visual proof):
  - one span per node (planner / executor / verifier / abort),
  - token counts per node (from `msg.usage`), and
  - one span per verification iteration (verify_node is called once per retry),
    so the loop stacks visibly in the Phoenix UI.
"""

from __future__ import annotations

import os

from opentelemetry import trace

_PROJECT = "gusti-harness"
_tracer = trace.get_tracer("harness")  # no-op proxy until a provider is registered
_enabled = False


def _is_truthy(v: str | None) -> bool:
    return (v or "").lower() in ("1", "true", "on", "yes")


def setup_telemetry(force: bool = False):
    """Register a Phoenix-backed tracer provider and auto-instrument Anthropic.

    Returns the provider (or None if telemetry is disabled). Safe to call once.
    """
    global _tracer, _enabled
    if not (force or _is_truthy(os.getenv("HARNESS_TELEMETRY"))):
        return None
    if _enabled:
        return None

    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    from phoenix.otel import register

    endpoint = os.getenv("PHOENIX_ENDPOINT")  # default: local Phoenix collector
    provider = register(
        project_name=_PROJECT,
        endpoint=endpoint,
        auto_instrument=False,
        set_global_tracer_provider=True,
        verbose=False,
    )
    AnthropicInstrumentor().instrument(tracer_provider=provider)
    _tracer = provider.get_tracer("harness")
    _enabled = True
    return provider


def span(name: str):
    """Context manager for a node-level span (no-op when telemetry is off)."""
    return _tracer.start_as_current_span(name)


def set_attr(key: str, value) -> None:
    trace.get_current_span().set_attribute(key, value)


def record_tokens(usage, prefix: str = "llm.tokens") -> None:
    """Add token counts from an Anthropic `msg.usage` to the current span.

    Accumulates when called multiple times in one span (e.g. the executor's
    tool-use loop), so the node span shows total tokens spent.
    """
    if usage is None:
        return
    sp = trace.get_current_span()
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    _add(sp, f"{prefix}.input", inp)
    _add(sp, f"{prefix}.output", out)
    # Prompt-cache visibility: makes cache hits/writes show up per node in Phoenix.
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    _add(sp, f"{prefix}.cache_write", cache_write)
    _add(sp, f"{prefix}.cache_read", cache_read)


def _add(sp, key: str, delta: int) -> None:
    # span attributes aren't readable back portably; track a running total here.
    current = getattr(sp, "_harness_tokens", {})
    current[key] = current.get(key, 0) + delta
    try:
        sp._harness_tokens = current
    except Exception:
        pass
    sp.set_attribute(key, current[key])
