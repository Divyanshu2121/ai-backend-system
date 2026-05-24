"""
Unit Tests
──────────
Tests for core business logic without requiring a live database or OpenAI API.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.data.ingestion_engine import DataIngestionEngine
from app.services.data.schema_generator import SchemaGenerator
from app.prompts.prompt_library import PromptLibrary, PromptTemplate


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ingestion_engine() -> DataIngestionEngine:
    return DataIngestionEngine()


@pytest.fixture
def schema_generator() -> SchemaGenerator:
    return SchemaGenerator()


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return b"""order_id,product,quantity,price,order_date,status
1,Laptop,1,999.99,2024-01-01,delivered
2,Mouse,2,29.99,2024-01-02,shipped
3,Keyboard,1,79.99,2024-01-03,pending
4,Monitor,,399.99,2024-01-04,delivered
5,Headphones,1,149.99,,delivered
"""


@pytest.fixture
def sample_json_bytes() -> bytes:
    data = [
        {"user_id": "U001", "name": "Alice", "score": 95.5, "active": True},
        {"user_id": "U002", "name": "Bob", "score": 82.0, "active": False},
        {"user_id": "U003", "name": "Carol", "score": 91.2, "active": True},
    ]
    return json.dumps(data).encode()


@pytest.fixture
def raw_schema_fixture() -> dict:
    return {
        "columns": [
            {
                "name": "order_id",
                "detected_type": "int64",
                "suggested_db_type": "BIGINT",
                "nullable": False,
                "unique_ratio": 1.0,
                "null_ratio": 0.0,
                "sample_values": [1, 2, 3],
                "statistics": {"mean": 3.0, "std": 1.58, "min": 1.0, "max": 5.0, "median": 3.0},
                "is_potential_pk": True,
                "is_potential_fk": False,
            },
            {
                "name": "product",
                "detected_type": "object",
                "suggested_db_type": "VARCHAR(100)",
                "nullable": False,
                "unique_ratio": 1.0,
                "null_ratio": 0.0,
                "sample_values": ["Laptop", "Mouse"],
                "statistics": {"most_common": {"Laptop": 1}, "avg_length": 6.5},
                "is_potential_pk": False,
                "is_potential_fk": False,
            },
            {
                "name": "price",
                "detected_type": "float64",
                "suggested_db_type": "DOUBLE PRECISION",
                "nullable": False,
                "unique_ratio": 1.0,
                "null_ratio": 0.0,
                "sample_values": [999.99, 29.99],
                "statistics": {"mean": 331.97, "std": 400.1, "min": 29.99, "max": 999.99, "median": 149.99},
                "is_potential_pk": False,
                "is_potential_fk": False,
            },
            {
                "name": "status",
                "detected_type": "object",
                "suggested_db_type": "VARCHAR(100)",
                "nullable": False,
                "unique_ratio": 0.6,
                "null_ratio": 0.0,
                "sample_values": ["delivered", "shipped", "pending"],
                "statistics": {"most_common": {"delivered": 2, "shipped": 1, "pending": 1}, "avg_length": 8.0},
                "is_potential_pk": False,
                "is_potential_fk": False,
            },
        ],
        "total_rows": 5,
        "total_columns": 4,
    }


# ── DataIngestionEngine Tests ─────────────────────────────────────────────────


class TestDataIngestionEngine:

    @pytest.mark.asyncio
    async def test_parse_csv_success(
        self, ingestion_engine: DataIngestionEngine, sample_csv_bytes: bytes, tmp_path
    ):
        with patch.object(ingestion_engine, "_save_file", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = "/tmp/test.csv"
            result = await ingestion_engine.ingest_file(sample_csv_bytes, "test.csv", "Test Dataset")

        assert result["row_count"] == 5
        assert result["column_count"] == 6
        assert result["source_type"] == "csv"
        assert "raw_schema" in result
        assert "dataframe" in result

    @pytest.mark.asyncio
    async def test_parse_json_success(
        self, ingestion_engine: DataIngestionEngine, sample_json_bytes: bytes
    ):
        with patch.object(ingestion_engine, "_save_file", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = "/tmp/test.json"
            result = await ingestion_engine.ingest_file(sample_json_bytes, "test.json", "Users")

        assert result["row_count"] == 3
        assert result["column_count"] == 4
        assert result["source_type"] == "json"

    @pytest.mark.asyncio
    async def test_json_api_ingest(self, ingestion_engine: DataIngestionEngine):
        data = [
            {"id": 1, "name": "Alice", "value": 100.0},
            {"id": 2, "name": "Bob", "value": 200.0},
        ]
        result = await ingestion_engine.ingest_json_api(data)
        assert result["row_count"] == 2
        assert result["source_type"] == "json"

    @pytest.mark.asyncio
    async def test_json_api_with_wrapper(self, ingestion_engine: DataIngestionEngine):
        """API responses often wrap data in a 'data' key."""
        payload = {"data": [{"id": 1}, {"id": 2}], "total": 2}
        result = await ingestion_engine.ingest_json_api(payload)
        assert result["row_count"] == 2

    def test_column_name_normalization(self, ingestion_engine: DataIngestionEngine):
        df = pd.DataFrame({"First Name": ["Alice"], "last-name": ["Smith"], "AGE ": [30]})
        cleaned = ingestion_engine._clean_dataframe(df)
        assert "first_name" in cleaned.columns
        assert "last_name" in cleaned.columns
        assert "age" in cleaned.columns

    def test_schema_analysis_detects_nulls(self, ingestion_engine: DataIngestionEngine):
        df = pd.DataFrame({
            "id": [1, 2, 3, 4, 5],
            "value": [10.0, None, 30.0, None, 50.0],
        })
        schema = ingestion_engine._analyze_schema(df)
        value_col = next(c for c in schema["columns"] if c["name"] == "value")
        assert value_col["null_ratio"] == 0.4
        assert value_col["nullable"] is True

    @pytest.mark.asyncio
    async def test_unsupported_extension_raises(
        self, ingestion_engine: DataIngestionEngine
    ):
        with pytest.raises(Exception, match="Unsupported"):
            await ingestion_engine.ingest_file(b"data", "file.pdf", "Test")


# ── SchemaGenerator Tests ─────────────────────────────────────────────────────


class TestSchemaGenerator:

    def test_generates_schema_with_primary_key(
        self, schema_generator: SchemaGenerator, raw_schema_fixture: dict
    ):
        result = schema_generator.generate(raw_schema_fixture, "orders")
        assert result["table_name"] == "orders"
        assert result["primary_key"] == "id"
        pk_col = next(c for c in result["columns"] if c["name"] == "id")
        assert pk_col["is_primary_key"] is True
        assert pk_col["db_type"] == "UUID"

    def test_sanitizes_table_name(self, schema_generator: SchemaGenerator):
        result = schema_generator.generate({"columns": [], "total_rows": 0}, "My Table!! 2024")
        assert result["table_name"] == "my_table_2024"

    def test_generates_indexes_for_status(
        self, schema_generator: SchemaGenerator, raw_schema_fixture: dict
    ):
        result = schema_generator.generate(raw_schema_fixture, "orders")
        index_names = [idx["name"] for idx in result["indexes"]]
        assert any("status" in name for name in index_names)

    def test_generates_sqlalchemy_model_code(
        self, schema_generator: SchemaGenerator, raw_schema_fixture: dict
    ):
        result = schema_generator.generate(raw_schema_fixture, "orders")
        code = result["sqlalchemy_model_code"]
        assert "class Orders(Base):" in code
        assert '__tablename__ = "orders"' in code
        assert "UUID" in code

    def test_provides_recommendations_for_large_dataset(
        self, schema_generator: SchemaGenerator, raw_schema_fixture: dict
    ):
        raw_schema_fixture["total_rows"] = 2_000_000
        result = schema_generator.generate(raw_schema_fixture, "big_table")
        assert any("partition" in r.lower() for r in result["recommendations"])

    def test_table_name_starting_with_digit(self, schema_generator: SchemaGenerator):
        result = schema_generator.generate({"columns": [], "total_rows": 0}, "2024_orders")
        assert result["table_name"].startswith("t_") or result["table_name"][0].isalpha()


# ── PromptLibrary Tests ───────────────────────────────────────────────────────


class TestPromptLibrary:

    def test_all_default_templates_registered(self):
        lib = PromptLibrary()
        templates = lib.list_templates()
        names = [t["name"] for t in templates]
        assert "nl_to_sql" in names
        assert "data_summary" in names
        assert "trend_analysis" in names

    def test_template_render_success(self):
        lib = PromptLibrary()
        template = lib.get("nl_to_sql")
        rendered = template.render(schema="Table: orders\nColumns:\n  id INT", question="How many orders?")
        assert "How many orders?" in rendered
        assert "Table: orders" in rendered

    def test_template_render_missing_variable(self):
        lib = PromptLibrary()
        template = lib.get("nl_to_sql")
        with pytest.raises(ValueError, match="Missing template variable"):
            template.render(schema="some schema")  # missing 'question'

    def test_unknown_template_raises(self):
        lib = PromptLibrary()
        with pytest.raises(ValueError, match="Unknown prompt template"):
            lib.get("nonexistent_template")

    def test_register_custom_template(self):
        lib = PromptLibrary()
        custom = PromptTemplate(
            name="custom_test",
            category="insight",
            version="1.0.0",
            system_prompt="You are a test assistant.",
            user_template="Test: $value",
        )
        lib.register(custom)
        assert lib.get("custom_test").name == "custom_test"
        rendered = lib.get("custom_test").render(value="hello")
        assert rendered == "Test: hello"


# ── Auth utility Tests ────────────────────────────────────────────────────────


class TestAuthUtils:

    def test_password_hash_and_verify(self):
        from app.services.auth.auth_service import hash_password, verify_password
        hashed = hash_password("SecurePass123")
        assert verify_password("SecurePass123", hashed)
        assert not verify_password("WrongPass123", hashed)

    def test_create_access_token_contains_claims(self):
        from app.services.auth.auth_service import create_access_token, decode_token
        token, expires_in = create_access_token("user-123", "admin")
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert expires_in > 0

    def test_invalid_token_raises(self):
        from app.services.auth.auth_service import decode_token
        from app.core.exceptions import AuthenticationError
        with pytest.raises(AuthenticationError):
            decode_token("not.a.valid.jwt.token")
