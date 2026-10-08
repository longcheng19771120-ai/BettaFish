"""
基于本地 SearXNG 的多模态搜索工具集

与 BochaMultimodalSearch 提供相同的 5 个工具方法并返回 BochaResponse，
用于本地化部署时在不依赖 Bocha / Anspire API 的情况下运行 Media Engine。
SearXNG 没有 AI 总结与模态卡，对应字段保持为空。
在 .env 中设置 SEARCH_TOOL_TYPE=SearXNG 与 SEARXNG_BASE_URL 即可启用。
"""

import os
import sys
from typing import Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
utils_dir = os.path.join(root_dir, 'utils')
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

from loguru import logger
from retry_helper import with_graceful_retry, SEARCH_API_RETRY_CONFIG
from searxng_client import SearXNGClient

from .search import BochaResponse, ImageResult, WebpageResult


class SearXNGMultimodalSearch:
    """方法签名与 BochaMultimodalSearch 一致，可直接替换"""

    def __init__(self, base_url: Optional[str] = None):
        self._client = SearXNGClient(base_url=base_url)

    @with_graceful_retry(SEARCH_API_RETRY_CONFIG, default_return=BochaResponse(query="搜索失败"))
    def _search(self, query: str, categories: str = "general", time_range: Optional[str] = None,
                max_results: int = 10, with_images: bool = False) -> BochaResponse:
        result = self._client.search(query, categories=categories, time_range=time_range, max_results=max_results)
        response = BochaResponse(
            query=query,
            answer="\n".join(result.answers) or None,
            follow_ups=result.suggestions,
            webpages=[
                WebpageResult(
                    name=h.title,
                    url=h.url,
                    snippet=h.content,
                    display_url=h.url,
                    date_last_crawled=h.published_date,
                )
                for h in result.hits
            ],
        )
        if with_images:
            images = self._client.search(query, categories="images", max_results=5)
            response.images = [
                ImageResult(
                    name=h.title,
                    content_url=h.img_src or h.url,
                    host_page_url=h.url,
                    thumbnail_url=h.thumbnail_src,
                )
                for h in images.hits
            ]
        return response

    def comprehensive_search(self, query: str, max_results: int = 10) -> BochaResponse:
        logger.info(f"--- TOOL: 全面综合搜索[SearXNG] (query: {query}) ---")
        return self._search(query, max_results=max_results, with_images=True)

    def web_search_only(self, query: str, max_results: int = 15) -> BochaResponse:
        logger.info(f"--- TOOL: 纯网页搜索[SearXNG] (query: {query}) ---")
        return self._search(query, max_results=max_results)

    def search_for_structured_data(self, query: str) -> BochaResponse:
        # SearXNG 没有模态卡，退化为普通网页搜索；instant answer 会放在 answer 字段
        logger.info(f"--- TOOL: 结构化数据查询[SearXNG] (query: {query}) ---")
        return self._search(query, max_results=10)

    def search_last_24_hours(self, query: str) -> BochaResponse:
        logger.info(f"--- TOOL: 搜索24小时内信息[SearXNG] (query: {query}) ---")
        return self._search(query, categories="news", time_range="day", max_results=10)

    def search_last_week(self, query: str) -> BochaResponse:
        logger.info(f"--- TOOL: 搜索本周信息[SearXNG] (query: {query}) ---")
        return self._search(query, categories="news", time_range="week", max_results=10)
