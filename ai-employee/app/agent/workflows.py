"""Сценарии, где ИИ работает с данными: отчёт по аудиту, КП, тексты, сжатие памяти."""

from __future__ import annotations

import logging

from app.agent.prompts import TEXT_KINDS, company_context, writer_system
from app.context import AppContext
from app.services import audit as audit_service
from app.services import clients as client_service
from app.services import memory as memory_service
from app.services import proposals as proposal_service
from app.services.profile import get_profile

log = logging.getLogger(__name__)

SUMMARY_BATCH = 10  # сколько «лишних» сообщений копим перед сжатием


async def generate_audit_report(app: AppContext, audit_id: int, user_id: int | None = None):
    audit = await audit_service.get_audit(app.sf, audit_id)
    profile = await get_profile(app.sf)
    prompt = audit_service.build_report_prompt(audit, company_context(profile))
    report = await app.llm.complete_json(
        prompt=prompt,
        schema=audit_service.REPORT_SCHEMA,
        system="Ты — опытный бизнес-аналитик и консультант по внедрению ИИ в малый и средний бизнес.",
        model=app.llm.smart,
        purpose="audit_report",
        user_id=user_id,
        effort="medium",
    )
    audit = await audit_service.save_report(app.sf, audit_id, report)
    if audit.client_id:
        try:
            await client_service.add_interaction(
                app.sf,
                audit.client_id,
                f"Проведён аудит процессов (#{audit.id}). Потенциальная экономия: "
                f"{audit.report.get('total_hours_saved_per_month', 0):g} ч/мес.",
                kind="meeting",
            )
            client = await client_service.get_client(app.sf, audit.client_id)
            if client.status in ("lead", "contacted"):
                await client_service.update_client(app.sf, audit.client_id, status="audit")
        except Exception:
            log.exception("Не удалось обновить карточку клиента после аудита")
    return audit


async def generate_proposal(app: AppContext, audit_id: int, user_id: int | None = None):
    """Возвращает (proposal, bytes docx, имя файла)."""
    audit = await audit_service.get_audit(app.sf, audit_id)
    if audit.status != "completed" or not audit.report:
        raise ValueError(
            f"Аудит #{audit_id} ещё не завершён — КП делается по готовому отчёту аудита."
        )
    profile = await get_profile(app.sf)
    content = await app.llm.complete_json(
        prompt=proposal_service.build_prompt(audit, company_context(profile)),
        schema=proposal_service.PROPOSAL_SCHEMA,
        system="Ты — руководитель отдела продаж компании, внедряющей ИИ в бизнес клиентов.",
        model=app.llm.smart,
        purpose="proposal",
        user_id=user_id,
        effort="medium",
    )
    content = proposal_service.calculate(content, profile.hourly_rate)
    data = proposal_service.render_docx(content, profile, audit.client_name)
    filename = proposal_service.proposal_filename(audit.client_name)
    proposal = await proposal_service.save_proposal(
        app.sf, app.proposals_dir, audit, content, data, filename
    )
    if audit.client_id:
        try:
            await client_service.add_interaction(
                app.sf,
                audit.client_id,
                f"Подготовлено КП #{proposal.id} на {proposal_service.money(proposal.total_cost)}",
                kind="note",
            )
            client = await client_service.get_client(app.sf, audit.client_id)
            if client.status in ("lead", "contacted", "audit"):
                await client_service.update_client(app.sf, audit.client_id, status="proposal")
        except Exception:
            log.exception("Не удалось обновить карточку клиента после КП")
    return proposal, data, filename


async def write_text(
    app: AppContext,
    kind: str,
    brief: str,
    user_id: int | None = None,
    client_id: int | None = None,
) -> str:
    profile = await get_profile(app.sf)
    kind_label = TEXT_KINDS.get(kind, TEXT_KINDS["other"])
    parts = [f"Задача: напиши {kind_label}.", f"Что нужно: {brief}"]
    if client_id:
        client = await client_service.get_client(app.sf, client_id)
        facts = await memory_service.list_facts(app.sf, client_id=client_id)
        parts.append(
            "Данные клиента: "
            + ", ".join(
                f"{k}: {v}"
                for k, v in client_service.client_to_dict(client, profile.timezone).items()
                if v and k != "id"
            )
        )
        if facts:
            parts.append("Факты о клиенте: " + "; ".join(f.content for f in facts))
    company_facts = [
        f for f in await memory_service.list_facts(app.sf, limit=30) if not f.client_id
    ]
    if company_facts:
        parts.append("Факты о нашей компании: " + "; ".join(f.content for f in company_facts))
    return await app.llm.complete_text(
        prompt="\n\n".join(parts),
        system=writer_system(profile),
        model=app.llm.smart,
        max_tokens=app.settings.max_tokens_per_request,
        purpose=f"text_{kind}",
        user_id=user_id,
        effort="low",
    )


async def maybe_summarize(app: AppContext, user_id: int) -> bool:
    """Сжимает старую часть истории в резюме, оставляя последние HISTORY_LIMIT сообщений."""
    limit = app.settings.history_limit
    messages = await memory_service.unsummarized_messages(app.sf, user_id)
    if len(messages) <= limit + SUMMARY_BATCH:
        return False
    old = messages[: len(messages) - limit]
    previous = await memory_service.get_summary(app.sf, user_id)
    transcript = "\n".join(
        f"{'Пользователь' if m.role == 'user' else 'Ассистент'}: {m.content[:1500]}" for m in old
    )
    prompt = (
        (f"Текущее резюме:\n{previous.summary}\n\n" if previous and previous.summary else "")
        + f"Новые сообщения:\n{transcript}\n\n"
        "Обнови резюме переписки: 5–15 пунктов, только важное — договорённости, решения, "
        "упомянутые клиенты, открытые вопросы. Без вступлений."
    )
    try:
        summary = await app.llm.complete_text(
            prompt=prompt,
            system="Ты кратко и точно резюмируешь деловую переписку на русском.",
            model=app.llm.fast,
            max_tokens=1500,
            purpose="summary",
            user_id=user_id,
        )
    except Exception:
        log.exception("Не удалось сжать историю диалога")
        return False
    await memory_service.save_summary(app.sf, user_id, summary, old[-1].id)
    return True
