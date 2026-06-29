# apps/api/core/exceptions/_problem.py

"""Shared helpers for RFC 7807 problem-details construction."""

# Top-level problem keys that must not be overwritten by per-error `details`.
PROBLEM_RESERVED_KEYS: frozenset[str] = frozenset({"type", "status", "title", "detail"})
