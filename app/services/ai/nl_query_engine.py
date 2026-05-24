"""
Natural Language → SQL Query Engine
────────────────────────────────────
Converts plain-English questions into safe, optimized PostgreSQL queries.
Uses schema context injection and guardrails to prevent SQL injection.
"""

import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AIServiceError, QueryExecutionError
from app.core.logging import get_logger
from app.prompts.prompt_library import prompt_library
from app.services.ai.insight_engine import AIInsightEngine

logger = get_logger(__name__)

# Blocks destructive SQL from the LLM (belt-and-suspenders safety)
_DANGEROUS_PATTERNS = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|INSERT|UPDATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)


class NLQueryEngine:
    """
    Pipeline:
    1. Build schema context string from the dataset's generated schema
    2. Send to LLM via nl_to_sql prompt template
    3. Validate and sanitize returned SQL
    4. Execute against PostgreSQL
    5. Return structured result + log for feedback loop
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._ai = AIInsightEngine()

    async def execute(
        self,
        question: str,
        schema: dict[str, Any],
        max_rows: int = 100,
        explain: bool = False,
    ) -> dict[str, Any]:
        """
        Main entry: question → SQL → result dict.
        """
        schema_context = self._build_schema_context(schema)

        # Generate SQL
        template = prompt_library.get("nl_to_sql")
        user_prompt = template.render(schema=schema_context, question=question)
        llm_result = await self._ai._call_llm(
            template.system_prompt,
            user_prompt,
            max_tokens=template.max_tokens,
            temperature=template.temperature,
        )

        raw_sql = llm_result["content"].strip()
        safe_sql = self._validate_and_sanitize(raw_sql, max_rows)

        # Optionally get explanation
        explanation = None
        if explain:
            explain_template = prompt_library.get("sql_explain")
            explain_result = await self._ai._call_llm(
                explain_template.system_prompt,
                explain_template.render(sql=safe_sql),
                max_tokens=explain_template.max_tokens,
                temperature=explain_template.temperature,
            )
            explanation = explain_result["content"]

        # Execute
        start = time.monotonic()
        rows, columns = await self._execute_sql(safe_sql)
        elapsed_ms = (time.monotonic() - start) * 1000

        return {
            "natural_language": question,
            "generated_sql": safe_sql,
            "explanation": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(elapsed_ms, 2),
            "prompt_tokens": llm_result["prompt_tokens"],
            "completion_tokens": llm_result["completion_tokens"],
            "model_used": llm_result["model"],
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _build_schema_context(self, schema: dict[str, Any]) -> str:
        """Convert generated schema dict into a compact SQL DDL-style string."""
        table = schema.get("table_name", "unknown_table")
        columns = schema.get("columns", [])
        lines = [f"Table: {table}"]
        lines.append("Columns:")
        for col in columns:
            null_str = "NULL" if col.get("nullable") else "NOT NULL"
            lines.append(f"  {col['name']} {col['db_type']} {null_str}")

        indexes = schema.get("indexes", [])
        if indexes:
            lines.append("Indexes:")
            for idx in indexes:
                cols = ", ".join(idx.get("columns", []))
                lines.append(f"  {idx['name']} ON ({cols})")

        return "\n".join(lines)

    def _validate_and_sanitize(self, sql: str, max_rows: int) -> str:
        # Strip any markdown the LLM snuck in
        sql = re.sub(r"```(?:sql)?", "", sql).strip().rstrip(";")

        if _DANGEROUS_PATTERNS.search(sql):
            raise QueryExecutionError(
                "Generated SQL contains disallowed operations. "
                "Only SELECT queries are permitted."
            )

        if not sql.strip().upper().startswith("SELECT"):
            raise QueryExecutionError(
                "Only SELECT queries are allowed via natural language interface."
            )

        # Enforce row limit
        if "LIMIT" not in sql.upper():
            sql = f"{sql}\nLIMIT {max_rows}"

        return sql

    async def _execute_sql(
        self, sql: str
    ) -> tuple[list[list[Any]], list[str]]:
        try:
            result = await self._db.execute(text(sql))
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchall()]
            return rows, columns
        except Exception as exc:
            logger.error("SQL execution failed", sql=sql, error=str(exc))
            raise QueryExecutionError(
                f"Query execution failed: {exc}"
            ) from exc
