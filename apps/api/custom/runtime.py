# apps/api/custom/runtime.py

"""Deployment agent tools and job handlers."""


def register_custom_runtime() -> None:
    """Registers the deployment's agent tools and job handlers.

    Runtime catalogue assembly calls this once per process, after core tools and
    enabled providers. Import tool and job handler modules inside this function.
    """
