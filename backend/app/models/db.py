from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class LiteratureDocument(Base):
    __tablename__ = "literature_documents"
    __table_args__ = (
        UniqueConstraint("path", name="uq_literature_documents_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    suffix: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @classmethod
    def from_path(cls, path: Path) -> "LiteratureDocument":
        stat = path.stat()
        content: str | None = None
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md", ".tsv", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))

            if reader.is_encrypted:
                reader.decrypt("")

            content = "\n".join(page.extract_text() or "" for page in reader.pages)

        return cls(
            path=str(path.resolve()),
            filename=path.name,
            suffix=suffix,
            size_bytes=stat.st_size,
            content=content,
        )