"""The controlled retention purge (Story 10.6).

- `registry` — what modules register: their purge steps, the retention selector and run ids.
- `history` — the recent `platform.purge.completed` events (Admin > Retention).
- `job` — the daily `platform.purge` job, the only code that deletes Opportunity data. Only
  the worker imports it (an import-linter contract keeps it out of the api process).
"""
