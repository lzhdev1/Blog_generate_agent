"""Additive access-control tables; existing accounts and manuscripts need no column changes."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String

from .session import Base


class WindowCounter(Base):
    __tablename__ = "usage_window"
    scope = Column(String(32), primary_key=True)
    subject = Column(String(64), primary_key=True)
    window = Column(BigInteger, primary_key=True)
    used = Column(Integer, nullable=False)
    expires = Column(BigInteger, nullable=False, index=True)


class EmailChallenge(Base):
    __tablename__ = "email_challenge"
    email = Column(String(128), primary_key=True)
    digest = Column(String(64), nullable=False)
    expires = Column(BigInteger, nullable=False, index=True)
    failures = Column(Integer, default=0, nullable=False)


class SessionVersion(Base):
    __tablename__ = "account_session_version"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, default=0, nullable=False)


class SavedMedia(Base):
    __tablename__ = "saved_article_media"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    filename = Column(String(180), primary_key=True)
