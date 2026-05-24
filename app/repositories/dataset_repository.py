from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Dataset, GeneratedTable


class DatasetRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, dataset_id: str) -> Dataset | None:
        result = await self._db.execute(
            select(Dataset)
            .options(selectinload(Dataset.table_schemas))
            .where(Dataset.id == dataset_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        owner_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Dataset], int]:
        base = select(Dataset).where(Dataset.owner_id == owner_id)
        total_result = await self._db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            base.order_by(Dataset.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), total

    async def create(self, dataset: Dataset) -> Dataset:
        self._db.add(dataset)
        await self._db.flush()
        await self._db.refresh(dataset)
        return dataset

    async def update(self, dataset: Dataset) -> Dataset:
        await self._db.flush()
        await self._db.refresh(dataset)
        return dataset

    async def delete(self, dataset: Dataset) -> None:
        await self._db.delete(dataset)
        await self._db.flush()

    async def save_generated_table(self, table: GeneratedTable) -> GeneratedTable:
        self._db.add(table)
        await self._db.flush()
        await self._db.refresh(table)
        return table
