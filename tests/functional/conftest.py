from typing import Generator

import pytest
from apscheduler.schedulers.background import BackgroundScheduler


@pytest.fixture(autouse=True)
def scheduler() -> Generator[BackgroundScheduler, None, None]:
    """Use the real scheduler, because the scenarios run the jobs of a connection end to end."""
    from supa import scheduler

    yield scheduler
