"""
SQLAlchemy Declarative Base for all FastAPI microservice models in RT-FADS.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass
