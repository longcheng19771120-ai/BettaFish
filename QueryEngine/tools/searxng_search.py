"""
基于本地 SearXNG 的新闻搜索工具集

与 TavilyNewsAgency 提供完全相同的 6 个工具方法并返回 TavilyResponse，
用于本地化部署时在不依赖 Tavily API 的情况下运行 Query Engine。
在 .env 中设置 SEARCH_TOOL_TYPE=SearXNG 与 SEARXNG_BASE_URL 即可启用。
"""

import os
import sys
from typing import List, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
utils_dir = os.path.join(root_dir, 'utils')
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

from loguru import logger
from retry_helper import with_graceful_retry, SEARCH_API_RETRY_CONFIG
from searxng_client import (
    SearXNGClient,
    SearXNGHit,
    filter_hits_by_date,
    time_range_for_start_date,
)

from .search import ImageResult, SearchResult, TavilyResponse


class SearXNGNewsAgency:
    """方法签名与 TavilyNewsAgency 一致，可直接替换"""

    def __init__(self, base_url: Optional[str] = None):
        self._client = SearXNGClient(base_url=base_url)

    @with_graceful_retry(SEARCH_API_RETRY_CONFIG, default_return=TavilyResponse(query="搜索失败"))
    def _search(self, query: str, categories: str = "general", time_range: Optional[str] = None,
                max_results: int = 10, include_answer: bool = False,
                start_date: Optional[str] = None, end_date: Optional[str] = None) -> TavilyResponse:
        result = self._client.search(query, categories=categories, time_range=time_range, max_results=max_results)
        hits = result.hits
        if start_date and end_date:
            hits = filter_hits_by_date(hits, start_date, end_date)

        if categories == "images":
            return TavilyResponse(
                query=query,
                images=[ImageResult(url=h.img_src or h.url, description=h.title or h.content) for h in hits],
            )

        answer = "\n".join(result.answers) if include_answer and result.answers else None
        return TavilyResponse(query=query, answer=answer, results=_to_search_results(hits))

    def basic_search_news(self, query: str, max_results: int = 7) -> TavilyResponse:
        logger.info(f"--- TOOL: 基础新闻搜索[SearXNG] (query: {query}) ---")
        return self._search(query, max_results=max_results)

    def deep_search_news(self, query: str) -> TavilyResponse:
        logger.info(f"--- TOOL: 深度新闻分析[SearXNG] (query: {query}) ---")
        return self._search(query, max_results=20, include_answer=True)

    def search_news_last_24_hours(self, query: str) -> TavilyResponse:
        logger.info(f"--- TOOL: 搜索24小时内新闻[SearXNG] (query: {query}) ---")
        return self._search(query, categories="news", time_range="day", max_results=10)

    def search_news_last_week(self, query: str) -> TavilyResponse:
        logger.info(f"--- TOOL: 搜索本周新闻[SearXNG] (query: {query}) ---")
        return self._search(query, categories="news", time_range="week", max_results=10)

    def search_images_for_news(self, query: str) -> TavilyResponse:
        logger.info(f"--- TOOL: 查找新闻图片[SearXNG] (query: {query}) ---")
        # 同时返回网页结果，保证后续总结节点有文本可用
        response = self._search(query, max_results=5)
        images = self._search(query, categories="images", max_results=5)
        response.images = images.images
        return response

    def search_news_by_date(self, query: str, start_date: str, end_date: str) -> TavilyResponse:
        logger.info(f"--- TOOL: 按日期范围搜索新闻[SearXNG] (query: {query}, from: {start_date}, to: {end_date}) ---")
        # SearXNG 不支持任意日期区间：先用能覆盖起始日期的 time_range 搜索，再按发布日期过滤
        return self._search(
            query,
            time_range=time_range_for_start_date(start_date),
            max_results=15,
            start_date=start_date,
            end_date=end_date,
        )


def _to_search_results(hits: List[SearXNGHit]) -> List[SearchResult]:
    return [
        SearchResult(
            title=h.title,
            url=h.url,
            content=h.content,
            score=h.score,
            raw_content=h.content,
            published_date=h.published_date,
        )
        for h in hits
    ]
