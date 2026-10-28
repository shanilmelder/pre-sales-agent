"""Registers conflicts' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.conflicts.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 40
"""Conflicts reference Assessments and Estimate Versions by id only (no foreign key)."""

register_step("conflicts", ORDER, purge.purge_opportunity, tables=purge.TABLES)
