"""
SearXNG 本地搜索客户端

SearXNG 是可自建的开源元搜索引擎，用于在本地化部署时替代 Tavily / Bocha / Anspire
等付费搜索 API。Query Engine 与 Media Engine 的 SearXNG 适配器都基于本模块。

要求 SearXNG 实例在 settings.yml 中开启 json 输出格式：
    search:
      formats: [html, json]
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

DEFAULT_SEARXNG_BASE_URL = "http://localhost:8080"

# SearXNG 只支持这几档 time_range，按时间跨度从小到大排列
_TIME_RANGES = [("day", 1), ("week", 7), ("month", 31), ("year", 366)]


@dataclass
class SearXNGHit:
    """一条 SearXNG 搜索结果（网页或图片）"""
    title: str
    url: str
    content: str
    published_date: Optional[str] = None
    score: Optional[float] = None
    img_src: Optional[str] = None
    thumbnail_src: Optional[str] = None


@dataclass
class SearXNGResult:
    """一次 SearXNG 查询的汇总结果"""
    query: str
    hits: List[SearXNGHit]
    answers: List[str]
    suggestions: List[str]


def time_range_for_start_date(start_date: str, now: Optional[datetime] = None) -> Optional[str]:
    """返回能覆盖 start_date 至今的最小 SearXNG time_range；超过一年返回 None（不限时间）。"""
    now = now or datetime.now()
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    days = (now - start).days + 1
    for name, span in _TIME_RANGES:
        if days <= span:
            return name
    return None


def filter_hits_by_date(hits: List[SearXNGHit], start_date: str, end_date: str) -> List[SearXNGHit]:
    """按发布日期过滤结果；没有发布日期的结果予以保留。"""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except (TypeError, ValueError):
        return hits

    kept = []
    for hit in hits:
        published = _parse_date(hit.published_date)
        if published is None or start <= published < end:
            kept.append(hit)
    return kept


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class SearXNGClient:
    """对 SearXNG JSON API 的最小封装"""

    def __init__(self, base_url: Optional[str] = None, language: str = "zh-CN", timeout: float = 30):
        self.base_url = (base_url or DEFAULT_SEARXNG_BASE_URL).rstrip("/")
        self.language = language
        self.timeout = timeout

    def search(
        self,
        query: str,
        categories: str = "general",
        time_range: Optional[str] = None,
        max_results: int = 10,
        max_pages: int = 3,
    ) -> SearXNGResult:
        """执行搜索，必要时翻页直到凑够 max_results 条结果。网络错误会直接抛出，由调用方的重试机制处理。"""
        hits: List[SearXNGHit] = []
        answers: List[str] = []
        suggestions: List[str] = []
        seen_urls = set()

        for page in range(1, max_pages + 1):
            data = self._request(query, categories, time_range, page)
            page_results = data.get("results") or []
            for item in page_results:
                url = item.get("url") or item.get("img_src")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                hits.append(SearXNGHit(
                    title=item.get("title") or "",
                    url=url,
                    content=item.get("content") or "",
                    published_date=item.get("publishedDate"),
                    score=item.get("score"),
                    img_src=item.get("img_src"),
                    thumbnail_src=item.get("thumbnail_src") or item.get("thumbnail"),
                ))
            if page == 1:
                answers = [_answer_text(a) for a in data.get("answers") or []]
                answers = [a for a in answers if a]
                suggestions = list(data.get("suggestions") or [])
            if len(hits) >= max_results or not page_results:
                break

        return SearXNGResult(query=query, hits=hits[:max_results], answers=answers, suggestions=suggestions)

    def _request(self, query: str, categories: str, time_range: Optional[str], page: int) -> Dict[str, Any]:
        params = {
            "q": query,
            "format": "json",
            "categories": categories,
            "language": self.language,
            "pageno": page,
        }
        if time_range:
            params["time_range"] = time_range
        response = requests.get(f"{self.base_url}/search", params=params, timeout=self.timeout)
        if response.status_code == 403:
            logger.error("SearXNG 返回 403：请在 SearXNG 的 settings.yml 中把 json 加入 search.formats")
        response.raise_for_status()
        return response.json()


def _answer_text(answer: Any) -> str:
    # 不同版本的 SearXNG 中 answers 可能是字符串，也可能是 {"answer": ...} 对象
    if isinstance(answer, dict):
        return str(answer.get("answer") or answer.get("content") or "")
    return str(answer or "")
