"""Registers workflows' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.workflows.adapters import purge
from app.platform.purge.registry import register_run_ids, register_step

ORDER = 100
"""After the modules whose rows name runs by id; the run ids were collected before any step."""

register_step("workflows", ORDER, purge.purge_opportunity, tables=purge.TABLES)
register_run_ids(purge.run_ids)
