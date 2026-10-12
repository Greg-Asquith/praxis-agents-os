# apps/renderer/media/__main__.py

"""Starts the media renderer."""

from driver.server import serve

from media.operations import OPERATIONS

serve(OPERATIONS)
