"""Vercel Python Function for the health endpoint."""

from app import Handler


class handler(Handler):
    """Serve the health endpoint through Vercel's Python runtime."""
