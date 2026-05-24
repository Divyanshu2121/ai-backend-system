import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.db.session import get_db
from app.models.models import Insight, QueryLog, User
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.schemas import (
    APIResponse,
    FeedbackRequest,
    FeedbackResponse,
    InsightRequest,
    InsightResponse,
    NLQueryRequest,
    NLQueryResponse,
)
from app.services.ai.feedback_service import FeedbackService
from app.services.ai.insight_engine import AIInsightEngine
from app.services.ai.nl_query_engine import NLQueryEngine
from app.services.auth.auth_service import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Intelligence"])

_insight_engine = AIInsightEngine()


@router.post(
    "/datasets/{dataset_id}/insights",
    response_model=InsightResponse,
    summary="Generate AI-powered insights from a dataset",
)
async def generate_insight(
    dataset_id: str,
    payload: InsightRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsightResponse:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    if not dataset.raw_schema:
        raise NotFoundError("Dataset schema not available — ensure ingestion completed")

    insight_type = payload.insight_type

    if insight_type == "summary":
        llm_result = await _insight_engine.generate_summary(
            dataset.name, dataset.raw_schema
        )
    elif insight_type == "trend":
        # Find date-like columns automatically
        columns = dataset.raw_schema.get("columns", [])
        date_cols = [c["name"] for c in columns if "datetime" in c.get("detected_type", "")]
        numeric_cols = [c["name"] for c in columns if "float" in c.get("detected_type", "") or "int" in c.get("detected_type", "")]
        time_col = date_cols[0] if date_cols else "created_at"
        llm_result = await _insight_engine.analyze_trends(
            dataset.name,
            f"Dataset with {dataset.row_count} rows",
            time_col,
            numeric_cols[:5],
        )
    elif insight_type == "anomaly":
        columns = dataset.raw_schema.get("columns", [])
        llm_result = await _insight_engine.detect_anomalies(
            dataset.name, columns, "Outlier detection based on column statistics"
        )
    else:  # recommendation
        llm_result = await _insight_engine.get_business_recommendations(
            dataset_name=dataset.name,
            business_context=payload.custom_prompt or "General business context",
            key_metrics={"rows": dataset.row_count, "columns": dataset.column_count},
            existing_insights=[],
        )

    insight = Insight(
        dataset_id=dataset_id,
        insight_type=insight_type,
        content=llm_result["content"],
        prompt_tokens=llm_result.get("prompt_tokens"),
        completion_tokens=llm_result.get("completion_tokens"),
        model_used=llm_result.get("model"),
    )
    db.add(insight)
    await db.flush()
    await db.refresh(insight)

    return InsightResponse.model_validate(insight)


@router.get(
    "/datasets/{dataset_id}/insights",
    response_model=list[InsightResponse],
    summary="List all AI insights for a dataset",
)
async def list_insights(
    dataset_id: str,
    insight_type: str | None = Query(None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InsightResponse]:
    from sqlalchemy import select
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()

    q = (
        select(Insight)
        .where(Insight.dataset_id == dataset_id)
        .order_by(Insight.created_at.desc())
        .limit(limit)
    )
    if insight_type:
        q = q.where(Insight.insight_type == insight_type)

    result = await db.execute(q)
    return [InsightResponse.model_validate(i) for i in result.scalars()]


@router.post(
    "/query",
    response_model=NLQueryResponse,
    summary="Ask a natural language question over your data",
)
async def natural_language_query(
    payload: NLQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NLQueryResponse:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(payload.dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {payload.dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    if not dataset.generated_schema:
        raise NotFoundError("Schema not available — re-upload the dataset")

    engine = NLQueryEngine(db)
    query_result = await engine.execute(
        question=payload.query,
        schema=dataset.generated_schema,
        max_rows=payload.max_rows,
        explain=payload.explain,
    )

    # Log for feedback loop
    query_id = str(uuid.uuid4())
    log = QueryLog(
        id=query_id,
        user_id=current_user.id,
        dataset_id=dataset.id,
        natural_language_query=payload.query,
        generated_sql=query_result["generated_sql"],
        sql_result={
            "columns": query_result["columns"],
            "row_count": query_result["row_count"],
        },
        execution_time_ms=query_result["execution_time_ms"],
        was_successful=True,
        prompt_version="2.1.0",
    )
    db.add(log)
    await db.flush()

    return NLQueryResponse(
        query_id=query_id,
        natural_language=query_result["natural_language"],
        generated_sql=query_result["generated_sql"],
        explanation=query_result["explanation"],
        columns=query_result["columns"],
        rows=query_result["rows"],
        row_count=query_result["row_count"],
        execution_time_ms=query_result["execution_time_ms"],
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit feedback on an AI query response",
)
async def submit_feedback(
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    service = FeedbackService(db)
    feedback = await service.record_feedback(
        user_id=current_user.id,
        query_id=payload.query_id,
        rating=payload.rating,
        comment=payload.comment,
        was_helpful=payload.was_helpful,
        suggested_improvement=payload.suggested_improvement,
    )
    return FeedbackResponse.model_validate(feedback)


@router.get(
    "/feedback/report",
    summary="Get AI performance report based on user feedback (admin only)",
)
async def get_feedback_report(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role != "admin":
        raise AuthorizationError("Admin access required")
    service = FeedbackService(db)
    return await service.get_performance_report(days)
