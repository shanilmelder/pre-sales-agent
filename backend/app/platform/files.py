"""`platform_files`: metadata and reference counts for stored blobs (AD-18).

One row per blob in `platform.storage`, keyed by its SHA-256. `ref_count` counts the
references held by business rows (e.g. one per Opportunity Source version), so a later
clean-up can tell which blobs are still in use. Nothing deletes blobs in R1.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base
from app.platform.uow import UnitOfWork


class PlatformFile(Base):
    __tablename__ = "platform_files"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes"),
        CheckConstraint("ref_count >= 0", name="ref_count"),
    )

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    ref_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


async def add_reference(uow: UnitOfWork, sha256: str, size: int) -> int:
    """Record one more reference to the blob, creating its row on first use, inside the
    caller's Unit of Work. Returns the new reference count."""
    statement = (
        insert(PlatformFile)
        .values(sha256=sha256, size_bytes=size, ref_count=1)
        .on_conflict_do_update(
            index_elements=[PlatformFile.sha256],
            set_={"ref_count": PlatformFile.ref_count + 1},
        )
        .returning(PlatformFile.ref_count)
    )
    count: int = (await uow.session.execute(statement)).scalar_one()
    return count
