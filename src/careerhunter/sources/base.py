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
        """Retry transient ATS errors, never retry permanent authentication errors.

        Retry-After from a remote server is capped so one broken source cannot
        stall the entire four-country daily scan.
        """
        delay = 1.0
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": self.user_agent}) as client:
            for attempt in range(self.retries):
                try:
                    response = client.get(url)
                except httpx.RequestError:
                    if attempt + 1 == self.retries:
                        raise SourceError(f"{self.name}: transport_error") from None
                    time.sleep(min(delay, 8.0))
                    delay = min(delay * 2, 8.0)
                    continue

                code = response.status_code
                if code == 429 or code >= 500:
                    if attempt + 1 == self.retries:
                        raise SourceError(f"{self.name}: HTTP {code}")
                    retry_after = response.headers.get("Retry-After", "")
                    seconds = (
                        min(float(retry_after), 8.0)
                        if retry_after.isdigit() and len(retry_after) <= 8
                        else min(delay, 8.0)
                    )
                    time.sleep(seconds)
                    delay = min(delay * 2, 8.0)
                    continue
                if code >= 300:
                    # 3xx unexpected redirects and 4xx auth/config errors are
                    # not fixed by another identical API request.
                    raise SourceError(f"{self.name}: HTTP {code}")
                try:
                    return response.json()
                except (ValueError, TypeError):
                    raise SourceError(f"{self.name}: invalid_json") from None
        raise SourceError(f"{self.name}: request failed")

    @abstractmethod
    def fetch(self, company: str, slug: str) -> list[Job]: ...

