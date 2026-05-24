"""
Feedback Loop System
────────────────────
Stores user feedback on AI responses and surfaces improvement signals.
Tracks prompt version performance to enable data-driven prompt tuning.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import Feedback, PromptTemplate, QueryLog

logger = get_logger(__name__)

# A prompt is flagged for review when its avg rating drops below this
_PERFORMANCE_THRESHOLD = 3.0


class FeedbackService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_feedback(
        self,
        user_id: str,
        query_id: str,
        rating: int,
        comment: str | None = None,
        was_helpful: bool | None = None,
        suggested_improvement: str | None = None,
    ) -> Feedback:
        feedback = Feedback(
            user_id=user_id,
            query_id=query_id,
            rating=rating,
            comment=comment,
            was_helpful=was_helpful,
            suggested_improvement=suggested_improvement,
        )
        self._db.add(feedback)
        await self._db.flush()
        await self._db.refresh(feedback)

        await self._update_prompt_performance(query_id, rating)
        logger.info("Feedback recorded", query_id=query_id, rating=rating)
        return feedback

    async def get_performance_report(
        self, days: int = 30
    ) -> dict[str, Any]:
        """Aggregate feedback stats for the last N days."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self._db.execute(
            select(
                func.avg(Feedback.rating).label("avg_rating"),
                func.count(Feedback.id).label("total_feedback"),
                func.sum(
                    func.cast(Feedback.was_helpful == True, type_=Integer)
                ).label("helpful_count"),
            ).where(Feedback.created_at >= since)
        )
        row = result.one()

        # Get worst performing queries
        bad_queries = await self._db.execute(
            select(QueryLog.natural_language_query, func.avg(Feedback.rating).label("avg"))
            .join(Feedback, Feedback.query_id == QueryLog.id)
            .where(Feedback.created_at >= since)
            .group_by(QueryLog.id, QueryLog.natural_language_query)
            .having(func.avg(Feedback.rating) < _PERFORMANCE_THRESHOLD)
            .order_by(func.avg(Feedback.rating))
            .limit(10)
        )

        return {
            "period_days": days,
            "avg_rating": float(row.avg_rating or 0),
            "total_feedback": row.total_feedback,
            "helpful_rate": (
                (row.helpful_count or 0) / row.total_feedback
                if row.total_feedback
                else 0
            ),
            "low_performing_queries": [
                {"query": q.natural_language_query, "avg_rating": round(float(q.avg), 2)}
                for q in bad_queries
            ],
        }

    async def get_improvement_suggestions(self) -> list[str]:
        """
        Surfaces user-provided improvement suggestions from recent feedback
        to help prompt engineers tune the templates.
        """
        result = await self._db.execute(
            select(Feedback.suggested_improvement)
            .where(
                Feedback.suggested_improvement.isnot(None),
                Feedback.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
                Feedback.rating <= 2,
            )
            .order_by(Feedback.created_at.desc())
            .limit(50)
        )
        return [row.suggested_improvement for row in result if row.suggested_improvement]

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _update_prompt_performance(
        self, query_id: str, rating: int
    ) -> None:
        """Update the performance score on the prompt template used for this query."""
        query_result = await self._db.execute(
            select(QueryLog).where(QueryLog.id == query_id)
        )
        query = query_result.scalar_one_or_none()
        if not query or not query.prompt_version:
            return

        template_result = await self._db.execute(
            select(PromptTemplate).where(
                PromptTemplate.name == "nl_to_sql",
                PromptTemplate.version == query.prompt_version,
            )
        )
        template = template_result.scalar_one_or_none()
        if not template:
            return

        # Exponential moving average: new_score = 0.9 * old + 0.1 * rating
        old_score = template.performance_score or rating
        template.performance_score = round(0.9 * old_score + 0.1 * rating, 3)
        template.usage_count += 1
        await self._db.flush()

        if template.performance_score < _PERFORMANCE_THRESHOLD:
            logger.warning(
                "Prompt template below performance threshold",
                template=template.name,
                version=template.version,
                score=template.performance_score,
            )
