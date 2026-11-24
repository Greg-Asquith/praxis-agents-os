# apps/api/custom/routes/__init__.py

"""Deployment route registry, served under the `/custom` API prefix."""

from fastapi import APIRouter

router = APIRouter(tags=["custom"])
