# apps/api/tests/support/document_conversion_worker.py

"""Document worker handlers whose markdown conversion overruns memory. Loaded only by tests."""

from services.documents.handlers import HANDLERS as PRODUCTION_HANDLERS


def _allocate(*_args):
    bytearray(1024 * 1024 * 1024)
    return {}, None


HANDLERS = {**PRODUCTION_HANDLERS, "to_markdown": _allocate}
