"""Registers gaps' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.gaps.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 70
"""Gaps reference Requirements and passages by id only (no foreign key)."""

register_step("gaps", ORDER, purge.purge_opportunity, tables=purge.TABLES)
