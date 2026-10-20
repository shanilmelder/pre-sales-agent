"""The NOTIFY channel of the per-Opportunity event stream (AD-30).

Every notification on it carries ids only: `{event_id?, opportunity_id, source}`. The
stream (`workflows.application.events`) re-reads the row and authorizes it per subscriber.
"""

EVENTS_CHANNEL = "psa_events"
"""The Postgres NOTIFY channel shared by the trace writer, workflows and gaps."""
TRACE_SOURCE = "trace"
"""`source` of a notification about a `platform_trace_events` row."""

__all__ = ["EVENTS_CHANNEL", "TRACE_SOURCE"]
