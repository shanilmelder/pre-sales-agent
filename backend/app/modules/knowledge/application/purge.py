"""Registers knowledge' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.knowledge.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 90
"""Snapshots reference workflow runs and tasks by id only."""

register_step("knowledge", ORDER, purge.purge_opportunity, tables=purge.TABLES)
