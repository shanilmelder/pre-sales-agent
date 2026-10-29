"""Registers estimates' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.estimates.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 60
"""Before `opportunities` (Baselines reference the Opportunity row by foreign key)."""

register_step("estimates", ORDER, purge.purge_opportunity, tables=purge.TABLES)
