# apps/api/integrations/outlook_mail/entity_resolvers/__init__.py

from .attachment import OUTLOOK_ATTACHMENT_RESOLVER
from .message import OUTLOOK_MESSAGE_RESOLVER

__all__ = ["OUTLOOK_ATTACHMENT_RESOLVER", "OUTLOOK_MESSAGE_RESOLVER"]
