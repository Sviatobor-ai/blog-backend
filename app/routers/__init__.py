"""Application routers package."""

from .admin_api import admin_api_router
from .admin_page import admin_page_router

__all__ = ["admin_api_router", "admin_page_router"]
