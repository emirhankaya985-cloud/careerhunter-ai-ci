from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from careerhunter.models import Job


class SourceError(RuntimeError):
    pass


class JobSource(ABC):
    name: str

    def __init__(self, timeout: float = 20, retries: int = 3, user_agent: str = "CareerHunterAI/0.1"):
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent

    def get_json(self, url: str) -> Any:
        delay = 1.0
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": self.user_agent}) as client:
            for attempt in range(self.retries):
                try:
                    response = client.get(url)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt + 1 == self.retries:
                            raise SourceError(f"{self.name}: HTTP {response.status_code}")
                        retry_after = response.headers.get("Retry-After")
                        time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                        delay *= 2
                        continue
                    response.raise_for_status()
                    return response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt + 1 == self.retries:
                        raise SourceError(f"{self.name}: {type(exc).__name__}") from exc
                    time.sleep(delay)
                    delay *= 2
        raise SourceError(f"{self.name}: request failed")

    @abstractmethod
    def fetch(self, company: str, slug: str) -> list[Job]: ...

