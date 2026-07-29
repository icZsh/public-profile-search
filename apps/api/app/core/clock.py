from dataclasses import dataclass
from datetime import UTC, datetime


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FixedClock(Clock):
    value: datetime

    def now(self) -> datetime:
        return self.value
