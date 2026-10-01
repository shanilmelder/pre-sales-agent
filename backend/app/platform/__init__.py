"""Shared platform layer: config, errors, logging, db (and later uow, trace, jobs,
idempotency, model_gateway, tool_gateway, storage, telemetry).

`platform` never depends on business modules, orchestration or agents.
"""
