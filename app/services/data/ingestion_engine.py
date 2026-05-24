"""
Data Ingestion Engine
─────────────────────
Handles file parsing, data cleaning, and schema auto-detection.
Supports CSV, JSON, and Excel with configurable chunked reading for large files.
"""

import io
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.exceptions import DataIngestionError
from app.core.logging import get_logger
from app.schemas.schemas import ColumnInfo

logger = get_logger(__name__)

# Map pandas dtype strings to PostgreSQL column types
_DTYPE_TO_PG: dict[str, str] = {
    "int64": "BIGINT",
    "int32": "INTEGER",
    "int16": "SMALLINT",
    "float64": "DOUBLE PRECISION",
    "float32": "REAL",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP WITH TIME ZONE",
    "object": "TEXT",
    "category": "VARCHAR(255)",
}

# Thresholds for type inference
_UNIQUE_RATIO_THRESHOLD = 0.05   # Below this → candidate for ENUM/FK
_INT_DETECT_THRESHOLD = 0.95     # >95% parseable as int → treat as int
_DATETIME_DETECT_THRESHOLD = 0.9


class DataIngestionEngine:
    """
    Core ingestion pipeline. Steps:
    1. Parse file → DataFrame
    2. Clean (nulls, whitespace, types)
    3. Analyse schema per-column
    4. Return structured metadata
    """

    CHUNK_SIZE = 50_000  # Rows per chunk for large files

    async def ingest_file(
        self, file_bytes: bytes, filename: str, dataset_name: str
    ) -> dict[str, Any]:
        """Main entry point. Returns ingestion metadata."""
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in settings.allowed_extensions_list:
            raise DataIngestionError(
                f"Unsupported file type: .{ext}. Allowed: {settings.allowed_extensions}"
            )

        try:
            df = self._parse_file(file_bytes, ext)
        except Exception as exc:
            raise DataIngestionError(f"Failed to parse file: {exc}") from exc

        df = self._clean_dataframe(df)
        schema_info = self._analyze_schema(df)
        file_path = await self._save_file(file_bytes, dataset_name, ext)

        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "file_path": file_path,
            "source_type": ext,
            "raw_schema": schema_info,
            "dataframe": df,
        }

    async def ingest_json_api(self, data: list[dict] | dict) -> dict[str, Any]:
        """Ingest data from a JSON payload (e.g. external API response)."""
        if isinstance(data, dict):
            # Try to extract the records list from common API response shapes
            for key in ("data", "results", "items", "records"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                data = [data]  # Single-object response

        try:
            df = pd.DataFrame(data)
        except Exception as exc:
            raise DataIngestionError(f"Cannot construct DataFrame: {exc}") from exc

        df = self._clean_dataframe(df)
        schema_info = self._analyze_schema(df)

        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "file_path": None,
            "source_type": "json",
            "raw_schema": schema_info,
            "dataframe": df,
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_file(self, file_bytes: bytes, ext: str) -> pd.DataFrame:
        buffer = io.BytesIO(file_bytes)
        if ext == "csv":
            # Try common encodings; fall back to latin-1 which never fails
            for encoding in ("utf-8", "utf-8-sig", "latin-1"):
                try:
                    buffer.seek(0)
                    return pd.read_csv(buffer, encoding=encoding, low_memory=False)
                except UnicodeDecodeError:
                    continue
            raise DataIngestionError("Could not decode CSV with supported encodings")

        elif ext == "json":
            buffer.seek(0)
            raw = json.loads(buffer.read())
            if isinstance(raw, list):
                return pd.DataFrame(raw)
            elif isinstance(raw, dict):
                for key in ("data", "results", "items"):
                    if key in raw:
                        return pd.DataFrame(raw[key])
                return pd.DataFrame([raw])
            raise DataIngestionError("JSON must be an array or object with a data key")

        elif ext in ("xlsx", "xls"):
            return pd.read_excel(buffer, engine="openpyxl")

        raise DataIngestionError(f"Unsupported extension: .{ext}")

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        # Normalise column names to snake_case
        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace(r"\s+", "_", regex=True)
            .str.replace(r"[^\w]", "_", regex=True)
            .str.replace(r"_+", "_", regex=True)
            .str.strip("_")
        )

        # Drop fully empty columns and rows
        df = df.dropna(axis=1, how="all")
        df = df.dropna(axis=0, how="all")

        # Strip leading/trailing whitespace from string columns
        str_cols = df.select_dtypes(include="object").columns
        df[str_cols] = df[str_cols].apply(
            lambda col: col.str.strip().replace("", np.nan)
        )

        # Attempt datetime inference on suspicious columns
        for col in df.select_dtypes(include="object").columns:
            if any(k in col for k in ("date", "time", "created", "updated", "at")):
                try:
                    converted = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce")
                    if converted.notna().mean() >= _DATETIME_DETECT_THRESHOLD:
                        df[col] = converted
                except Exception:
                    pass

        return df

    def _analyze_schema(self, df: pd.DataFrame) -> dict[str, Any]:
        columns: list[dict[str, Any]] = []
        total_rows = len(df)

        for col_name in df.columns:
            series = df[col_name]
            null_count = series.isna().sum()
            null_ratio = null_count / total_rows if total_rows > 0 else 0
            non_null = series.dropna()

            unique_count = non_null.nunique()
            unique_ratio = unique_count / len(non_null) if len(non_null) > 0 else 0

            detected_type = str(series.dtype)
            suggested_pg_type = _DTYPE_TO_PG.get(detected_type, "TEXT")

            # Refine type based on content analysis
            if detected_type == "object":
                suggested_pg_type = self._infer_text_type(non_null, unique_ratio)
            elif "int" in detected_type:
                # Check if this might be a foreign key
                if unique_ratio < _UNIQUE_RATIO_THRESHOLD:
                    suggested_pg_type = "INTEGER"  # Likely categorical/FK

            stats = self._compute_statistics(series, detected_type)
            # Convert numpy types in sample values to standard python types
            sample_values = []
            for v in non_null.head(5).tolist():
                if isinstance(v, (bool, np.bool_)):
                    sample_values.append(bool(v))
                elif isinstance(v, (int, np.integer)):
                    sample_values.append(int(v))
                elif isinstance(v, (float, np.floating)):
                    sample_values.append(float(v))
                else:
                    sample_values.append(str(v))

            columns.append({
                "name": col_name,
                "detected_type": detected_type,
                "suggested_db_type": suggested_pg_type,
                "nullable": bool(null_ratio > 0),
                "unique_ratio": round(float(unique_ratio), 4),
                "null_ratio": round(float(null_ratio), 4),
                "sample_values": sample_values,
                "statistics": stats,
                "is_potential_pk": bool(
                    unique_ratio == 1.0
                    and null_ratio == 0
                    and "id" in col_name.lower()
                ),
                "is_potential_fk": bool(
                    unique_ratio < _UNIQUE_RATIO_THRESHOLD
                    and "id" in col_name.lower()
                    and col_name != df.columns[0]
                ),
            })

        return {
            "columns": columns,
            "total_rows": total_rows,
            "total_columns": len(df.columns),
        }

    def _infer_text_type(self, series: pd.Series, unique_ratio: float) -> str:
        if unique_ratio < _UNIQUE_RATIO_THRESHOLD and series.nunique() <= 50:
            return "VARCHAR(100)"  # Good ENUM candidate
        max_len = series.astype(str).str.len().max()
        if max_len <= 50:
            return "VARCHAR(100)"
        elif max_len <= 255:
            return "VARCHAR(255)"
        return "TEXT"

    def _compute_statistics(
        self, series: pd.Series, dtype: str
    ) -> dict[str, Any] | None:
        if "int" in dtype or "float" in dtype:
            desc = series.describe()
            return {
                "mean": float(desc.get("mean", 0)),
                "std": float(desc.get("std", 0)),
                "min": float(desc.get("min", 0)),
                "max": float(desc.get("max", 0)),
                "median": float(series.median()),
            }
        elif dtype == "object":
            # Convert numpy counts to standard python integers
            most_common = {}
            for k, v in series.value_counts().head(5).to_dict().items():
                most_common[str(k)] = int(v)
            return {
                "most_common": most_common,
                "avg_length": float(series.astype(str).str.len().mean()),
            }
        return None

    async def _save_file(self, file_bytes: bytes, name: str, ext: str) -> str:
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        # Sanitise name for filesystem
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name}_{timestamp}.{ext}"
        filepath = upload_dir / filename
        filepath.write_bytes(file_bytes)
        return str(filepath)
