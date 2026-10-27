"""
Re-export module for feedback router.
Provides path compatibility for backend/app/api/feedback.py.
"""
from app.routers.feedback import router, submit_feedback

__all__ = ["router", "submit_feedback"]
