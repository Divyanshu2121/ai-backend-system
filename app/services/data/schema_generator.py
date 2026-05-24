"""
Schema Generator
────────────────
Takes the raw column analysis from DataIngestionEngine and produces:
  1. An optimized relational schema with normalization recommendations
  2. Auto-generated SQLAlchemy model Python code
  3. Alembic-compatible migration hints
"""

import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# PostgreSQL reserved words — columns with these names need quoting
_PG_RESERVED = frozenset({
    "user", "table", "column", "index", "select", "from", "where",
    "order", "group", "limit", "offset", "join", "on", "in", "as",
    "is", "not", "and", "or", "null", "true", "false",
})

# Columns that strongly suggest auto-increment integer PKs
_PK_PATTERNS = re.compile(r"^(id|pk|primary_key)$", re.IGNORECASE)

# Columns that suggest foreign keys
_FK_PATTERNS = re.compile(r"_id$|_fk$", re.IGNORECASE)

# Columns likely to need indexing
_INDEX_PATTERNS = re.compile(
    r"(email|username|name|code|status|date|created_at|updated_at|type|category)",
    re.IGNORECASE,
)


class SchemaGenerator:
    """
    Converts raw schema analysis into an optimized database schema.
    """

    def generate(
        self, raw_schema: dict[str, Any], table_name: str
    ) -> dict[str, Any]:
        """
        Returns a complete schema definition dict including:
        - columns: list of column definitions
        - indexes: list of index definitions
        - constraints: uniqueness / FK constraints
        - sqlalchemy_code: ready-to-paste model code
        - recommendations: human-readable advice
        """
        columns = raw_schema.get("columns", [])
        table_name = self._sanitize_name(table_name)

        optimized_columns = [self._optimize_column(col) for col in columns]
        pk_column = self._identify_primary_key(optimized_columns, table_name)
        indexes = self._generate_indexes(optimized_columns, table_name)
        constraints = self._generate_constraints(optimized_columns)
        recommendations = self._generate_recommendations(optimized_columns, raw_schema)
        model_code = self._generate_sqlalchemy_model(
            table_name, optimized_columns, pk_column, indexes
        )

        return {
            "table_name": table_name,
            "columns": optimized_columns,
            "primary_key": pk_column,
            "indexes": indexes,
            "constraints": constraints,
            "sqlalchemy_model_code": model_code,
            "recommendations": recommendations,
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _sanitize_name(self, name: str) -> str:
        safe = re.sub(r"[^\w]", "_", name.lower())
        safe = re.sub(r"_+", "_", safe).strip("_")
        if safe[0].isdigit():
            safe = f"t_{safe}"
        return safe

    def _optimize_column(self, col: dict[str, Any]) -> dict[str, Any]:
        name = self._sanitize_name(col["name"])
        if name in _PG_RESERVED:
            name = f"{name}_col"

        db_type = col["suggested_db_type"]
        null_ratio = col.get("null_ratio", 0)
        unique_ratio = col.get("unique_ratio", 0)
        stats = col.get("statistics", {}) or {}

        # Tighten VARCHAR lengths based on observed data
        if db_type.startswith("VARCHAR"):
            avg_len = stats.get("avg_length", 50)
            max_len = 255 if avg_len <= 100 else 512
            db_type = f"VARCHAR({max_len})"

        # Downgrade BIGINT to INTEGER when values are small
        if db_type == "BIGINT":
            max_val = stats.get("max", 0)
            if max_val and max_val < 2_147_483_647:
                db_type = "INTEGER"

        is_fk = bool(_FK_PATTERNS.search(name)) and col.get("is_potential_fk", False)

        return {
            "original_name": col["name"],
            "name": name,
            "db_type": db_type,
            "nullable": bool(null_ratio > 0.0),
            "unique": bool(unique_ratio == 1.0 and null_ratio == 0.0),
            "is_primary_key": bool(col.get("is_potential_pk", False)),
            "is_foreign_key": bool(is_fk),
            "default": None,
            "comment": None,
        }

    def _identify_primary_key(
        self, columns: list[dict], table_name: str
    ) -> str:
        # Prefer an existing candidate
        for col in columns:
            if col["is_primary_key"] and col["name"] == "id":
                return "id"
        # Add synthetic UUID PK — we'll prepend it to the column list
        columns.insert(0, {
            "original_name": "id",
            "name": "id",
            "db_type": "UUID",
            "nullable": False,
            "unique": True,
            "is_primary_key": True,
            "is_foreign_key": False,
            "default": "uuid_generate_v4()",
            "comment": "Auto-generated primary key",
        })
        return "id"

    def _generate_indexes(
        self, columns: list[dict], table_name: str
    ) -> list[dict[str, Any]]:
        indexes = []
        for col in columns:
            if col["is_primary_key"]:
                continue
            if _INDEX_PATTERNS.search(col["name"]) or col["is_foreign_key"]:
                indexes.append({
                    "name": f"ix_{table_name}_{col['name']}",
                    "columns": [col["name"]],
                    "unique": col["unique"] and not col["nullable"],
                })
        return indexes

    def _generate_constraints(
        self, columns: list[dict]
    ) -> list[dict[str, Any]]:
        constraints = []
        unique_cols = [c["name"] for c in columns if c["unique"] and not c["is_primary_key"]]
        for col_name in unique_cols:
            constraints.append({
                "type": "UNIQUE",
                "columns": [col_name],
                "name": f"uq_{col_name}",
            })
        return constraints

    def _generate_recommendations(
        self, columns: list[dict], raw_schema: dict
    ) -> list[str]:
        recs = []
        total = raw_schema.get("total_rows", 0)

        high_null = [c["name"] for c in columns if c.get("null_ratio", 0) > 0.3]
        if high_null:
            recs.append(
                f"Columns with >30% nulls: {', '.join(high_null)}. "
                "Consider making them nullable or using a separate table."
            )

        if total > 1_000_000:
            recs.append(
                "Dataset has >1M rows. Consider partitioning by a date column "
                "and adding BRIN indexes for range queries."
            )

        fk_cols = [c["name"] for c in columns if c["is_foreign_key"]]
        if fk_cols:
            recs.append(
                f"Potential FK columns detected: {', '.join(fk_cols)}. "
                "Review and add explicit FOREIGN KEY constraints."
            )

        text_cols = [c["name"] for c in columns if c["db_type"] == "TEXT"]
        if text_cols:
            recs.append(
                f"TEXT columns {text_cols} — add GIN index if full-text search is needed."
            )

        return recs

    def _generate_sqlalchemy_model(
        self,
        table_name: str,
        columns: list[dict],
        pk_column: str,
        indexes: list[dict],
    ) -> str:
        class_name = "".join(part.title() for part in table_name.split("_"))
        lines = [
            "import uuid",
            "from datetime import datetime",
            "from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, Index",
            "from sqlalchemy.dialects.postgresql import UUID",
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n",
            "class Base(DeclarativeBase):",
            "    pass\n\n",
            f"class {class_name}(Base):",
            f'    __tablename__ = "{table_name}"\n',
        ]

        type_map = {
            "UUID": "UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())",
            "INTEGER": "Integer",
            "BIGINT": "Integer",
            "SMALLINT": "Integer",
            "DOUBLE PRECISION": "Float",
            "REAL": "Float",
            "BOOLEAN": "Boolean, default=False",
            "TEXT": "Text",
            "TIMESTAMP WITH TIME ZONE": "DateTime(timezone=True)",
        }

        for col in columns:
            name = col["name"]
            db_type = col["db_type"]
            nullable = col["nullable"]
            default = col.get("default")

            if col["is_primary_key"] and db_type == "UUID":
                col_def = type_map["UUID"]
            elif db_type in type_map:
                col_def = type_map[db_type]
                if not nullable:
                    col_def = col_def + ", nullable=False"
            elif db_type.startswith("VARCHAR"):
                length = db_type[8:-1]
                nullable_str = "" if nullable else ", nullable=False"
                col_def = f"String({length}){nullable_str}"
            else:
                col_def = "Text"

            lines.append(f"    {name}: Mapped[str] = mapped_column({col_def})")

        if indexes:
            lines.append("\n    __table_args__ = (")
            for idx in indexes:
                cols = ", ".join(f'"{c}"' for c in idx["columns"])
                unique = ", unique=True" if idx.get("unique") else ""
                lines.append(f'        Index("{idx["name"]}", {cols}{unique}),')
            lines.append("    )")

        return "\n".join(lines)
