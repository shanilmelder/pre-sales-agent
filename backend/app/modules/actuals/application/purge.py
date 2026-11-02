"""Registers actuals' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.actuals.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 30
"""Before `opportunities` (its tables reference the Opportunity row by foreign key)."""

register_step("actuals", ORDER, purge.purge_opportunity, tables=purge.TABLES)
