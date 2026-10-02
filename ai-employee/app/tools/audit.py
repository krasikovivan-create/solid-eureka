"""Инструменты: аудит процессов клиента и коммерческое предложение."""

from __future__ import annotations

from app.agent import workflows
from app.services import audit as audit_service
from app.services import clients as client_service
from app.services import proposals as proposal_service
from app.services.tasks import NotFoundError
from app.tools.base import S_INT, S_STR, OutAuditStarted, OutFile, ToolContext, registry


@registry.register(
    "start_audit",
    "Начать пошаговое интервью-аудит процессов клиента. Укажи client_id (если клиент есть в "
    "базе) или client_name. Бот сам задаст вопросы по очереди.",
    {"client_id": S_INT, "client_name": S_STR},
)
async def start_audit(ctx: ToolContext, client_id: int | None = None, client_name: str = ""):
    name = client_name
    if client_id is None and client_name:
        try:
            client = await client_service.resolve_client(ctx.app.sf, None, client_name)
            client_id, name = client.id, client.company
        except NotFoundError:
            client_id = None
    elif client_id is not None:
        client = await client_service.get_client(ctx.app.sf, client_id)
        name = client.company
    if not name:
        raise ValueError("Укажите, для какого клиента проводим аудит")
    audit = await audit_service.start_audit(ctx.app.sf, ctx.user_id, name, client_id)
    ctx.outbox.append(OutAuditStarted(audit.id))
    return {
        "audit_id": audit.id,
        "client": name,
        "note": "Аудит начат, бот сейчас задаст первый вопрос. Ничего не спрашивай сам.",
    }


@registry.register("list_audits", "Список аудитов (последние 20) со статусами.", {})
async def list_audits(ctx: ToolContext):
    audits = await audit_service.list_audits(ctx.app.sf)
    return [
        {
            "id": a.id,
            "client": a.client_name,
            "status": a.status,
            "answered": len(a.answers or []),
            "saved_hours_per_month": (a.report or {}).get("total_hours_saved_per_month"),
        }
        for a in audits
    ]


@registry.register(
    "get_audit_report",
    "Отчёт по завершённому аудиту: процессы, что автоматизировать, экономия.",
    {"audit_id": S_INT},
    required=["audit_id"],
)
async def get_audit_report(ctx: ToolContext, audit_id: int):
    audit = await audit_service.get_audit(ctx.app.sf, audit_id)
    if not audit.report:
        return {"audit_id": audit.id, "status": audit.status, "report": None}
    return {"audit_id": audit.id, "client": audit.client_name, "report": audit.report}


@registry.register(
    "create_proposal",
    "Сгенерировать коммерческое предложение (проблема → решение → этапы → сроки → стоимость) "
    "по завершённому аудиту и отправить DOCX-файл пользователю.",
    {"audit_id": S_INT},
    required=["audit_id"],
)
async def create_proposal(ctx: ToolContext, audit_id: int):
    proposal, data, filename = await workflows.generate_proposal(ctx.app, audit_id, ctx.user_id)
    content = proposal.content
    ctx.outbox.append(
        OutFile(
            filename,
            data,
            caption=(
                f"📄 КП #{proposal.id}: {content.get('title', '')}\n"
                f"Сроки: ~{content.get('total_weeks', 0):g} нед. · "
                f"Стоимость: {proposal_service.money(proposal.total_cost)}"
            ),
        )
    )
    return {
        "proposal_id": proposal.id,
        "sent_file": filename,
        "total_cost_rub": proposal.total_cost,
        "total_weeks": content.get("total_weeks"),
        "stages": [s["name"] for s in content.get("stages", [])],
    }
