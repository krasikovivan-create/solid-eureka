import json
from datetime import timedelta

from app.services import tasks as task_service
from app.services.timeutils import now_local, now_utc
from app.tools import OutConfirm, registry
from app.tools.base import ToolRegistry
from tests.conftest import OWNER_ID


def tomorrow_at(hhmm: str) -> str:
    d = now_local("Europe/Moscow").date() + timedelta(days=1)
    return f"{d.isoformat()}T{hhmm}"


async def run(ctx, name, **args):
    out, is_error = await registry.execute(ctx, name, args)
    try:
        return json.loads(out), is_error
    except json.JSONDecodeError:
        return out, is_error


async def test_registry_definitions_are_valid():
    defs = registry.definitions()
    names = [d["name"] for d in defs]
    assert len(names) == len(set(names)) >= 25
    for d in defs:
        assert d["description"]
        assert d["input_schema"]["type"] == "object"
        for req in d["input_schema"]["required"]:
            assert req in d["input_schema"]["properties"]


async def test_create_task_with_reminder_schedules_job(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, err = await run(
        ctx, "create_task", title="Позвонить Иванову", remind_at=tomorrow_at("10:00")
    )
    assert not err
    task_id = data["created"]["id"]
    assert data["created"]["remind"].startswith("завтра 10:00")
    task = await task_service.get_task(ctx.app.sf, task_id)
    assert task.user_id == OWNER_ID
    job = ctx.app.scheduler.scheduler.get_job(f"reminder:{task_id}")
    assert job is not None


async def test_due_with_time_sets_reminder_automatically(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, _ = await run(ctx, "create_task", title="Отчёт", due_at=tomorrow_at("15:00"))
    assert data["created"]["remind"] is not None
    data, _ = await run(ctx, "create_task", title="Без времени", due_at="2030-01-01")
    assert data["created"]["remind"] is None


async def test_create_task_validation_errors(tool_ctx_factory):
    ctx = tool_ctx_factory()
    out, err = await run(ctx, "create_task", title="X", priority="космический")
    assert err and "Приоритет" in out
    out, err = await run(ctx, "create_task", title="X", due_at="послезавтра")
    assert err and "дату" in out
    out, err = await run(ctx, "create_task")
    assert err


async def test_list_tasks_periods_and_priorities(tool_ctx_factory):
    ctx = tool_ctx_factory()
    await run(ctx, "create_task", title="Низкий", priority="low", due_at=tomorrow_at("09:00"))
    await run(ctx, "create_task", title="Срочный", priority="urgent", due_at=tomorrow_at("18:00"))
    await run(ctx, "create_task", title="Без даты")
    past = (now_local("Europe/Moscow") - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    await run(ctx, "create_task", title="Просроченная", due_at=past)

    data, _ = await run(ctx, "list_tasks")
    assert data["count"] == 4
    assert data["tasks"][0]["title"] == "Срочный"  # сортировка по приоритету
    data, _ = await run(ctx, "list_tasks", period="tomorrow")
    assert {t["title"] for t in data["tasks"]} == {"Низкий", "Срочный"}
    data, _ = await run(ctx, "list_tasks", period="overdue")
    assert [t["title"] for t in data["tasks"]] == ["Просроченная"]
    data, _ = await run(ctx, "list_tasks", period="no_date")
    assert [t["title"] for t in data["tasks"]] == ["Без даты"]


async def test_update_task_status_and_reschedule(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, _ = await run(ctx, "create_task", title="Встреча", remind_at=tomorrow_at("10:00"))
    tid = data["created"]["id"]
    data, err = await run(ctx, "update_task", task_id=tid, remind_at=tomorrow_at("12:30"))
    assert not err and data["updated"]["remind"].startswith("завтра 12:30")
    data, _ = await run(ctx, "update_task", task_id=tid, status="done", priority="high")
    assert data["updated"]["status"] == "done"
    assert ctx.app.scheduler.scheduler.get_job(f"reminder:{tid}") is None
    task = await task_service.get_task(ctx.app.sf, tid)
    assert task.completed_at is not None
    data, _ = await run(ctx, "list_tasks", status="done")
    assert data["count"] == 1


async def test_update_task_clear_and_errors(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, _ = await run(ctx, "create_task", title="A", due_at=tomorrow_at("10:00"))
    tid = data["created"]["id"]
    data, _ = await run(ctx, "update_task", task_id=tid, clear_due=True, clear_reminder=True)
    assert data["updated"]["due"] is None and data["updated"]["remind"] is None
    out, err = await run(ctx, "update_task", task_id=9999, title="x")
    assert err and "не найдена" in out
    out, err = await run(ctx, "update_task", task_id=tid, status="непонятно")
    assert err


async def test_delete_task_requires_confirmation(tool_ctx_factory):
    ctx = tool_ctx_factory()
    data, _ = await run(ctx, "create_task", title="Удалить меня")
    tid = data["created"]["id"]
    _out, err = await run(ctx, "delete_task", task_id=tid)
    assert not err
    assert isinstance(ctx.outbox[-1], OutConfirm)
    assert ctx.outbox[-1].kind == "task" and ctx.outbox[-1].object_id == tid
    # задача ещё существует — удаление только после кнопки
    assert (await task_service.get_task(ctx.app.sf, tid)).title == "Удалить меня"


async def test_tasks_are_private_per_user(tool_ctx_factory):
    owner = tool_ctx_factory()
    other = tool_ctx_factory(user_id=777)
    data, _ = await run(owner, "create_task", title="Моя")
    tid = data["created"]["id"]
    _out, err = await run(other, "update_task", task_id=tid, title="Чужая")
    assert err
    data, _ = await run(other, "list_tasks")
    assert data["count"] == 0


async def test_day_overview_and_evening(tool_ctx_factory):
    ctx = tool_ctx_factory()
    today = now_local("Europe/Moscow").date().isoformat()
    await run(ctx, "create_task", title="Сегодняшняя", due_at=f"{today}T23:59")
    data, _ = await run(ctx, "day_overview")
    assert "Сегодняшняя" in data["overview"]
    t = await task_service.create_task(ctx.app.sf, OWNER_ID, "Сделано")
    await task_service.update_task(ctx.app.sf, t.id, status="done")
    data, _ = await run(ctx, "evening_summary")
    assert "Сделано" in data["summary"]


async def test_unknown_tool_and_bad_args(tool_ctx_factory):
    ctx = tool_ctx_factory()
    out, err = await registry.execute(ctx, "nope", {})
    assert err
    out, err = await registry.execute(ctx, "list_tasks", {"bogus": 1})
    assert err and "аргументы" in out.lower()


async def test_tool_internal_error_is_reported():
    reg = ToolRegistry()

    @reg.register("boom", "boom", {})
    async def boom(ctx):
        raise RuntimeError("секрет")

    out, err = await reg.execute(None, "boom", {})
    assert err and "RuntimeError" in out and "секрет" not in out


async def test_reminder_in_past_warns(tool_ctx_factory):
    ctx = tool_ctx_factory()
    past = (now_utc() - timedelta(hours=1)).astimezone(now_local("Europe/Moscow").tzinfo)
    data, _ = await run(
        ctx, "create_task", title="Старое", remind_at=past.strftime("%Y-%m-%dT%H:%M")
    )
    assert "warning" in data
