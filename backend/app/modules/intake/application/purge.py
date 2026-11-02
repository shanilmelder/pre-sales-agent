"""Registers intake' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.intake.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 80
"""Intake rows reference nothing outside intake."""

register_step("intake", ORDER, purge.purge_opportunity, tables=purge.TABLES)
