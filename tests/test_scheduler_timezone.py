# -*- coding: utf-8 -*-

from src.scheduler import DEFAULT_MARKET_TIMEZONE, Scheduler


def test_scheduler_registers_daily_job_with_market_timezone():
    scheduler = Scheduler(schedule_time="08:00", market_timezone="Australia/Sydney")
    scheduler.schedule.clear()

    try:
        scheduler.set_daily_task(lambda: None, run_immediately=False)
        jobs = scheduler.schedule.get_jobs()

        assert len(jobs) == 1
        assert getattr(jobs[0].at_time_zone, "zone", "") == "Australia/Sydney"
        assert "Australia/Sydney" in scheduler._get_next_run_time()
    finally:
        scheduler.schedule.clear()


def test_scheduler_invalid_timezone_falls_back_to_sydney():
    scheduler = Scheduler(schedule_time="08:00", market_timezone="Invalid/Timezone")

    assert scheduler.market_timezone == DEFAULT_MARKET_TIMEZONE
