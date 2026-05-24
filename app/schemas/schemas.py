"""
Pydantic v2 schemas for API request/response validation.
Separated from ORM models following clean architecture.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Base ──────────────────────────────────────────────────────────────────────


class APIResponse(BaseModel):
    success: bool = True
    message: str | None = None


class PaginatedResponse(APIResponse):
    total: int
    page: int
    page_size: int
    pages: int
    data: list[Any]


# ── Auth ──────────────────────────────────────────────────────────────────────


class UserRegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserWithTokenResponse(APIResponse):
    user: UserResponse
    tokens: TokenResponse


# ── Dataset ───────────────────────────────────────────────────────────────────


class DatasetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)


class DatasetResponse(BaseModel):
    id: str
    name: str
    description: str | None
    source_type: str
    row_count: int | None
    column_count: int | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetDetailResponse(DatasetResponse):
    raw_schema: dict | None
    generated_schema: dict | None
    file_path: str | None


class ColumnInfo(BaseModel):
    name: str
    detected_type: str
    suggested_db_type: str
    nullable: bool
    unique_ratio: float
    null_ratio: float
    sample_values: list[Any]
    statistics: dict[str, Any] | None = None


class SchemaAnalysisResponse(APIResponse):
    dataset_id: str
    columns: list[ColumnInfo]
    detected_relationships: list[dict[str, Any]]
    recommendations: list[str]


class GeneratedTableResponse(BaseModel):
    id: str
    table_name: str
    columns: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    sqlalchemy_model_code: str | None
    is_created: bool

    model_config = {"from_attributes": True}


# ── AI Insights ───────────────────────────────────────────────────────────────


class InsightRequest(BaseModel):
    insight_type: str = Field(
        default="summary",
        pattern="^(summary|trend|anomaly|recommendation)$",
    )
    custom_prompt: str | None = Field(None, max_length=500)
    max_tokens: int = Field(default=1024, ge=100, le=4096)


class InsightResponse(BaseModel):
    id: str
    dataset_id: str
    insight_type: str
    content: str
    metadata: dict | None = Field(default=None, validation_alias="insight_metadata")
    model_used: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Natural Language Query ────────────────────────────────────────────────────


class NLQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    dataset_id: str
    explain: bool = False   # If true, also return SQL explanation
    max_rows: int = Field(default=100, ge=1, le=1000)


class NLQueryResponse(APIResponse):
    query_id: str
    natural_language: str
    generated_sql: str
    explanation: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float


# ── Feedback ──────────────────────────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    query_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)
    was_helpful: bool | None = None
    suggested_improvement: str | None = Field(None, max_length=500)


class FeedbackResponse(BaseModel):
    id: str
    rating: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Prompt Templates ──────────────────────────────────────────────────────────


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., pattern="^(insight|sql_gen|summary|schema)$")
    template: str = Field(..., min_length=10)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    category: str
    version: str
    is_active: bool
    performance_score: float | None
    usage_count: int

    model_config = {"from_attributes": True}


# ── Monitoring ────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
    timestamp: datetime


class UsageStatsResponse(APIResponse):
    total_datasets: int
    total_queries: int
    avg_query_time_ms: float
    successful_query_rate: float
    top_endpoints: list[dict[str, Any]]
    ai_usage: dict[str, Any]
