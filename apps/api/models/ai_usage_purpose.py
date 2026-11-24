# apps/api/models/ai_usage_purpose.py

"""What AI usage can be recorded for, with the name the usage page shows."""

from sqlalchemy import Column, String

from models.base import Base


class AIUsagePurpose(Base):
    """One usage purpose. Core and each deployment's app migrations add their own rows."""

    __tablename__ = "ai_usage_purposes"

    key = Column(String(64), primary_key=True)
    label = Column(String(100), nullable=False)
