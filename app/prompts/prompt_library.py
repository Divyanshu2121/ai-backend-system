"""
Prompt Engineering Module
─────────────────────────
Central registry of reusable, versioned prompt templates.
All LLM calls in the system go through this module so prompts are
consistent, testable, and improvable without touching service code.
"""

from dataclasses import dataclass, field
from string import Template
from typing import Any


@dataclass
class PromptTemplate:
    name: str
    category: str
    version: str
    system_prompt: str
    user_template: str   # Uses $variable substitution
    max_tokens: int = 1024
    temperature: float = 0.1

    def render(self, **kwargs: Any) -> str:
        try:
            return Template(self.user_template).substitute(**kwargs)
        except KeyError as exc:
            raise ValueError(f"Missing template variable: {exc}") from exc


# ── Template Registry ─────────────────────────────────────────────────────────


class PromptLibrary:
    """
    Central store for all prompt templates.
    Templates are versioned so we can A/B test improvements.
    """

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._register_defaults()

    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            raise ValueError(f"Unknown prompt template: {name!r}")
        return self._templates[name]

    def register(self, template: PromptTemplate) -> None:
        self._templates[template.name] = template

    def list_templates(self) -> list[dict[str, str]]:
        return [
            {"name": t.name, "category": t.category, "version": t.version}
            for t in self._templates.values()
        ]

    def _register_defaults(self) -> None:

        # ── SQL Generation ────────────────────────────────────────────────────
        self.register(PromptTemplate(
            name="nl_to_sql",
            category="sql_gen",
            version="2.1.0",
            system_prompt="""You are an expert SQL engineer. Your ONLY job is to convert
natural language questions into valid, optimized PostgreSQL SQL queries.

Rules:
- Output ONLY the SQL query, nothing else.
- Never include explanations, markdown, or backticks in your answer.
- Use proper table and column names from the schema provided.
- Add LIMIT clause when fetching rows (default 100 unless specified).
- Prefer CTEs over nested subqueries for readability.
- Always handle NULLs safely (use COALESCE or IS NULL checks).
- Use lowercase SQL keywords.
- Never use SELECT * — always name columns explicitly.""",
            user_template="""Database schema:
$schema

User question: $question

Generate a PostgreSQL SQL query. Output only the SQL, no explanation.""",
            max_tokens=512,
            temperature=0.0,
        ))

        # ── SQL Explanation ───────────────────────────────────────────────────
        self.register(PromptTemplate(
            name="sql_explain",
            category="sql_gen",
            version="1.0.0",
            system_prompt="""You are a data analyst explaining SQL queries to non-technical users.
Use simple language. Be concise. Use bullet points for steps.""",
            user_template="""Explain what this SQL query does in plain English:

```sql
$sql
```

Provide a 2-3 sentence summary followed by bullet points for each major step.""",
            max_tokens=400,
            temperature=0.3,
        ))

        # ── Data Summary ──────────────────────────────────────────────────────
        self.register(PromptTemplate(
            name="data_summary",
            category="insight",
            version="1.2.0",
            system_prompt="""You are a senior data analyst generating executive-level
dataset summaries. Be specific, cite numbers, and highlight what matters most.
Use markdown formatting with headers and bullet points.""",
            user_template="""Analyze this dataset and provide an executive summary:

Dataset: $dataset_name
Rows: $row_count
Columns: $column_count

Column details:
$column_info

Sample statistics:
$statistics

Provide:
1. A 2-3 sentence overview
2. Key data quality observations
3. Most interesting patterns or distributions
4. Top 3 business insights
5. Recommended next steps for analysis""",
            max_tokens=1500,
            temperature=0.3,
        ))

        # ── Trend Analysis ────────────────────────────────────────────────────
        self.register(PromptTemplate(
            name="trend_analysis",
            category="insight",
            version="1.1.0",
            system_prompt="""You are a business intelligence analyst specializing in
trend detection. Focus on quantified changes, seasonality, and anomalies.
Always cite specific numbers and percentages.""",
            user_template="""Analyze trends in this dataset:

Dataset: $dataset_name
Time column: $time_column
Metrics analyzed: $metrics

Data summary:
$data_summary

Identify:
1. Primary trends (growth/decline rates with percentages)
2. Seasonality patterns if present
3. Anomalies or outliers
4. Inflection points
5. Forecast direction (qualitative)

Format as a structured business report.""",
            max_tokens=2000,
            temperature=0.2,
        ))

        # ── Anomaly Detection ─────────────────────────────────────────────────
        self.register(PromptTemplate(
            name="anomaly_detection",
            category="insight",
            version="1.0.0",
            system_prompt="""You are a data quality specialist focused on detecting
anomalies, inconsistencies, and data integrity issues. Be specific about
the rows or values that are suspicious.""",
            user_template="""Analyze this data for anomalies and quality issues:

Dataset: $dataset_name
Statistics per column:
$column_stats

Outlier summary:
$outlier_data

Identify:
1. Statistical outliers (values > 3 std deviations)
2. Data inconsistencies (e.g. dates in the future, negative ages)
3. Suspicious patterns (sudden spikes, missing ranges)
4. Data quality score (0-100) with justification
5. Recommended data cleaning actions""",
            max_tokens=1500,
            temperature=0.1,
        ))

        # ── Schema Optimization ───────────────────────────────────────────────
        self.register(PromptTemplate(
            name="schema_optimization",
            category="schema",
            version="1.0.0",
            system_prompt="""You are a database architect specializing in PostgreSQL
performance optimization. Your recommendations must be specific and actionable.""",
            user_template="""Review this database schema and suggest optimizations:

Table: $table_name
Columns: $columns
Expected row count: $row_count
Query patterns: $query_patterns

Provide:
1. Normalization recommendations (3NF issues)
2. Index strategy (which indexes to add and why)
3. Data type optimizations
4. Partitioning recommendation if applicable
5. Missing constraints (CHECK, FK, etc.)

Be specific and prioritized.""",
            max_tokens=1200,
            temperature=0.1,
        ))

        # ── Business Recommendations ──────────────────────────────────────────
        self.register(PromptTemplate(
            name="business_recommendations",
            category="insight",
            version="1.0.0",
            system_prompt="""You are a business consultant with expertise in data-driven
decision making. Focus on actionable recommendations backed by the data.""",
            user_template="""Based on this data analysis, provide business recommendations:

Business context: $business_context
Dataset: $dataset_name

Key metrics:
$key_metrics

Insights already found:
$existing_insights

Provide 5 specific, actionable business recommendations.
For each recommendation:
- What to do
- Why (data evidence)
- Expected impact
- Priority (High/Medium/Low)""",
            max_tokens=2000,
            temperature=0.4,
        ))


# Module-level singleton
prompt_library = PromptLibrary()
