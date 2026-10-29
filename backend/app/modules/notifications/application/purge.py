"""Registers notifications' retention purge step (Story 10.6). Imported by the worker only
(`app.main_worker`), which runs the `platform.purge` job."""

from app.modules.notifications.adapters import purge
from app.platform.purge.registry import register_step

ORDER = 10
"""Inbox items reference nothing; any order works."""

register_step("notifications", ORDER, purge.purge_opportunity, tables=purge.TABLES)
