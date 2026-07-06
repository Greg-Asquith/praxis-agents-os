# apps/api/models/__init__.py

"""
SQLAlchemy model registry.

All models must be imported here to ensure they are registered with SQLAlchemy's
mapper before any relationships are resolved. This prevents errors like:
"name 'SomeModel' is not defined" when using string references in relationships.
"""

# All models must be imported to register them with SQLAlchemy's mapper.
# base is imported indirectly by every model module; listed here explicitly for clarity.
from models.agent import Agent, AgentSchedule, AgentScheduleRun  # noqa: F401
from models.agent_run import AgentRun  # noqa: F401
from models.audit_event import AuditEvent  # noqa: F401
from models.base import BaseModel  # noqa: F401
from models.conversation import Conversation, ConversationMessage  # noqa: F401
from models.conversation_todos import ConversationTodoList  # noqa: F401
from models.jobs import Job  # noqa: F401
from models.notification import Notification  # noqa: F401
from models.rate_limiting import RateLimitAttempt  # noqa: F401
from models.security import SecurityEvent  # noqa: F401
from models.session import Session  # noqa: F401
from models.skills import Skill  # noqa: F401
from models.user import PasswordResetToken, User, UserAuth  # noqa: F401
from models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership  # noqa: F401
