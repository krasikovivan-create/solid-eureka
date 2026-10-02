import json
from pathlib import Path

import pytest

from app.services.bm25 import BM25Index, stem, tokenize
from app.services.documents import (
    UnsupportedDocumentError,
    chunk_text,
    extract_text,
    is_supported,
)
from app.tools import OutConfirm, registry
from tests.helpers import make_docx, make_pdf

PAYMENT_TEXT = (
    "Условия оплаты\n\nОплата производится поэтапно: 50% предоплата, 50% после сдачи работ.\n\n"
    "Сроки внедрения чат-бота — от двух до четырёх недель.\n\n"
    "Гарантия на внедрённые решения — три месяца."
)


def test_extract_txt_encodings():
    assert extract_text("a.txt", "Привет, мир".encode()) == "Привет, мир"
    assert extract_text("a.txt", "Привет из Windows".encode("cp1251")) == "Привет из Windows"


def test_extract_docx_with_table():
    data = make_docx(["Договор оказания услуг", "Срок: 30 дней"], [["Этап", "Цена"], ["1", "100"]])
    text = extract_text("dogovor.docx", data)
    assert "Договор оказания услуг" in text
    assert "Этап | Цена" in text


def test_extract_pdf():
    data = make_pdf(["Price list", "Chatbot integration costs 50000 rubles"])
    text = extract_text("price.pdf", data)
    assert "Chatbot integration" in text
    assert "[стр. 1]" in text


def test_extract_errors():
    with pytest.raises(UnsupportedDocumentError):
        extract_text("image.png", b"123")
    with pytest.raises(UnsupportedDocumentError):
        extract_text("broken.docx", b"not a zip")
    with pytest.raises(UnsupportedDocumentError):
        extract_text("broken.pdf", b"%PDF-garbage")
    with pytest.raises(UnsupportedDocumentError):
        extract_text("empty.txt", b"   \n  ")
    assert is_supported("A.PDF") and is_supported("x.docx") and not is_supported("x.doc")


def test_chunking_covers_text():
    text = "\n\n".join(f"Абзац номер {i}. " + "слово " * 40 for i in range(30))
    chunks = chunk_text(text, size=500, overlap=100)
    assert len(chunks) > 5
    assert all(len(c) <= 600 for c in chunks)
    for i in range(30):
        assert any(f"Абзац номер {i}." in c for c in chunks)
    long = "а" * 3000
    assert len(chunk_text(long, size=1000)) == 3


def test_russian_stemming_and_tokenize():
    assert stem("оплаты") == stem("оплата") == stem("оплату")
    assert stem("договорами") == stem("договор")
    assert "и" not in tokenize("оплата и сроки")


def test_bm25_ranking():
    idx = BM25Index()
    idx.add("pay", "Условия оплаты: предоплата 50 процентов")
    idx.add("time", "Сроки внедрения чат-бота две недели")
    idx.add("other", "Наша команда любит кофе")
    hits = idx.search("какие условия по оплате?")
    assert hits[0].key == "pay"
    assert idx.search("сроки внедрения")[0].key == "time"
    assert idx.search("квантовая физика") == []


async def test_kb_add_search_delete(onboarded):
    kb = onboarded.kb
    doc = await kb.add_document("Условия.txt", PAYMENT_TEXT.encode())
    assert Path(doc.file_path).exists()
    await kb.add_document("Прочее.txt", "Наш офис находится в Москве.".encode())
    hits = await kb.search("как происходит оплата")
    assert hits and hits[0].filename == "Условия.txt"
    assert "предоплата" in hits[0].text
    docs = await kb.list_documents()
    assert len(docs) == 2
    await kb.delete_document(doc.id)
    assert not Path(doc.file_path).exists()
    assert all(h.filename != "Условия.txt" for h in await kb.search("оплата"))


async def test_kb_tools(tool_ctx_factory):
    ctx = tool_ctx_factory()
    out, err = await registry.execute(ctx, "search_knowledge", {"query": "оплата"})
    assert not err and "пуста" in out
    doc = await ctx.app.kb.add_document("Условия.docx", make_docx(PAYMENT_TEXT.split("\n\n")))
    out, err = await registry.execute(ctx, "search_knowledge", {"query": "гарантия"})
    data = json.loads(out)
    assert data["results"][0]["source"] == "📄 Условия.docx"
    assert "три месяца" in data["results"][0]["text"]
    out, _ = await registry.execute(ctx, "search_knowledge", {"query": "космос"})
    assert "ничего не найдено" in out
    out, _ = await registry.execute(ctx, "list_documents", {})
    assert json.loads(out)[0]["filename"] == "Условия.docx"
    out, err = await registry.execute(ctx, "delete_document", {"document_id": doc.id})
    assert not err and isinstance(ctx.outbox[-1], OutConfirm)
    out, err = await registry.execute(ctx, "delete_document", {"document_id": 999})
    assert err
