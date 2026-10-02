import itertools
import json
from datetime import timedelta

from app.services import clients as client_service
from app.services import memory as memory_service
from app.services import tasks as task_service
from app.services.timeutils import now_local
from app.tools import OutConfirm, OutText, registry
from tests.conftest import response, text_block


async def run(ctx, name, **args):
    out, is_error = await registry.execute(ctx, name, args)
    try:
        return json.loads(out), is_error
    except json.JSONDecodeError:
        return out, is_error


async def test_client_crud_and_search(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, err = await run(
        ctx,
        "create_client",
        company="ООО Ромашка",
        industry="ритейл",
        contact_name="Пётр",
        phone="+7 900 000-00-00",
    )
    assert not err
    cid = data["created"]["id"]
    assert data["created"]["status"] == "lead"

    data, _ = await run(ctx, "find_clients", query="ромашка")
    assert data["count"] == 1 and data["clients"][0]["id"] == cid
    data, _ = await run(ctx, "find_clients", query="РИТЕЙЛ")
    assert data["count"] == 1

    data, _ = await run(ctx, "update_client", client_id=cid, status="negotiation", notes="Важный")
    assert data["updated"]["status"] == "negotiation"
    data, _ = await run(
        ctx, "update_client", client_id=cid, notes="Любит звонки", append_notes=True
    )
    assert data["updated"]["notes"] == "Важный\nЛюбит звонки"

    out, err = await run(ctx, "update_client", client_id=cid, status="mystery")
    assert err and "Статус" in out
    out, err = await run(ctx, "create_client", company="  ")
    assert err


async def test_interactions_history_and_card(tool_ctx_factory):
    ctx = tool_ctx_factory()
    client = await client_service.create_client(ctx.app.sf, "Альфа")
    data, err = await run(
        ctx, "add_interaction", client_id=client.id, kind="call", summary="Обсудили бюджет"
    )
    assert not err
    data, _ = await run(ctx, "get_client", client_id=client.id)
    assert data["history"][0]["summary"] == "Обсудили бюджет"
    assert data["history"][0]["kind"] == "call"
    card = client_service.format_client_card(
        await client_service.get_client(ctx.app.sf, client.id), "Europe/Moscow"
    )
    assert "Обсудили бюджет" in card and "Альфа" in card
    _out, err = await run(ctx, "add_interaction", client_id=9999, summary="x")
    assert err


async def test_follow_up_creates_linked_reminder(tool_ctx_factory):
    ctx = tool_ctx_factory()
    client = await client_service.create_client(ctx.app.sf, "Бета")
    when = (now_local("Europe/Moscow") + timedelta(days=3)).strftime("%Y-%m-%dT11:00")
    data, err = await run(
        ctx, "schedule_follow_up", client_id=client.id, when=when, note="узнать решение"
    )
    assert not err
    task = await task_service.get_task(ctx.app.sf, data["follow_up_task"]["id"])
    assert task.client_id == client.id and task.remind_at is not None
    assert "Бета" in task.title
    assert ctx.app.scheduler.scheduler.get_job(f"reminder:{task.id}") is not None
    data, _ = await run(ctx, "get_client", client_id=client.id)
    assert len(data["open_tasks"]) == 1


async def test_pipeline(tool_ctx_factory):
    ctx = tool_ctx_factory()
    await client_service.create_client(ctx.app.sf, "A", status="lead")
    await client_service.create_client(ctx.app.sf, "B", status="lead")
    await client_service.create_client(ctx.app.sf, "C", status="won")
    out, err = await run(ctx, "sales_pipeline")
    assert not err
    assert "всего 3" in out
    assert "Лид: 2" in out and "Сделка: 1" in out


async def test_delete_client_confirmation_and_cascade(tool_ctx_factory):
    ctx = tool_ctx_factory()
    client = await client_service.create_client(ctx.app.sf, "Гамма")
    await client_service.add_interaction(ctx.app.sf, client.id, "привет")
    _out, err = await run(ctx, "delete_client", client_id=client.id)
    assert not err and isinstance(ctx.outbox[-1], OutConfirm)
    await client_service.delete_client(ctx.app.sf, client.id)
    assert await client_service.count_clients(ctx.app.sf) == 0


async def test_resolve_client_ambiguity(onboarded):
    import pytest

    await client_service.create_client(onboarded.sf, "Ромашка Север")
    await client_service.create_client(onboarded.sf, "Ромашка Юг")
    with pytest.raises(ValueError, match="несколько"):
        await client_service.resolve_client(onboarded.sf, None, "Ромашка")
    c = await client_service.resolve_client(onboarded.sf, None, "ромашка юг")
    assert c.company == "Ромашка Юг"


async def test_facts_memory(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, err = await run(ctx, "remember_fact", content="Ставка 3500 ₽/ч")
    assert not err
    fid = data["saved_fact_id"]
    client = await client_service.create_client(ctx.app.sf, "Дельта")
    await run(ctx, "remember_fact", content="Платят в конце месяца", client_id=client.id)
    out, _ = await run(ctx, "list_facts")
    assert "3500" in out and "Платят" in out and "клиент #" in out
    out, _ = await run(ctx, "list_facts", client_id=client.id)
    assert "3500" not in out
    out, err = await run(ctx, "forget_fact", fact_id=fid)
    assert not err and isinstance(ctx.outbox[-1], OutConfirm)
    out, err = await run(ctx, "forget_fact", fact_id=999)
    assert err


async def test_history_building_and_summary(onboarded, fake_llm):
    from app.agent import workflows

    sf = onboarded.sf
    uid = 1
    for i in range(40):
        await memory_service.add_message(sf, uid, "user" if i % 2 == 0 else "assistant", f"m{i}")
    msgs = await memory_service.unsummarized_messages(sf, uid)
    history = memory_service.build_history(msgs, 20)
    assert len(history) <= 20 and history[0]["role"] == "user"
    roles = [h["role"] for h in history]
    assert all(a != b for a, b in itertools.pairwise(roles))

    fake_llm.add(response(text_block("- обсуждали m0..m19")))
    assert await workflows.maybe_summarize(onboarded, uid) is True
    summary = await memory_service.get_summary(sf, uid)
    assert "обсуждали" in summary.summary
    remaining = await memory_service.unsummarized_messages(sf, uid)
    assert len(remaining) == onboarded.settings.history_limit
    # повторно сжимать нечего
    assert await workflows.maybe_summarize(onboarded, uid) is False
    await memory_service.clear_history(sf, uid)
    assert await memory_service.unsummarized_messages(sf, uid) == []


async def test_write_text_tool_uses_smart_model_and_style(tool_ctx_factory, fake_llm):
    ctx = tool_ctx_factory()
    client = await client_service.create_client(ctx.app.sf, "Эпсилон", contact_name="Ольга")
    fake_llm.add(response(text_block("Тема: Встреча\n\nОльга, добрый день! **Ждём вас.**")))
    data, err = await run(
        ctx, "write_text", kind="email", brief="Напомнить о встрече", client_id=client.id
    )
    assert not err and data["chars"] > 10
    out = ctx.outbox[-1]
    assert isinstance(out, OutText) and "<b>Ждём вас.</b>" in out.text
    call = fake_llm.calls[-1]
    assert call["model"] == "claude-sonnet-5-5"
    assert "ИИ Лаб" in call["system"] and "Деловой" in call["system"]
    assert "Ольга" in call["messages"][0]["content"]


async def test_update_settings_tool_reschedules(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, err = await run(ctx, "update_settings", morning_time="08:15", evening_enabled=False)
    assert not err
    assert data["morning"].startswith("08:15")
    sched = ctx.app.scheduler.scheduler
    assert sched.get_job("daily:morning") is not None
    assert sched.get_job("daily:evening") is None
    _out, err = await run(ctx, "update_settings", timezone="Nowhere/City")
    assert err


async def test_get_usage_tool(tool_ctx_factory):
    ctx = tool_ctx_factory()
    out, err = await run(ctx, "get_usage")
    assert not err and "Сегодня" in out
