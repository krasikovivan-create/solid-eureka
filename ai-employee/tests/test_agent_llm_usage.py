import anthropic
import httpx2 as httpx
import pytest

from app.agent.agent import Agent, choose_model
from app.agent.llm import BudgetExceededError, LLMError, friendly_api_error
from app.services import tasks as task_service
from app.services import usage as usage_service
from app.services.usage import calc_cost
from app.tools import OutConfirm
from tests.conftest import OWNER_ID, response, text_block, tool_block


def api_error(cls, status: int, message: str = "error"):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req, json={"error": {"message": message}})
    return cls(message, response=resp, body={"error": {"message": message}})


# --- Учёт расходов -------------------------------------------------------------


def test_calc_cost():
    assert calc_cost("claude-haiku-4-5", 1_000_000, 0) == 1.0
    assert calc_cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0
    assert calc_cost("claude-sonnet-5-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.2)
    assert calc_cost("claude-sonnet-5-5", 0, 0, cache_write_tokens=1_000_000) == pytest.approx(2.5)


async def test_usage_records_and_report(onboarded, fake_llm):
    fake_llm.add(response(text_block("ok"), input_tokens=1000, output_tokens=500))
    text = await onboarded.llm.complete_text(prompt="hi", purpose="test", user_id=OWNER_ID)
    assert text == "ok"
    day_start, _month_start = usage_service.period_starts("Europe/Moscow")
    totals = await usage_service.totals_since(onboarded.sf, day_start)
    assert totals.requests == 1
    assert totals.cost_usd == pytest.approx(calc_cost("claude-haiku-4-5", 1000, 500))
    report = await usage_service.usage_report(onboarded.sf, "Europe/Moscow", 1.0, 10.0)
    assert "Сегодня" in report and "Этот месяц" in report and "claude-haiku-4-5" in report
    assert "Лимит: $1.00" in report


async def test_budget_limit_blocks_requests(onboarded, fake_llm):
    onboarded.settings.daily_budget_usd = 0.0001
    await usage_service.record_usage(onboarded.sf, "claude-sonnet-5-5", 100_000, 10_000)
    with pytest.raises(BudgetExceededError) as exc:
        await onboarded.llm.complete_text(prompt="hi")
    assert "лимит" in exc.value.user_message
    assert fake_llm.calls == []


async def test_max_tokens_limit_is_applied(onboarded, fake_llm):
    fake_llm.add(response(text_block("ok")))
    await onboarded.llm.complete_text(prompt="hi")
    assert fake_llm.calls[-1]["max_tokens"] == onboarded.settings.max_tokens_per_request


async def test_effort_not_sent_to_haiku(onboarded, fake_llm):
    fake_llm.add(response(text_block("a")), response(text_block("b")))
    await onboarded.llm.complete_text(prompt="x", model="claude-haiku-4-5", effort="low")
    assert "output_config" not in fake_llm.calls[-1]
    await onboarded.llm.complete_text(prompt="x", model="claude-sonnet-5-5", effort="low")
    assert fake_llm.calls[-1]["output_config"] == {"effort": "low"}


async def test_api_errors_are_friendly(onboarded, fake_llm):
    fake_llm.add(api_error(anthropic.RateLimitError, 429))
    with pytest.raises(LLMError) as exc:
        await onboarded.llm.complete_text(prompt="x")
    assert "Слишком много запросов" in exc.value.user_message
    assert "ключ" in friendly_api_error(api_error(anthropic.AuthenticationError, 401)).lower()
    assert "средства" in friendly_api_error(
        api_error(anthropic.BadRequestError, 400, "Your credit balance is too low")
    )


async def test_refusal_falls_back_to_fast_model(onboarded, fake_llm):
    fake_llm.add(
        response(text_block(""), stop_reason="refusal", model="claude-sonnet-5-5"),
        response(text_block("Вот текст")),
    )
    text = await onboarded.llm.complete_text(prompt="x", model="claude-sonnet-5-5")
    assert text == "Вот текст"
    assert fake_llm.calls[-1]["model"] == "claude-haiku-4-5"


# --- Агент -----------------------------------------------------------------------


def test_choose_model(app):
    assert choose_model(app, "Напомни завтра позвонить") == "claude-haiku-4-5"
    assert choose_model(app, "Проанализируй воронку и предложи стратегию") == "claude-sonnet-5-5"
    assert choose_model(app, "x" * 700) == "claude-sonnet-5-5"


async def test_agent_tool_loop_creates_task(onboarded, fake_llm):
    fake_llm.add(
        response(
            text_block("Создаю задачу."),
            tool_block(
                "create_task", {"title": "Позвонить Иванову", "remind_at": "2030-01-10T10:00"}
            ),
        ),
        response(text_block("Готово! Напомню 10 января в 10:00.")),
    )
    agent = Agent(onboarded)
    reply = await agent.handle(OWNER_ID, "напомни 10 января 2030 в 10 позвонить Иванову")
    assert reply.text == "Готово! Напомню 10 января в 10:00."
    assert reply.tool_calls == ["create_task"]
    tasks = await task_service.list_tasks(onboarded.sf, OWNER_ID, "Europe/Moscow")
    assert tasks[0].title == "Позвонить Иванову" and tasks[0].remind_at is not None

    first, second = fake_llm.calls
    assert first["model"] == "claude-haiku-4-5"
    assert {t["name"] for t in first["tools"]} >= {"create_task", "search_knowledge"}
    # система: статичная часть с кэшем + профиль компании и текущее время
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "ИИ Лаб" in first["system"][1]["text"] and "Сейчас:" in first["system"][1]["text"]
    # второй запрос содержит результат инструмента
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "Позвонить Иванову" in tool_result["content"]


async def test_agent_history_is_persisted(onboarded, fake_llm):
    agent = Agent(onboarded)
    fake_llm.add(response(text_block("Привет!")), response(text_block("Вы спрашивали про погоду.")))
    await agent.handle(OWNER_ID, "Привет")
    await agent.handle(OWNER_ID, "Что я спрашивал?")
    msgs = fake_llm.calls[-1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "Привет" and msgs[1]["content"] == "Привет!"


async def test_agent_tool_error_is_passed_back(onboarded, fake_llm):
    fake_llm.add(
        response(tool_block("update_task", {"task_id": 999, "title": "x"})),
        response(text_block("Такой задачи нет.")),
    )
    reply = await Agent(onboarded).handle(OWNER_ID, "переименуй задачу 999")
    result = fake_llm.calls[-1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert reply.text == "Такой задачи нет."


async def test_agent_delete_goes_to_confirmation(onboarded, fake_llm):
    task = await task_service.create_task(onboarded.sf, OWNER_ID, "Лишняя")
    fake_llm.add(
        response(tool_block("delete_task", {"task_id": task.id})),
        response(text_block("Подтвердите удаление кнопкой ниже.")),
    )
    reply = await Agent(onboarded).handle(OWNER_ID, "удали задачу Лишняя")
    assert isinstance(reply.outbox[0], OutConfirm)
    assert (await task_service.get_task(onboarded.sf, task.id)).title == "Лишняя"


async def test_agent_stops_after_max_iterations(onboarded, fake_llm):
    onboarded.settings.max_tool_iterations = 2
    fake_llm.add(
        response(tool_block("list_tasks", {}, id="t1")),
        response(tool_block("list_tasks", {}, id="t2")),
    )
    reply = await Agent(onboarded).handle(OWNER_ID, "цикл")
    assert "многошаговой" in reply.text
    assert len(fake_llm.calls) == 2


async def test_agent_refusal_retry_and_empty_text(onboarded, fake_llm):
    fake_llm.add(
        response(text_block(""), stop_reason="refusal", model="claude-sonnet-5-5"),
        response(text_block("")),
    )
    reply = await Agent(onboarded).handle(OWNER_ID, "Проанализируй всё")
    assert fake_llm.calls[0]["model"] == "claude-sonnet-5-5"
    assert fake_llm.calls[1]["model"] == "claude-haiku-4-5"
    assert reply.text  # не пустой ответ


async def test_agent_max_tokens_note(onboarded, fake_llm):
    fake_llm.add(response(text_block("Длинный ответ"), stop_reason="max_tokens"))
    reply = await Agent(onboarded).handle(OWNER_ID, "расскажи всё")
    assert "обрезан" in reply.text
