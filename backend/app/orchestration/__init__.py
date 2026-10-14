"""LangGraph graphs and thin node wrappers (AD-5, AD-6, AD-7; Story 5.2).

This is the only package allowed to import `langgraph`, and only the `worker` process
imports it (the `api` never does: import-linter contract). Nodes drive business modules only
through their `application/public.py`.

- `graph`: builds a Workflow Run's graph from its plan (one node per task, edges from the
  tasks it `requires`) and the node wrapper.
- `executors`: per Agent, how a node loads its inputs, calls the Agent and submits the
  result (the specialist Agents' executors).
- `checkpointer`: the Postgres checkpointer on its own connection pool.
- `runner`: resumes a run's thread, or starts it again, and returns its tasks' errors; the
  worker installs it as `workflows`' graph runner.
"""

import os

# Checkpoint deserialization is restricted to known types (AD-6). Read by langgraph at
# import, so it is set before any submodule imports it.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
