"""
AI Insight Engine
─────────────────
Uses OpenAI GPT models to generate dataset summaries, trend analysis,
anomaly detection, and business recommendations.
Includes retry logic, token tracking, and prompt versioning.
"""

import json
import time
from typing import Any

from openai import AsyncOpenAI, APIError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import AIServiceError
from app.core.logging import get_logger
from app.prompts.prompt_library import prompt_library

logger = get_logger(__name__)

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    timeout=settings.llm_request_timeout,
    max_retries=0,  # We handle retries with tenacity for better observability
)


class AIInsightEngine:
    """
    Central AI service for all LLM interactions.
    Every method returns a structured dict with content + metadata.
    """

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        response_format: str = "text",
    ) -> dict[str, Any]:
        """
        Core LLM call with retry, token tracking, and error normalization.
        Returns {"content": str, "prompt_tokens": int, "completion_tokens": int, "model": str}
        """
        start = time.monotonic()
        try:
            kwargs: dict[str, Any] = dict(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}

            response = await _client.chat.completions.create(**kwargs)
            elapsed = (time.monotonic() - start) * 1000

            content = response.choices[0].message.content or ""
            usage = response.usage

            logger.info(
                "LLM call completed",
                model=response.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                elapsed_ms=round(elapsed, 1),
            )

            return {
                "content": content,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "model": response.model,
            }

        except RateLimitError:
            logger.warning("OpenAI rate limit hit — retrying")
            raise
        except APIError as exc:
            logger.error("OpenAI API error", error=str(exc))
            raise AIServiceError(f"LLM API error: {exc}") from exc

    # ── Public methods ────────────────────────────────────────────────────────

    async def generate_summary(
        self, dataset_name: str, raw_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a comprehensive dataset summary."""
        template = prompt_library.get("data_summary")
        columns = raw_schema.get("columns", [])

        column_info = "\n".join(
            f"  - {c['name']}: {c['detected_type']} "
            f"(null: {c['null_ratio']:.0%}, unique: {c['unique_ratio']:.0%})"
            for c in columns
        )

        # Build statistics block for numeric columns
        stats_lines = []
        for col in columns:
            stats = col.get("statistics")
            if stats and "mean" in stats:
                stats_lines.append(
                    f"  - {col['name']}: mean={stats['mean']:.2f}, "
                    f"min={stats['min']:.2f}, max={stats['max']:.2f}"
                )
        statistics = "\n".join(stats_lines) or "No numeric statistics available"

        user_prompt = template.render(
            dataset_name=dataset_name,
            row_count=raw_schema.get("total_rows", "unknown"),
            column_count=raw_schema.get("total_columns", len(columns)),
            column_info=column_info,
            statistics=statistics,
        )

        return await self._call_llm(
            template.system_prompt,
            user_prompt,
            max_tokens=template.max_tokens,
            temperature=template.temperature,
        )

    async def analyze_trends(
        self,
        dataset_name: str,
        data_summary: str,
        time_column: str,
        metrics: list[str],
    ) -> dict[str, Any]:
        """Analyze time-series trends in the dataset."""
        template = prompt_library.get("trend_analysis")
        user_prompt = template.render(
            dataset_name=dataset_name,
            time_column=time_column,
            metrics=", ".join(metrics),
            data_summary=data_summary,
        )
        return await self._call_llm(
            template.system_prompt,
            user_prompt,
            max_tokens=template.max_tokens,
            temperature=template.temperature,
        )

    async def detect_anomalies(
        self,
        dataset_name: str,
        column_stats: list[dict],
        outlier_data: str,
    ) -> dict[str, Any]:
        template = prompt_library.get("anomaly_detection")
        col_stats_str = json.dumps(column_stats, indent=2, default=str)
        user_prompt = template.render(
            dataset_name=dataset_name,
            column_stats=col_stats_str,
            outlier_data=outlier_data,
        )
        return await self._call_llm(
            template.system_prompt,
            user_prompt,
            max_tokens=template.max_tokens,
            temperature=template.temperature,
        )

    async def get_business_recommendations(
        self,
        dataset_name: str,
        business_context: str,
        key_metrics: dict[str, Any],
        existing_insights: list[str],
    ) -> dict[str, Any]:
        template = prompt_library.get("business_recommendations")
        user_prompt = template.render(
            dataset_name=dataset_name,
            business_context=business_context,
            key_metrics=json.dumps(key_metrics, indent=2, default=str),
            existing_insights="\n".join(f"- {i}" for i in existing_insights),
        )
        return await self._call_llm(
            template.system_prompt,
            user_prompt,
            max_tokens=template.max_tokens,
            temperature=template.temperature,
        )

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a vector embedding for semantic search / RAG."""
        try:
            response = await _client.embeddings.create(
                model=settings.openai_embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except APIError as exc:
            raise AIServiceError(f"Embedding generation failed: {exc}") from exc
