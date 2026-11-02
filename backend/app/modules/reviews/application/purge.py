"""Registers reviews' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.reviews.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 20
"""Review Requests reference Estimate Versions and Assessments by id only (no foreign key)."""

register_step("reviews", ORDER, purge.purge_opportunity, tables=purge.TABLES)
