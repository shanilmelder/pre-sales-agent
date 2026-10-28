"""Registers assessments' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.assessments.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 50
"""Assessments reference workflow runs and registry configs by id only."""

register_step("assessments", ORDER, purge.purge_opportunity, tables=purge.TABLES)
