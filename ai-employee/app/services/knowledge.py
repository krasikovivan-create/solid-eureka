"""База знаний: хранение документов и поиск по ним (BM25)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from app.database.models import Document, DocumentChunk
from app.database.session import SessionFactory
from app.services.bm25 import BM25Index
from app.services.documents import chunk_text, extract_text
from app.services.tasks import NotFoundError

log = logging.getLogger(__name__)


@dataclass
class KnowledgeHit:
    document_id: int
    filename: str
    chunk_idx: int
    text: str
    score: float


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", filename, flags=re.UNICODE).strip() or "document"
    return name[:150]


def _remove_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        log.warning("Не удалось удалить файл %s", path)


class KnowledgeBase:
    """Индекс строится лениво и сбрасывается при добавлении/удалении документов."""

    def __init__(self, sf: SessionFactory, storage_dir: Path) -> None:
        self.sf = sf
        self.storage_dir = Path(storage_dir)
        self._index: BM25Index | None = None
        self._chunks: dict[int, tuple[int, str, int, str]] = {}

    def invalidate(self) -> None:
        self._index = None
        self._chunks = {}

    async def add_document(self, filename: str, data: bytes) -> Document:
        text = extract_text(filename, data)
        chunks = chunk_text(text)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        async with self.sf() as s:
            doc = Document(filename=filename, size=len(data), chars=len(text))
            s.add(doc)
            await s.flush()
            path = self.storage_dir / f"{doc.id}_{_safe_name(filename)}"
            path.write_bytes(data)
            doc.file_path = str(path)
            for idx, chunk in enumerate(chunks):
                s.add(DocumentChunk(document_id=doc.id, idx=idx, text=chunk))
            await s.commit()
            await s.refresh(doc)
        self.invalidate()
        log.info("Документ #%s «%s» добавлен: %s фрагментов", doc.id, filename, len(chunks))
        return doc

    async def list_documents(self) -> list[tuple[Document, int]]:
        async with self.sf() as s:
            rows = await s.execute(
                select(Document, func.count(DocumentChunk.id))
                .outerjoin(DocumentChunk)
                .group_by(Document.id)
                .order_by(Document.id)
            )
            return [(d, int(n)) for d, n in rows.all()]

    async def get_document(self, document_id: int) -> Document:
        async with self.sf() as s:
            doc = await s.get(Document, document_id)
            if doc is None:
                raise NotFoundError(f"Документ #{document_id} не найден")
            return doc

    async def delete_document(self, document_id: int) -> Document:
        async with self.sf() as s:
            doc = await s.get(Document, document_id)
            if doc is None:
                raise NotFoundError(f"Документ #{document_id} не найден")
            path = doc.file_path
            await s.delete(doc)
            await s.commit()
        if path:
            _remove_file(path)
        self.invalidate()
        return doc

    async def _ensure_index(self) -> BM25Index:
        if self._index is not None:
            return self._index
        index = BM25Index()
        chunks: dict[int, tuple[int, str, int, str]] = {}
        async with self.sf() as s:
            rows = await s.execute(
                select(DocumentChunk, Document.filename).join(Document).order_by(DocumentChunk.id)
            )
            for chunk, filename in rows.all():
                # Имя файла тоже участвует в поиске.
                index.add(chunk.id, f"{filename}\n{chunk.text}")
                chunks[chunk.id] = (chunk.document_id, filename, chunk.idx, chunk.text)
        self._index = index
        self._chunks = chunks
        return index

    async def search(self, query: str, top_k: int = 5) -> list[KnowledgeHit]:
        index = await self._ensure_index()
        hits = []
        for hit in index.search(query, top_k=top_k):
            doc_id, filename, idx, text = self._chunks[hit.key]  # type: ignore[index]
            hits.append(KnowledgeHit(doc_id, filename, idx, text, round(hit.score, 3)))
        return hits
