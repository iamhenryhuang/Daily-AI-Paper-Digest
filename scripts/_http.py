"""Minimal HTTP helpers with retry logic."""

from __future__ import annotations

import socket
import sys
import time
import urllib.error
import urllib.request


def _request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    retries: int = 3,
    as_text: bool = True,
) -> str | bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                return raw.decode("utf-8") if as_text else raw
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:800]}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt == retries:
                raise RuntimeError(f"Network error calling {url}: {exc}") from exc
            last_error = exc

        wait_seconds = min(30, 2 ** attempt)
        print(f"Request failed, retrying in {wait_seconds}s ({attempt}/{retries}): {last_error}", file=sys.stderr)
        time.sleep(wait_seconds)

    raise RuntimeError(f"Network error calling {url}: {last_error}")


def request_text(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 60, retries: int = 3) -> str:
    return _request(url, data=data, headers=headers, timeout=timeout, retries=retries, as_text=True)  # type: ignore[return-value]


def request_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: int = 60, retries: int = 3) -> bytes:
    return _request(url, headers=headers, timeout=timeout, retries=retries, as_text=False)  # type: ignore[return-value]
