from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.jobs import Jobs

logger = logging.getLogger(__name__)


def setup_scheduler(jobs: Jobs, timezone: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)
    common = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 120}
    scheduler.add_job(jobs.broadcasts, "interval", minutes=1, id="broadcasts", **common)
    scheduler.add_job(jobs.abandoned_carts, "interval", minutes=15, id="abandoned_carts", **common)
    scheduler.add_job(jobs.favorite_alerts, "interval", minutes=30, id="favorites", **common)
    scheduler.add_job(jobs.sync_tracking, "interval", hours=1, id="tracking", **common)
    scheduler.add_job(jobs.cancel_unpaid, "interval", hours=1, id="unpaid", **common)
    return scheduler
