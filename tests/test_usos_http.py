"""CachedHttp: cache hits, expiry per kind, --refresh, offline and failed refetches."""

import os
import time

import pytest

from metro_agh.usos.fetch import FAILED_IN_A_ROW, _page
from metro_agh.usos.http import CachedHttp, FetchFailed, OfflineMiss


class Fake(CachedHttp):
    """No network: every GET answers ``page <n>`` (or fails when ``down``)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, user_agent="test", delay_s=0.0, **kw)
        self.calls = 0
        self.down = False

    def _get(self, url: str) -> str:
        if self.down:
            raise FetchFailed(f"giving up on {url}")
        self.calls += 1
        return f"page {self.calls}"


def age(http: CachedHttp, kind: str, url: str, seconds: float) -> None:
    f = http._file(kind, url, ".html")
    t = time.time() - seconds
    os.utime(f, (t, t))


def test_cache_hit_and_expiry(tmp_path):
    h = Fake(tmp_path, max_age_s={"web/unit": 3600})
    assert h.text("web/unit", "https://x/u") == "page 1"
    assert h.text("web/unit", "https://x/u") == "page 1"  # cached
    assert h.text("web/course", "https://x/c") == "page 2"
    age(h, "web/unit", "https://x/u", 7200)
    age(h, "web/course", "https://x/c", 10**8)
    assert h.text("web/unit", "https://x/u") == "page 3"  # older than its max age
    assert h.text("web/course", "https://x/c") == "page 2"  # no max age: kept
    assert not list(tmp_path.rglob("*.part"))


def test_refresh_offline_and_failures(tmp_path):
    Fake(tmp_path).text("web/unit", "https://x/u")
    h = Fake(tmp_path, refresh=True)
    assert h.text("web/unit", "https://x/u") == "page 1"  # fetched again
    h.down = True
    assert h.text("web/unit", "https://x/u") == "page 1"  # refetch failed: old copy
    assert h.n_stale == 1
    with pytest.raises(RuntimeError):
        h.text("web/unit", "https://x/new")

    off = Fake(tmp_path, offline=True, refresh=True)
    assert off.text("web/unit", "https://x/u") == "page 1"  # offline never fetches
    with pytest.raises(OfflineMiss):
        off.text("web/unit", "https://x/missing")
    assert off.calls == 0


def test_failing_page_is_skipped_until_an_outage(tmp_path):
    h = Fake(tmp_path)
    h.down = True
    assert _page(h, "web/unit", {"id": 1}) is None  # skipped, counted, not cached
    assert h.n_failed == 1 and not list(tmp_path.rglob("*.html"))
    h.down = False
    assert _page(h, "web/unit", {"id": 1}) == "page 1"  # the rerun fetches it
    assert h.failed_in_a_row == 0
    h.down = True
    for i in range(FAILED_IN_A_ROW - 1):
        _page(h, "web/unit", {"id": 100 + i})
    with pytest.raises(RuntimeError, match="in a row"):
        _page(h, "web/unit", {"id": 999})
