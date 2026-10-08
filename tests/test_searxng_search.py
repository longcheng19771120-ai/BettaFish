import importlib
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "utils") not in sys.path:
    sys.path.append(str(PROJECT_ROOT / "utils"))

import searxng_client  # noqa: E402


WEB_PAGE = {
    "results": [
        {"title": "新闻一", "url": "https://a.example/1", "content": "摘要一", "publishedDate": "2026-10-07T08:00:00"},
        {"title": "新闻二", "url": "https://a.example/2", "content": "摘要二", "publishedDate": None},
        {"title": "重复", "url": "https://a.example/1", "content": "重复结果"},
    ],
    "answers": [{"answer": "即时答案"}],
    "suggestions": ["相关搜索"],
}
IMAGE_PAGE = {
    "results": [
        {"title": "图片", "url": "https://a.example/page", "img_src": "https://a.example/img.jpg",
         "thumbnail_src": "https://a.example/thumb.jpg"},
    ]
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise searxng_client.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def fake_searxng(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        if params["categories"] == "images":
            return FakeResponse(IMAGE_PAGE)
        if params["pageno"] > 1:
            return FakeResponse({"results": []})
        return FakeResponse(WEB_PAGE)

    monkeypatch.setattr(searxng_client.requests, "get", fake_get)
    return calls


def _load_tools_module(monkeypatch, engine):
    """只加载 <engine>.tools，避免触发 Agent 及其重量级依赖的导入"""
    package = types.ModuleType(engine)
    package.__path__ = [str(PROJECT_ROOT / engine)]
    monkeypatch.setitem(sys.modules, engine, package)
    for name in list(sys.modules):
        if name.startswith(f"{engine}.tools"):
            monkeypatch.delitem(sys.modules, name)
    return importlib.import_module(f"{engine}.tools.searxng_search")


def test_client_dedupes_and_requests_json(fake_searxng):
    client = searxng_client.SearXNGClient(base_url="http://searxng:8080/")
    result = client.search("测试", categories="news", time_range="week", max_results=10)

    assert [h.url for h in result.hits] == ["https://a.example/1", "https://a.example/2"]
    assert result.answers == ["即时答案"]
    assert fake_searxng[0]["format"] == "json"
    assert fake_searxng[0]["time_range"] == "week"
    assert fake_searxng[0]["language"] == "zh-CN"


def test_time_range_for_start_date():
    now = datetime(2026, 10, 8)
    assert searxng_client.time_range_for_start_date("2026-10-08", now) == "day"
    assert searxng_client.time_range_for_start_date("2026-10-03", now) == "week"
    assert searxng_client.time_range_for_start_date("2026-09-20", now) == "month"
    assert searxng_client.time_range_for_start_date("2026-01-01", now) == "year"
    assert searxng_client.time_range_for_start_date("2020-01-01", now) is None
    assert searxng_client.time_range_for_start_date("bad", now) is None


def test_filter_hits_by_date_keeps_undated():
    hits = [
        searxng_client.SearXNGHit("in", "u1", "", published_date="2026-10-05T10:00:00Z"),
        searxng_client.SearXNGHit("out", "u2", "", published_date="2026-09-01"),
        searxng_client.SearXNGHit("undated", "u3", ""),
    ]
    kept = searxng_client.filter_hits_by_date(hits, "2026-10-01", "2026-10-07")
    assert [h.title for h in kept] == ["in", "undated"]


def test_query_engine_agency_matches_tavily_interface(monkeypatch, fake_searxng):
    module = _load_tools_module(monkeypatch, "QueryEngine")
    agency = module.SearXNGNewsAgency(base_url="http://searxng:8080")

    response = agency.basic_search_news("测试", max_results=5)
    assert type(response).__name__ == "TavilyResponse"
    assert response.results[0].title == "新闻一"
    assert response.results[0].published_date == "2026-10-07T08:00:00"
    assert response.answer is None

    assert agency.deep_search_news("测试").answer == "即时答案"
    assert fake_searxng[-1]["categories"] == "general"

    agency.search_news_last_24_hours("测试")
    assert fake_searxng[-1]["categories"] == "news"
    assert fake_searxng[-1]["time_range"] == "day"

    images = agency.search_images_for_news("测试")
    assert images.results and images.images[0].url == "https://a.example/img.jpg"

    dated = agency.search_news_by_date("测试", "2026-10-01", "2026-10-07")
    assert [r.url for r in dated.results] == ["https://a.example/1", "https://a.example/2"]


def test_media_engine_search_matches_bocha_interface(monkeypatch, fake_searxng):
    module = _load_tools_module(monkeypatch, "MediaEngine")
    search = module.SearXNGMultimodalSearch(base_url="http://searxng:8080")

    response = search.comprehensive_search("测试", max_results=10)
    assert type(response).__name__ == "BochaResponse"
    assert response.webpages[0].name == "新闻一"
    assert response.webpages[0].snippet == "摘要一"
    assert response.images[0].content_url == "https://a.example/img.jpg"
    assert response.follow_ups == ["相关搜索"]

    for tool in ("web_search_only", "search_for_structured_data", "search_last_24_hours", "search_last_week"):
        assert getattr(search, tool)("测试").webpages


def test_search_failure_returns_empty_response(monkeypatch):
    def broken_get(*args, **kwargs):
        raise searxng_client.requests.ConnectionError("searxng down")

    monkeypatch.setattr(searxng_client.requests, "get", broken_get)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    module = _load_tools_module(monkeypatch, "QueryEngine")

    response = module.SearXNGNewsAgency(base_url="http://nowhere").basic_search_news("测试")
    assert response.results == []
