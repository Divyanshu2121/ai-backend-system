"""
SQLAlchemy ORM models.
All models inherit from Base and use UUIDs as primary keys.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Users & Auth ─────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("admin", "user", "analyst", name="user_role"),
        default="user",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    datasets: Mapped[list["Dataset"]] = relationship("Dataset", back_populates="owner")
    queries: Mapped[list["QueryLog"]] = relationship("QueryLog", back_populates="user")
    feedback: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Dataset & Schema ──────────────────────────────────────────────────────────


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(
        Enum("csv", "json", "api", "xlsx", name="source_type"), nullable=False
    )
    file_path: Mapped[str | None] = mapped_column(String(512))
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_count: Mapped[int | None] = mapped_column(Integer)
    raw_schema: Mapped[dict | None] = mapped_column(JSON)       # Detected column types
    generated_schema: Mapped[dict | None] = mapped_column(JSON) # Optimized DB schema
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "ready", "error", name="dataset_status"),
        default="pending",
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="datasets")
    table_schemas: Mapped[list["GeneratedTable"]] = relationship(
        "GeneratedTable", back_populates="dataset", cascade="all, delete-orphan"
    )
    insights: Mapped[list["Insight"]] = relationship("Insight", back_populates="dataset")
    queries: Mapped[list["QueryLog"]] = relationship("QueryLog", back_populates="dataset")

    __table_args__ = (Index("ix_datasets_owner_status", "owner_id", "status"),)


class GeneratedTable(Base):
    """Represents an auto-generated database table from a dataset."""
    __tablename__ = "generated_tables"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    columns: Mapped[list] = mapped_column(JSON, nullable=False)    # List of column defs
    indexes: Mapped[list] = mapped_column(JSON, default=list)
    foreign_keys: Mapped[list] = mapped_column(JSON, default=list)
    sqlalchemy_model_code: Mapped[str | None] = mapped_column(Text)  # Auto-generated code
    is_created: Mapped[bool] = mapped_column(Boolean, default=False)  # Actually in DB?
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="table_schemas")


# ── AI Insights & Queries ─────────────────────────────────────────────────────


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    insight_type: Mapped[str] = mapped_column(
        Enum("summary", "trend", "anomaly", "recommendation", name="insight_type"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    insight_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)   # Charts data, numbers, etc.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    model_used: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="insights")


class QueryLog(Base):
    """Tracks all natural-language queries for feedback loops."""
    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    natural_language_query: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    sql_result: Mapped[dict | None] = mapped_column(JSON)
    execution_time_ms: Mapped[float | None] = mapped_column(Float)
    was_successful: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="queries")
    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="queries")
    feedback: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="query")

    __table_args__ = (Index("ix_query_logs_user_date", "user_id", "created_at"),)


class Feedback(Base):
    """User feedback on AI responses — drives the improvement loop."""
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    query_id: Mapped[str | None] = mapped_column(ForeignKey("query_logs.id", ondelete="SET NULL"))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–5
    comment: Mapped[str | None] = mapped_column(Text)
    was_helpful: Mapped[bool | None] = mapped_column(Boolean)
    suggested_improvement: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="feedback")
    query: Mapped["QueryLog"] = relationship("QueryLog", back_populates="feedback")


# ── Prompt Templates ──────────────────────────────────────────────────────────


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(
        Enum("insight", "sql_gen", "summary", "schema", name="prompt_category"),
        nullable=False,
    )
    template: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    performance_score: Mapped[float | None] = mapped_column(Float)  # Avg feedback rating
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── API Usage Tracking ────────────────────────────────────────────────────────


class APIUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_api_logs_endpoint_date", "endpoint", "created_at"),)
