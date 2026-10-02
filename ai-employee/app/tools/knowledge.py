"""Инструменты: база знаний."""

from __future__ import annotations

from app.tools.base import S_INT, OutConfirm, ToolContext, registry


@registry.register(
    "search_knowledge",
    "Поиск по загруженным документам компании (BM25). Возвращает фрагменты с именем файла — "
    "в ответе ссылайся на источник.",
    {"query": {"type": "string", "description": "Ключевые слова вопроса"}},
    required=["query"],
)
async def search_knowledge(ctx: ToolContext, query: str):
    hits = await ctx.app.kb.search(query, top_k=5)
    if not hits:
        docs = await ctx.app.kb.list_documents()
        if not docs:
            return "База знаний пуста: пользователь ещё не загружал документы."
        return "По этому запросу ничего не найдено. Попробуй другие ключевые слова."
    return {
        "results": [
            {
                "source": f"📄 {h.filename}",
                "document_id": h.document_id,
                "fragment": h.chunk_idx + 1,
                "text": h.text,
            }
            for h in hits
        ]
    }


@registry.register("list_documents", "Список документов в базе знаний.", {})
async def list_documents(ctx: ToolContext):
    docs = await ctx.app.kb.list_documents()
    return [{"id": d.id, "filename": d.filename, "chars": d.chars, "fragments": n} for d, n in docs]


@registry.register(
    "delete_document",
    "Удалить документ из базы знаний. Выполнится после подтверждения пользователем кнопкой.",
    {"document_id": S_INT},
    required=["document_id"],
)
async def delete_document(ctx: ToolContext, document_id: int):
    doc = await ctx.app.kb.get_document(document_id)
    ctx.outbox.append(OutConfirm("document", doc.id, f"документ #{doc.id} «{doc.filename}»"))
    return "Пользователю показана кнопка подтверждения удаления."
