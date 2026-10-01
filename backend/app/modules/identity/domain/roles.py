"""Platform roles. Roles live in `identity`, not in Auth0 RBAC."""

from enum import StrEnum


class Role(StrEnum):
    PRESALES_ENGINEER = "presales_engineer"
    SALES_REPRESENTATIVE = "sales_representative"
    ENGINEERING_REVIEWER = "engineering_reviewer"
    PM_REVIEWER = "pm_reviewer"
    SECURITY_REVIEWER = "security_reviewer"
    COMMERCIAL = "commercial"
    DELIVERY_MANAGER = "delivery_manager"
    HEAD_OF_DELIVERY = "head_of_delivery"
    PLATFORM_ADMINISTRATOR = "platform_administrator"
