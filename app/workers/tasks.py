"""
Background Task Definitions
────────────────────────────
All Celery tasks. Each task uses its own sync DB session
(Celery workers are sync by default; async support requires extra config).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="app.workers.tasks.process_large_dataset",
)
def process_large_dataset(self, dataset_id: str, file_path: str) -> dict[str, Any]:
    """
    Process a large dataset in the background.
    Triggered when file size exceeds the synchronous processing threshold.
    """
    logger.info("Starting background dataset processing", dataset_id=dataset_id)
    try:
        result = _run_async(_process_dataset_async(dataset_id, file_path))
        logger.info("Dataset processing complete", dataset_id=dataset_id)
        return result
    except Exception as exc:
        logger.error("Dataset processing failed", dataset_id=dataset_id, error=str(exc))
        raise self.retry(exc=exc)


async def _process_dataset_async(dataset_id: str, file_path: str) -> dict[str, Any]:
    from app.db.session import get_db_context
    from app.models.models import Dataset
    from app.repositories.dataset_repository import DatasetRepository
    from app.services.data.ingestion_engine import DataIngestionEngine
    from app.services.data.schema_generator import SchemaGenerator
    from pathlib import Path

    engine = DataIngestionEngine()
    generator = SchemaGenerator()

    async with get_db_context() as db:
        repo = DatasetRepository(db)
        dataset = await repo.get_by_id(dataset_id)
        if not dataset:
            return {"error": "Dataset not found"}

        dataset.status = "processing"
        await repo.update(dataset)

        try:
            file_bytes = Path(file_path).read_bytes()
            result = await engine.ingest_file(file_bytes, Path(file_path).name, dataset.name)
            generated_schema = generator.generate(result["raw_schema"], dataset.name)

            dataset.row_count = result["row_count"]
            dataset.column_count = result["column_count"]
            dataset.raw_schema = result["raw_schema"]
            dataset.generated_schema = generated_schema
            dataset.status = "ready"
            await repo.update(dataset)

            return {"status": "ready", "rows": result["row_count"]}
        except Exception as exc:
            dataset.status = "error"
            dataset.error_message = str(exc)
            await repo.update(dataset)
            raise


@celery_app.task(name="app.workers.tasks.generate_scheduled_insights")
def generate_scheduled_insights(dataset_id: str, insight_type: str = "summary") -> dict:
    """Auto-generate insights for a dataset on a schedule."""
    logger.info("Generating scheduled insight", dataset_id=dataset_id, type=insight_type)
    return _run_async(_generate_insight_async(dataset_id, insight_type))


async def _generate_insight_async(dataset_id: str, insight_type: str) -> dict:
    from app.db.session import get_db_context
    from app.models.models import Insight
    from app.repositories.dataset_repository import DatasetRepository
    from app.services.ai.insight_engine import AIInsightEngine

    ai_engine = AIInsightEngine()

    async with get_db_context() as db:
        repo = DatasetRepository(db)
        dataset = await repo.get_by_id(dataset_id)
        if not dataset or not dataset.raw_schema:
            return {"error": "Dataset not ready"}

        llm_result = await ai_engine.generate_summary(dataset.name, dataset.raw_schema)

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
        return {"insight_id": insight.id}


@celery_app.task(name="app.workers.tasks.cleanup_old_logs")
def cleanup_old_logs(days_to_keep: int = 90) -> dict[str, int]:
    """Delete API usage logs older than N days to control DB size."""
    return _run_async(_cleanup_logs_async(days_to_keep))


async def _cleanup_logs_async(days_to_keep: int) -> dict[str, int]:
    from sqlalchemy import delete
    from app.db.session import get_db_context
    from app.models.models import APIUsageLog

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    async with get_db_context() as db:
        result = await db.execute(
            delete(APIUsageLog).where(APIUsageLog.created_at < cutoff)
        )
        deleted = result.rowcount
        logger.info("Cleaned up old API logs", deleted=deleted, cutoff=cutoff.isoformat())
        return {"deleted": deleted}


@celery_app.task(name="app.workers.tasks.refresh_prompt_scores")
def refresh_prompt_scores() -> dict:
    """Recalculate prompt template performance scores from recent feedback."""
    return _run_async(_refresh_scores_async())


async def _refresh_scores_async() -> dict:
    from sqlalchemy import select, func
    from app.db.session import get_db_context
    from app.models.models import Feedback, PromptTemplate, QueryLog

    async with get_db_context() as db:
        result = await db.execute(
            select(
                QueryLog.prompt_version,
                func.avg(Feedback.rating).label("avg_rating"),
                func.count(Feedback.id).label("count"),
            )
            .join(Feedback, Feedback.query_id == QueryLog.id)
            .where(QueryLog.prompt_version.isnot(None))
            .group_by(QueryLog.prompt_version)
        )
        updated = 0
        for row in result:
            tmpl = await db.execute(
                select(PromptTemplate).where(
                    PromptTemplate.name == "nl_to_sql",
                    PromptTemplate.version == row.prompt_version,
                )
            )
            template = tmpl.scalar_one_or_none()
            if template:
                template.performance_score = round(float(row.avg_rating), 3)
                updated += 1
        return {"updated_templates": updated}
