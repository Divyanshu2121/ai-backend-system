import math
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.db.session import get_db
from app.models.models import Dataset, GeneratedTable, User
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.schemas import (
    APIResponse,
    DatasetDetailResponse,
    DatasetResponse,
    GeneratedTableResponse,
    PaginatedResponse,
    SchemaAnalysisResponse,
    ColumnInfo,
)
from app.services.auth.auth_service import get_current_user
from app.services.data.ingestion_engine import DataIngestionEngine
from app.services.data.schema_generator import SchemaGenerator
from app.core.config import settings

router = APIRouter(prefix="/datasets", tags=["Datasets"])

_ingestion_engine = DataIngestionEngine()
_schema_generator = SchemaGenerator()


@router.post(
    "/upload",
    response_model=DatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV, JSON, or Excel file for ingestion",
)
async def upload_dataset(
    file: Annotated[UploadFile, File(description="CSV, JSON, or XLSX file")],
    name: Annotated[str, Form(min_length=1, max_length=255)],
    description: Annotated[str | None, Form(max_length=1000)] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetDetailResponse:
    if file.size and file.size > settings.max_upload_size_bytes:
        raise ValidationError(
            f"File too large. Maximum size is {settings.max_upload_size_mb}MB"
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise ValidationError("Uploaded file is empty")

    result = await _ingestion_engine.ingest_file(file_bytes, file.filename or "", name)
    generated_schema = _schema_generator.generate(result["raw_schema"], name)

    dataset = Dataset(
        owner_id=current_user.id,
        name=name,
        description=description,
        source_type=result["source_type"],
        file_path=result["file_path"],
        row_count=result["row_count"],
        column_count=result["column_count"],
        raw_schema=result["raw_schema"],
        generated_schema=generated_schema,
        status="ready",
    )

    repo = DatasetRepository(db)
    dataset = await repo.create(dataset)

    # Persist the generated table schema
    table = GeneratedTable(
        dataset_id=dataset.id,
        table_name=generated_schema["table_name"],
        columns=generated_schema["columns"],
        indexes=generated_schema["indexes"],
        sqlalchemy_model_code=generated_schema.get("sqlalchemy_model_code"),
    )
    await repo.save_generated_table(table)

    return DatasetDetailResponse.model_validate(dataset)


@router.post(
    "/ingest-json",
    response_model=DatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest data from a JSON payload or API response",
)
async def ingest_json(
    payload: dict | list,
    name: str = Query(..., min_length=1, max_length=255),
    description: str | None = Query(None, max_length=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetDetailResponse:
    result = await _ingestion_engine.ingest_json_api(payload)
    generated_schema = _schema_generator.generate(result["raw_schema"], name)

    dataset = Dataset(
        owner_id=current_user.id,
        name=name,
        description=description,
        source_type="json",
        row_count=result["row_count"],
        column_count=result["column_count"],
        raw_schema=result["raw_schema"],
        generated_schema=generated_schema,
        status="ready",
    )

    repo = DatasetRepository(db)
    dataset = await repo.create(dataset)
    return DatasetDetailResponse.model_validate(dataset)


@router.get(
    "/",
    response_model=PaginatedResponse,
    summary="List all datasets owned by the current user",
)
async def list_datasets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    repo = DatasetRepository(db)
    datasets, total = await repo.get_by_owner(current_user.id, page, page_size)

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size),
        data=[DatasetResponse.model_validate(d) for d in datasets],
    )


@router.get(
    "/{dataset_id}",
    response_model=DatasetDetailResponse,
    summary="Get detailed information about a dataset",
)
async def get_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetDetailResponse:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    return DatasetDetailResponse.model_validate(dataset)


@router.get(
    "/{dataset_id}/schema",
    response_model=SchemaAnalysisResponse,
    summary="Get the auto-analyzed schema for a dataset",
)
async def get_schema(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SchemaAnalysisResponse:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    if not dataset.raw_schema:
        raise NotFoundError("Schema analysis not yet available for this dataset")

    columns = [ColumnInfo(**col) for col in dataset.raw_schema.get("columns", [])]
    generated = dataset.generated_schema or {}

    return SchemaAnalysisResponse(
        dataset_id=dataset_id,
        columns=columns,
        detected_relationships=generated.get("constraints", []),
        recommendations=generated.get("recommendations", []),
    )


@router.get(
    "/{dataset_id}/generated-tables",
    response_model=list[GeneratedTableResponse],
    summary="Get auto-generated SQLAlchemy table definitions",
)
async def get_generated_tables(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GeneratedTableResponse]:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    return [GeneratedTableResponse.model_validate(t) for t in dataset.table_schemas]


@router.delete(
    "/{dataset_id}",
    response_model=APIResponse,
    summary="Delete a dataset and all associated data",
)
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    repo = DatasetRepository(db)
    dataset = await repo.get_by_id(dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id!r} not found")
    if dataset.owner_id != current_user.id and current_user.role != "admin":
        raise AuthorizationError()
    await repo.delete(dataset)
    return APIResponse(message="Dataset deleted successfully")
