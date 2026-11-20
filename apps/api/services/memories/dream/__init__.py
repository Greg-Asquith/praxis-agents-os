# apps/api/services/memories/dream/__init__.py

"""Background learning from finished conversations (internally, "dreaming")."""

from services.memories.dream.apply_dream_operations import apply_dream_operations

__all__ = ["apply_dream_operations"]
