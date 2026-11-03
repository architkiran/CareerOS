import json
from pathlib import Path
from typing import Any

from careeros.modules.sources.http import Fetcher, FetchPolicy

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(clock: FakeClock | None = None, **policy: Any) -> Fetcher:
    clock = clock or FakeClock()
    return Fetcher(policy=FetchPolicy(**policy), sleep=clock.sleep, monotonic=clock.monotonic)


GH_URL = "https://boards-api.greenhouse.io/v1/boards/examplepay/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/examplebank"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/examplecard"
