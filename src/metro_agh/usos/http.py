"""Polite HTTP with a disk cache, for the public USOS API and the public USOSweb catalogue.

Every response is stored under ``data/raw/usos/`` before it is parsed, so a crawl can be
stopped and resumed, and the parsers can be rerun without touching the network
(``offline=True``). Requests are spaced by ``delay_s`` and retried with backoff.

Cached pages expire: ``max_age_s`` maps a cache kind prefix (``web/unit``) to the age after
which the page is fetched again, because the counts of registered students change until the
registration closes. ``refresh=True`` fetches everything again. When a refetch fails, the old
copy is used (with a warning) rather than losing the page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)


class OfflineMiss(LookupError):
    """``offline=True`` and the page is not in the cache."""


class CachedHttp:
    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str,
        delay_s: float = 0.5,
        retries: int = 4,
        timeout_s: float = 60.0,
        offline: bool = False,
        max_requests: int | None = None,
        max_age_s: dict[str, float] | None = None,
        refresh: bool = False,
    ):
        self.cache_dir = Path(cache_dir)
        self.delay_s = delay_s
        self.retries = retries
        self.timeout_s = timeout_s
        self.offline = offline
        self.max_requests = max_requests
        self.max_age_s = dict(max_age_s or {})
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.n_requests = 0
        self.n_cached = 0
        self.n_stale = 0  # refetch failed, old copy used
        self._last = 0.0

    def _expired(self, kind: str, f: Path) -> bool:
        if self.refresh:
            return True
        ages = [age for prefix, age in self.max_age_s.items() if kind.startswith(prefix)]
        if not ages:
            return False
        return time.time() - f.stat().st_mtime > min(ages)

    def _file(self, kind: str, url: str, suffix: str) -> Path:
        digest = hashlib.sha1(url.encode()).hexdigest()[:20]
        return self.cache_dir / kind / f"{digest}{suffix}"

    def text(self, kind: str, base: str, params: dict | None = None, suffix=".html") -> str:
        """GET ``base?params`` as text (cached under ``<cache_dir>/<kind>/``)."""
        url = f"{base}?{urlencode(params)}" if params else base
        f = self._file(kind, url, suffix)
        cached = f.exists()
        if cached and (self.offline or not self._expired(kind, f)):
            self.n_cached += 1
            return f.read_text(encoding="utf-8")
        budget = self.max_requests is not None and self.n_requests >= self.max_requests
        if self.offline or budget:
            if cached:  # budget used up: an old copy beats nothing
                self.n_stale += 1
                return f.read_text(encoding="utf-8")
            raise OfflineMiss(url if self.offline else f"request budget used up: {url}")
        try:
            body = self._get(url)
        except RuntimeError:
            if not cached:
                raise
            log.warning("%s: keeping the cached copy from %s", url, time.ctime(f.stat().st_mtime))
            self.n_stale += 1
            return f.read_text(encoding="utf-8")
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f.suffix + ".part")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(f)  # never a half-written page in the cache
        return body

    def json(self, kind: str, base: str, params: dict | None = None):
        return json.loads(self.text(kind, base, params, suffix=".json"))

    def _get(self, url: str) -> str:
        for attempt in range(self.retries + 1):
            wait = self.delay_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.n_requests += 1
            try:
                r = self.session.get(url, timeout=self.timeout_s)
            except requests.RequestException as err:
                problem = str(err)
            else:
                if r.status_code == 200:
                    r.encoding = r.encoding or "utf-8"
                    return r.text
                if r.status_code in (400, 404):
                    # USOS API answers "object not found" with 400/404 and a JSON body
                    return r.text
                problem = f"HTTP {r.status_code}"
            backoff = min(60.0, 2.0**attempt * max(self.delay_s, 0.5))
            log.warning("%s: %s, retry in %.0f s", url, problem, backoff)
            time.sleep(backoff)
        raise RuntimeError(f"giving up on {url}")
