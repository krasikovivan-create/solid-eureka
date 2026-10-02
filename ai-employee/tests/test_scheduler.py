import asyncio
from datetime import timedelta

from apscheduler.triggers.cron import CronTrigger

from app.scheduler.scheduler import BotScheduler
from app.services import profile as profile_service
from app.services import tasks as task_service
from app.services.timeutils import now_utc
from tests.conftest import OWNER_ID, SentLog


async def test_reminder_scheduled_at_exact_time(onboarded):
    when = now_utc() + timedelta(hours=3)
    task = await task_service.create_task(onboarded.sf, OWNER_ID, "Позвонить", remind_at=when)
    onboarded.scheduler.schedule_task_reminder(task)
    job = onboarded.scheduler.scheduler.get_job(f"reminder:{task.id}")
    assert job.next_run_time == when


async def test_fire_reminder_sends_and_marks(onboarded):
    sent = onboarded.extra["sent"]
    task = await task_service.create_task(
        onboarded.sf, OWNER_ID, "Позвонить Иванову", priority="urgent", remind_at=now_utc()
    )
    assert await onboarded.scheduler.fire_reminder(task.id) is True
    user_id, text, _ = sent[-1]
    assert user_id == OWNER_ID and "Позвонить Иванову" in text and "Напоминание" in text
    assert (await task_service.get_task(onboarded.sf, task.id)).reminder_sent
    # повторно не отправляется
    assert await onboarded.scheduler.fire_reminder(task.id) is False
    assert len(sent) == 1


async def test_reminder_actually_fires_via_apscheduler(onboarded):
    sent = onboarded.extra["sent"]
    task = await task_service.create_task(
        onboarded.sf, OWNER_ID, "Скоро", remind_at=now_utc() + timedelta(seconds=1)
    )
    onboarded.scheduler.schedule_task_reminder(task)
    for _ in range(40):
        if sent:
            break
        await asyncio.sleep(0.1)
    assert sent and "Скоро" in sent[0][1]


async def test_done_task_is_not_reminded(onboarded):
    task = await task_service.create_task(onboarded.sf, OWNER_ID, "x", remind_at=now_utc())
    await task_service.update_task(onboarded.sf, task.id, status="done")
    assert await onboarded.scheduler.fire_reminder(task.id) is False


async def test_restore_after_restart(onboarded):
    """Напоминания живут в БД: новый планировщик (после перезапуска) их восстанавливает."""
    sf = onboarded.sf
    future = await task_service.create_task(
        sf, OWNER_ID, "Будущее", remind_at=now_utc() + timedelta(days=1)
    )
    await task_service.create_task(
        sf, OWNER_ID, "Пропущенное", remind_at=now_utc() - timedelta(hours=1)
    )
    done = await task_service.create_task(sf, OWNER_ID, "Готово", remind_at=now_utc())
    await task_service.update_task(sf, done.id, status="done")

    sent = SentLog()
    fresh = BotScheduler(onboarded, sent)
    await fresh.start()
    try:
        assert fresh.scheduler.get_job(f"reminder:{future.id}") is not None
        assert fresh.scheduler.get_job(f"reminder:{done.id}") is None
        assert fresh.scheduler.get_job("daily:morning") is not None
        assert fresh.scheduler.get_job("daily:evening") is not None
        assert fresh.scheduler.get_job("sweep") is not None
        # пропущенное за время простоя уходит почти сразу
        for _ in range(50):
            if sent:
                break
            await asyncio.sleep(0.1)
        assert any("Пропущенное" in text for _, text, _ in sent)
    finally:
        fresh.shutdown()


async def test_sweep_catches_unscheduled(onboarded):
    sent = onboarded.extra["sent"]
    await task_service.create_task(
        onboarded.sf, OWNER_ID, "Без джобы", remind_at=now_utc() - timedelta(minutes=5)
    )
    assert await onboarded.scheduler.sweep() == 1
    assert "Без джобы" in sent[-1][1]
    assert await onboarded.scheduler.sweep() == 0


async def test_rescheduled_reminder_not_sent_early(onboarded):
    task = await task_service.create_task(onboarded.sf, OWNER_ID, "x", remind_at=now_utc())
    await task_service.update_task(onboarded.sf, task.id, remind_at=now_utc() + timedelta(hours=2))
    assert await onboarded.scheduler.fire_reminder(task.id) is False
    assert onboarded.scheduler.scheduler.get_job(f"reminder:{task.id}") is not None


async def test_daily_jobs_follow_settings(onboarded):
    sched = onboarded.scheduler
    await profile_service.update_profile(
        onboarded.sf, morning_time="08:30", evening_time="20:15", timezone="Asia/Yekaterinburg"
    )
    await sched.reschedule_daily()
    morning = sched.scheduler.get_job("daily:morning")
    assert isinstance(morning.trigger, CronTrigger)
    fields = {f.name: str(f) for f in morning.trigger.fields}
    assert fields["hour"] == "8" and fields["minute"] == "30"
    assert str(morning.trigger.timezone) == "Asia/Yekaterinburg"
    evening = sched.scheduler.get_job("daily:evening")
    fields = {f.name: str(f) for f in evening.trigger.fields}
    assert fields["hour"] == "20" and fields["minute"] == "15"

    await profile_service.update_profile(onboarded.sf, morning_enabled=False)
    await sched.reschedule_daily()
    assert sched.scheduler.get_job("daily:morning") is None


async def test_morning_and_evening_broadcast(onboarded):
    sent = onboarded.extra["sent"]
    await task_service.create_task(
        onboarded.sf, OWNER_ID, "Утренняя задача", due_at=now_utc() + timedelta(minutes=1)
    )
    assert await onboarded.scheduler.send_morning() == 1
    assert "Доброе утро" in sent[-1][1]
    t = await task_service.create_task(onboarded.sf, OWNER_ID, "Закрытая")
    await task_service.update_task(onboarded.sf, t.id, status="done")
    assert await onboarded.scheduler.send_evening() == 1
    assert "Итоги дня" in sent[-1][1] and "Закрытая" in sent[-1][1]


async def test_no_broadcast_before_onboarding(app):
    await profile_service.try_claim_owner(app.sf, OWNER_ID)
    assert await app.scheduler.send_morning() == 0
