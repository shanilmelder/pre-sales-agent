"""The `workflows` module (Story 5.2): Workflow Runs, their plans and tasks, and progress.

It owns runs and tasks (moved from `assessments`, tables renamed in place) and its commands
are the only writers of their status: queueing a run (Run assessment, or after a Gap
detection), retrying a task, cancelling, and the `workflows.execute` job, which hands the
run to the graph runner the worker installs (`app.orchestration`: one LangGraph node per
task, checkpointed with `thread_id = run_id`). Each task start and end and each run queueing
and end writes a `workflows_progress` row, streamed per Opportunity over Server-Sent Events
(`GET /api/v1/opportunities/{id}/events`) and pruned after 30 days.

Other modules use it only through `application/public.py`.
"""
