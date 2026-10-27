"""
Re-export module for license router.
Provides path compatibility for backend/app/api/license.py.
"""
from app.routers.license import (
    router,
    verify_device_access,
    verify_review_access,
    get_license_status,
    activate_access_key,
)

__all__ = [
    "router",
    "verify_device_access",
    "verify_review_access",
    "get_license_status",
    "activate_access_key",
]
