# apps/api/services/embeddings/providers/__init__.py

"""Concrete embedding provider implementations.

Import each provider from its own module. The package doesn't re-export them,
so loading one provider's SDK never loads the others.
"""
