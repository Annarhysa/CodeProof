"""SQLite storage for evaluations. Simple by design for the hackathon MVP;
schema mirrors what the spec requires to be persisted per evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = Path(__file__).resolve().parents[2] / "codeproof.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class EvaluationRecord(Base):
    __tablename__ = "evaluations"

    id = Column(String, primary_key=True)
    repo_url = Column(String, nullable=False)
    issue_title = Column(String, nullable=False)
    issue_body = Column(String, nullable=False)
    commit_sha = Column(String, nullable=True)
    agent_name = Column(String, nullable=False)

    status = Column(String, nullable=False, default="PENDING")  # PENDING, RUNNING, DONE, ERROR
    verdict = Column(String, nullable=True)  # PASS, FAIL, ABSTAIN
    reason = Column(String, nullable=True)

    reproduction = Column(JSON, nullable=True)
    patch = Column(JSON, nullable=True)
    test_results = Column(JSON, nullable=True)
    evidence = Column(JSON, nullable=True)
    trajectory = Column(JSON, nullable=True)
    error = Column(String, nullable=True)

    human_decision = Column(String, nullable=True)  # APPROVE, REQUEST_REVISION, REJECT, ABSTAIN
    human_notes = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
