# -*- coding: utf-8 -*-
"""
===================================
ASX-first 自选股智能分析系统 - 搜索服务模块
===================================

职责：
1. 提供统一的新闻搜索接口
2. 默认使用 Tavily, Gemini Grounding, SerpAPI 搜索链路
3. 多 Key 负载均衡和故障转移
4. 搜索结果缓存和格式化
5. 针对澳洲股票 (ASX) 进行了搜索源优先级优化
"""

import json
import logging
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, List, Dict, Any, Optional, Tuple
from itertools import cycle
from zoneinfo import ZoneInfo
import requests
from newspaper import Article, Config

from src.gemini_key_manager import GEMINI_API_TIMEOUT_MS, is_valid_gemini_api_key

logger = logging.getLogger(__name__)


def fetch_url_content(url: str, timeout: int = 5) -> str:
    """
    获取 URL 网页正文内容 (使用 newspaper4k)
    """
    try:
        # 配置 newspaper4k
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = timeout
        config.fetch_images = False  # 不下载图片
        config.memoize_articles = False # 不缓存

        article = Article(url, config=config, language='en')
        article.download()
        article.parse()

        # 获取正文
        text = article.text.strip()

        # 简单的后处理，去除空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        return text[:1500]  # 限制返回长度
    except Exception as e:
        logger.debug(f"Fetch content failed for {url}: {e}")

    return ""


@dataclass
class SearchResult:
    """搜索结果数据类"""
    title: str
    snippet: str  # 摘要
    url: str
    source: str  # 来源网站
    published_date: Optional[str] = None
    published_fields: Dict[str, Any] = field(default_factory=dict)
    
    def to_text(self) -> str:
        """转换为文本格式"""
        date_str = f" ({self.published_date})" if self.published_date else ""
        return f"【{self.source}】{self.title}{date_str}\n{self.snippet}"


@dataclass 
class SearchResponse:
    """搜索响应"""
    query: str
    results: List[SearchResult]
    provider: str  # 使用的搜索引擎
    success: bool = True
    error_message: Optional[str] = None
    search_time: float = 0.0  # 搜索耗时（秒）
    
    def to_context(self, max_results: int = 5) -> str:
        """将搜索结果转换为可用于 AI 分析的上下文"""
        if not self.success or not self.results:
            return f"搜索 '{self.query}' 未找到相关结果。"
        
        lines = [f"【{self.query} 搜索结果】（来源：{self.provider}）"]
        for i, result in enumerate(self.results[:max_results], 1):
            lines.append(f"\n{i}. {result.to_text()}")
        
        return "\n".join(lines)


@dataclass
class _InflightCacheEntry:
    event: threading.Event = field(default_factory=threading.Event)
    response: Optional[SearchResponse] = None
    error: Optional[BaseException] = None


class BaseSearchProvider(ABC):
    """搜索引擎基类"""
    supports_comprehensive_intel_rotation = True
    requires_market_review_fallback_opt_in = False
    
    def __init__(self, api_keys: List[str], name: str):
        self._api_keys = api_keys
        self._name = name
        self._key_cycle = cycle(api_keys) if api_keys else None
        self._key_usage: Dict[str, int] = {key: 0 for key in api_keys}
        self._key_errors: Dict[str, int] = {key: 0 for key in api_keys}
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def is_available(self) -> bool:
        """检查是否有可用的 API Key"""
        return bool(self._api_keys)

    @staticmethod
    def _is_asx_localized_query(query: str) -> bool:
        text = (query or "").lower()
        return ".ax" in text or bool(re.search(r"\basx\b", text))
    
    def _get_next_key(self) -> Optional[str]:
        if not self._key_cycle:
            return None
        
        # 最多尝试所有 key
        for _ in range(len(self._api_keys)):
            key = next(self._key_cycle)
            # 跳过错误次数过多的 key（超过 3 次）
            if self._key_errors.get(key, 0) < 3:
                return key
        
        # 所有 key 都有问题，重置错误计数并返回第一个
        logger.warning(f"[{self._name}] 所有 API Key 都有错误记录，重置错误计数")
        self._key_errors = {key: 0 for key in self._api_keys}
        return self._api_keys[0] if self._api_keys else None
    
    def _record_success(self, key: str) -> None:
        self._key_usage[key] = self._key_usage.get(key, 0) + 1
        if key in self._key_errors and self._key_errors[key] > 0:
            self._key_errors[key] -= 1
    
    def _record_error(self, key: str) -> None:
        self._key_errors[key] = self._key_errors.get(key, 0) + 1
        logger.warning(f"[{self._name}] API Key {key[:8]}... 错误计数: {self._key_errors[key]}")
    
    @abstractmethod
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        pass
    
    def search(self, query: str, max_results: int = 5, days: int = 7) -> SearchResponse:
        api_key = self._get_next_key()
        if not api_key:
            return SearchResponse(
                query=query, results=[], provider=self._name, success=False,
                error_message=f"{self._name} 未配置 API Key"
            )
        
        start_time = time.time()
        try:
            response = self._do_search(query, api_key, max_results, days=days)
            response.search_time = time.time() - start_time
            
            if response.success:
                self._record_success(api_key)
                logger.info(f"[{self._name}] 搜索 '{query}' 成功，返回 {len(response.results)} 条结果")
            else:
                self._record_error(api_key)
            
            return response
            
        except Exception as e:
            self._record_error(api_key)
            elapsed = time.time() - start_time
            logger.error(f"[{self._name}] 搜索 '{query}' 失败: {e}")
            return SearchResponse(
                query=query, results=[], provider=self._name, success=False,
                error_message=str(e), search_time=elapsed
            )


class TavilySearchProvider(BaseSearchProvider):
    """Tavily 搜索引擎 (ASX 优化)"""
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Tavily")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        try:
            from tavily import TavilyClient
        except ImportError:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message="tavily-python 未安装")
        
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                search_depth="advanced",
                max_results=max_results,
                include_answer=False,
                include_raw_content=False,
                days=days,
            )
            
            results = []
            for item in response.get('results', []):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=item.get('content', '')[:500],
                    url=item.get('url', ''),
                    source=self._extract_domain(item.get('url', '')),
                    published_date=item.get('published_date'),
                    published_fields={
                        "published_date": item.get("published_date"),
                        "published_at": item.get("published_at"),
                        "publish_time": item.get("publish_time"),
                        "date": item.get("date"),
                        "time": item.get("time"),
                    },
                ))
            
            return SearchResponse(query=query, results=results, provider=self.name, success=True)
            
        except Exception as e:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=str(e))
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.replace('www.', '') or '未知来源'
        except:
            return '未知来源'


class GeminiGroundingSearchProvider(BaseSearchProvider):
    """Gemini Grounding with Google Search provider."""

    def __init__(
        self,
        api_keys: List[str],
        model: Optional[str] = None,
        max_results: int = 3,
        enabled: bool = True,
    ):
        valid_keys = [key for key in api_keys if is_valid_gemini_api_key(key)]
        super().__init__(valid_keys, "Gemini Grounding")
        self._model = (model or "gemini-3.5-flash").strip() or "gemini-3.5-flash"
        self._grounding_max_results = max(1, int(max_results or 3))
        self._enabled = enabled

    @property
    def is_available(self) -> bool:
        return self._enabled and super().is_available

    def search(self, query: str, max_results: int = 5, days: int = 7) -> SearchResponse:
        if not self.is_available:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="Gemini Grounding 未启用或未配置有效 Gemini API Key",
            )

        start_time = time.time()
        errors: List[str] = []
        attempted_keys = set()

        for _ in range(len(self._api_keys)):
            api_key = self._get_next_key()
            if not api_key or api_key in attempted_keys:
                break
            attempted_keys.add(api_key)

            response = self._do_search(query, api_key, max_results, days=days)
            response.search_time = time.time() - start_time
            if response.success and response.results:
                self._record_success(api_key)
                logger.info(f"[{self.name}] 搜索 '{query}' 成功，返回 {len(response.results)} 条结果")
                return response

            self._record_error(api_key)
            if response.error_message:
                errors.append(response.error_message)

        return SearchResponse(
            query=query,
            results=[],
            provider=self.name,
            success=False,
            error_message="; ".join(errors) or "Gemini Grounding 未返回可用搜索结果",
            search_time=time.time() - start_time,
        )

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message="google-genai 未安装")

        try:
            effective_max_results = min(max(1, max_results), self._grounding_max_results)
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=GEMINI_API_TIMEOUT_MS),
            )
            tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(tools=[tool], temperature=0.2)
            response = client.models.generate_content(
                model=self._model,
                contents=self._build_prompt(query, effective_max_results, days),
                config=config,
            )

            model_items = self._parse_model_results(getattr(response, "text", "") or "")
            grounding_chunks = self._extract_grounding_chunks(response)
            results = self._merge_grounded_results(grounding_chunks, model_items, effective_max_results)

            if not results:
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message="Gemini Grounding 未返回 grounding_chunks 或可用 URL",
                )

            return SearchResponse(query=query, results=results, provider=self.name, success=True)
        except Exception as e:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=str(e))

    @staticmethod
    def _build_prompt(query: str, max_results: int, days: int) -> str:
        return f"""Use Google Search grounding to find current, source-backed web results for this query:
{query}

Return only JSON in this exact shape:
{{
  "results": [
    {{
      "title": "source title",
      "snippet": "concise factual summary",
      "url": "https://source.example/path",
      "source": "source domain or publication",
      "published_date": "YYYY-MM-DD or null"
    }}
  ]
}}

Rules:
- Return at most {max_results} results.
- Prefer sources from the last {days} day(s) when available.
- If published_date cannot be determined, use null.
- Do not include markdown fences or extra commentary.
"""

    @classmethod
    def _parse_model_results(cls, response_text: str) -> List[Dict[str, Optional[str]]]:
        payload = cls._extract_json_payload(response_text)
        if not payload:
            return []

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json

                data = json.loads(repair_json(payload))
            except Exception:
                return []

        if isinstance(data, dict):
            raw_items = data.get("results", [])
        elif isinstance(data, list):
            raw_items = data
        else:
            return []

        items: List[Dict[str, Optional[str]]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or raw.get("uri") or "").strip()
            if not url:
                continue
            published_date = raw.get("published_date")
            items.append(
                {
                    "title": str(raw.get("title") or "").strip() or None,
                    "snippet": str(raw.get("snippet") or raw.get("summary") or "").strip() or None,
                    "url": url,
                    "source": str(raw.get("source") or "").strip() or None,
                    "published_date": str(published_date).strip() if published_date not in (None, "") else None,
                }
            )
        return items

    @staticmethod
    def _extract_json_payload(text: str) -> Optional[str]:
        text = (text or "").strip()
        if not text:
            return None

        starts = [(text.find("{"), "{", "}"), (text.find("["), "[", "]")]
        starts = [item for item in starts if item[0] >= 0]
        if not starts:
            return None
        start, _opener, closer = min(starts, key=lambda item: item[0])
        end = text.rfind(closer)
        if end < start:
            return None
        return text[start : end + 1]

    @classmethod
    def _extract_grounding_chunks(cls, response: Any) -> List[Dict[str, str]]:
        candidates = cls._get_value(response, "candidates") or []
        chunks: List[Dict[str, str]] = []

        for candidate in candidates:
            metadata = cls._get_value(candidate, "grounding_metadata") or cls._get_value(candidate, "groundingMetadata")
            if not metadata:
                continue
            raw_chunks = cls._get_value(metadata, "grounding_chunks") or cls._get_value(metadata, "groundingChunks") or []
            for raw_chunk in raw_chunks:
                web = cls._get_value(raw_chunk, "web") or cls._get_value(raw_chunk, "retrieved_context")
                if not web:
                    continue
                uri = str(cls._get_value(web, "uri") or cls._get_value(web, "url") or "").strip()
                if not uri:
                    continue
                title = str(cls._get_value(web, "title") or cls._get_value(web, "name") or "").strip()
                chunks.append({"url": uri, "title": title})

        return chunks

    @classmethod
    def _merge_grounded_results(
        cls,
        grounding_chunks: List[Dict[str, str]],
        model_items: List[Dict[str, Optional[str]]],
        max_results: int,
    ) -> List[SearchResult]:
        model_by_url = {item["url"]: item for item in model_items if item.get("url")}
        results: List[SearchResult] = []
        seen_urls = set()

        for chunk in grounding_chunks:
            url = chunk.get("url", "")
            if not url or url in seen_urls:
                continue
            model_item = model_by_url.get(url, {})
            title = model_item.get("title") or chunk.get("title") or url
            snippet = model_item.get("snippet") or ""
            source = model_item.get("source") or cls._extract_domain(url)
            published_date = model_item.get("published_date")
            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    url=url,
                    source=source,
                    published_date=published_date,
                    published_fields={"published_date": published_date},
                )
            )
            seen_urls.add(url)
            if len(results) >= max_results:
                return results

        for model_item in model_items:
            url = model_item.get("url") or ""
            if not url or url in seen_urls:
                continue
            published_date = model_item.get("published_date")
            results.append(
                SearchResult(
                    title=model_item.get("title") or url,
                    snippet=model_item.get("snippet") or "",
                    url=url,
                    source=model_item.get("source") or cls._extract_domain(url),
                    published_date=published_date,
                    published_fields={"published_date": published_date},
                )
            )
            seen_urls.add(url)
            if len(results) >= max_results:
                break

        return results

    @staticmethod
    def _get_value(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            from urllib.parse import urlparse

            return urlparse(url).netloc.replace("www.", "") or "未知来源"
        except Exception:
            return "未知来源"


class SerpAPISearchProvider(BaseSearchProvider):
    """SerpAPI 搜索引擎"""
    supports_comprehensive_intel_rotation = False
    requires_market_review_fallback_opt_in = True
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "SerpAPI")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        try:
            from serpapi import GoogleSearch
        except ImportError:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message="google-search-results 未安装")
        
        try:
            tbs = "qdr:w"
            if days <= 1: tbs = "qdr:d"
            elif days <= 30: tbs = "qdr:m"
            is_asx = self._is_asx_localized_query(query)
            
            params = {
                "engine": "google", "q": query, "api_key": api_key,
                "google_domain": "google.com.au" if is_asx else "google.com",
                "hl": "en",
                "gl": "au" if is_asx else "us",
                "tbs": tbs, "num": max_results
            }
            
            search = GoogleSearch(params)
            response = search.get_dict()
            results = []
            
            # 解析自然搜索结果
            for item in response.get('organic_results', [])[:max_results]:
                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=item.get('snippet', '')[:1000],
                    url=item.get('link', ''),
                    source=item.get('source', 'Google'),
                    published_date=item.get('date'),
                    published_fields={
                        "published_date": item.get("published_date"),
                        "published_at": item.get("published_at"),
                        "publish_time": item.get("publish_time"),
                        "date": item.get("date"),
                        "time": item.get("time"),
                    },
                ))
            
            return SearchResponse(query=query, results=results, provider=self.name, success=True)
            
        except Exception as e:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=str(e))


class BochaSearchProvider(BaseSearchProvider):
    """博查搜索引擎"""
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Bocha")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        try:
            url = "https://api.bocha.cn/v1/web-search"
            headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
            freshness = "oneWeek"
            if days <= 1: freshness = "oneDay"
            elif days > 30: freshness = "oneYear"

            payload = {
                "query": query, "freshness": freshness,
                "summary": True, "count": min(max_results, 50)
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code != 200:
                return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=f"HTTP {response.status_code}: {response.text}")
            
            data = response.json()
            if data.get('code') != 200:
                return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=data.get('msg'))
                
            results = []
            for item in data.get('data', {}).get('webPages', {}).get('value', [])[:max_results]:
                results.append(SearchResult(
                    title=item.get('name', ''),
                    snippet=(item.get('summary') or item.get('snippet', ''))[:500],
                    url=item.get('url', ''),
                    source=item.get('siteName', ''),
                    published_date=item.get('datePublished'),
                    published_fields={
                        "published_date": item.get("datePublished"),
                        "published_at": item.get("published_at"),
                        "publish_time": item.get("publish_time"),
                        "date": item.get("date"),
                        "time": item.get("time"),
                    },
                ))
                
            return SearchResponse(query=query, results=results, provider=self.name, success=True)
            
        except Exception as e:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=str(e))


class BraveSearchProvider(BaseSearchProvider):
    """Brave Search 搜索引擎"""

    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Brave")

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        try:
            headers = {'X-Subscription-Token': api_key, 'Accept': 'application/json'}
            freshness = "pw" # 默认一周
            if days <= 1: freshness = "pd"
            elif days > 30: freshness = "py"
            is_asx = self._is_asx_localized_query(query)
            
            params = {
                "q": query, "count": min(max_results, 20),
                "freshness": freshness,
                "search_lang": "en",
                "country": "AU" if is_asx else "US"
            }
            
            response = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=10)
            if response.status_code != 200:
                return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=f"HTTP {response.status_code}")

            data = response.json()
            results = []
            for item in data.get('web', {}).get('results', [])[:max_results]:
                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=item.get('description', '')[:500],
                    url=item.get('url', ''),
                    source="Brave",
                    published_date=item.get('age'),
                    published_fields={
                        "published_date": item.get("published_date"),
                        "published_at": item.get("published_at"),
                        "publish_time": item.get("publish_time"),
                        "date": item.get("date"),
                        "time": item.get("time"),
                    },
                ))
            
            return SearchResponse(query=query, results=results, provider=self.name, success=True)
            
        except Exception as e:
            return SearchResponse(query=query, results=[], provider=self.name, success=False, error_message=str(e))


class SearchService:
    """
    搜索服务 (澳洲优化版)
    """
    
    # 增强搜索关键词模板（ASX/AU/US 英文）
    ENHANCED_SEARCH_KEYWORDS_EN = [
        "{name} stock price today",
        "{name} {code} latest quote trend",
        "{name} stock analysis chart",
        "{name} technical analysis",
        "{name} {code} performance volume",
    ]
    
    # 增强搜索关键词模板（通用英文兜底）
    ENHANCED_SEARCH_KEYWORDS = [
        "{name} stock price today",
        "{name} {code} latest quote trend",
        "{name} stock analysis chart",
        "{name} technical analysis",
        "{name} {code} performance volume",
    ]
    _PUBLISHED_TIME_FIELDS = (
        "published_date",
        "published_at",
        "publish_time",
        "date",
        "time",
    )
    NEWS_INTEL_CACHE_PROVIDER = "news_intel_cache"
    
    def __init__(
        self,
        bocha_keys: Optional[List[str]] = None,
        tavily_keys: Optional[List[str]] = None,
        brave_keys: Optional[List[str]] = None,
        serpapi_keys: Optional[List[str]] = None,
        gemini_keys: Optional[List[str]] = None,
        gemini_grounding_enabled: bool = True,
        gemini_grounding_model: Optional[str] = None,
        gemini_grounding_max_results: int = 3,
        news_max_age_days: int = 3,
        market_timezone: Optional[str] = None,
        serpapi_market_review_fallback_enabled: bool = False,
        
    ):
        """初始化搜索服务（已针对澳洲股票优化：Tavily advanced 优先）"""
        self._providers: List[BaseSearchProvider] = []
        
        self.news_max_age_days = max(1, news_max_age_days)  # <--- 插入这句
        self.market_timezone = self._resolve_market_timezone(market_timezone)
        self.serpapi_market_review_fallback_enabled = bool(serpapi_market_review_fallback_enabled)

        # 1. Tavily 优先（针对 ASX 澳洲股票搜索能力强）
        if tavily_keys:
            self._providers.append(TavilySearchProvider(tavily_keys))
            logger.info(f"已配置 Tavily 搜索，共 {len(tavily_keys)} 个 API Key")

        # 2. Gemini Grounding with Google Search（Tavily 后第一 fallback，可复用 Gemini keys）
        if gemini_grounding_enabled and gemini_keys:
            self._providers.append(
                GeminiGroundingSearchProvider(
                    gemini_keys,
                    model=gemini_grounding_model,
                    max_results=gemini_grounding_max_results,
                    enabled=gemini_grounding_enabled,
                )
            )
            logger.info(f"已配置 Gemini Grounding 搜索，共 {len(gemini_keys)} 个 Gemini API Key")

        # 3. SerpAPI（低频 Google fallback）
        if serpapi_keys:
            self._providers.append(SerpAPISearchProvider(serpapi_keys))
            logger.info(f"已配置 SerpAPI 搜索，共 {len(serpapi_keys)} 个 API Key")

        if brave_keys or bocha_keys:
            logger.info("已忽略 Brave/Bocha 搜索配置，日常搜索链路仅使用 Tavily/Gemini Grounding/SerpAPI")

        if not self._providers:
            logger.warning("未配置任何搜索引擎 API Key，新闻搜索功能将不可用")

        self._cache: Dict[str, Tuple[float, 'SearchResponse']] = {}
        self._cache_ttl: int = 600
        self._cache_lock = threading.RLock()
        self._cache_inflight: Dict[str, _InflightCacheEntry] = {}

    @staticmethod
    def _resolve_market_timezone(market_timezone: Optional[str]) -> str:
        if market_timezone and market_timezone.strip():
            return market_timezone.strip()
        try:
            from src.config import get_config

            configured = getattr(get_config(), "market_timezone", "Australia/Sydney")
            return str(configured or "Australia/Sydney").strip() or "Australia/Sydney"
        except Exception as exc:
            logger.debug("读取市场时区配置失败，使用 Australia/Sydney: %s", exc)
            return "Australia/Sydney"

    def _now_in_market_timezone(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.market_timezone))
        except Exception as exc:
            logger.warning("无效市场时区 %s，已回退到 Australia/Sydney: %s", self.market_timezone, exc)
            return datetime.now(ZoneInfo("Australia/Sydney"))

    @property
    def is_available(self) -> bool:
        """检查是否有可用的搜索引擎"""
        return any(p.is_available for p in self._providers)

    @staticmethod
    def _is_foreign_stock(stock_code: str) -> bool:
        """判断是否为 ASX/AU/US 或港股"""
        import re
        code = stock_code.strip()
        # ASX/美股：1-5个大写字母，可能包含点（如 BRK.B, CBA.AX）
        if re.match(r'^[A-Za-z]{1,5}(\.[A-Za-z]+)?$', code):
            return True
        # 港股
        if code.lower().startswith('hk') or (code.isdigit() and len(code) == 5):
            return True
        return False

    @staticmethod
    def _is_market_review_stock_news(stock_code: str) -> bool:
        return (stock_code or "").strip().lower() == "market"

    def _should_use_provider_for_stock_news(
        self,
        provider: BaseSearchProvider,
        *,
        stock_code: str,
    ) -> bool:
        if not self._is_market_review_stock_news(stock_code):
            return True
        if not getattr(provider, "requires_market_review_fallback_opt_in", False):
            return True
        return self.serpapi_market_review_fallback_enabled

    def _cache_key(self, query: str, max_results: int, days: int) -> str:
        return f"{query}|{max_results}|{days}"

    def _get_cached_unlocked(self, key: str) -> Optional['SearchResponse']:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, response = entry
        if time.time() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return response

    def _get_cached(self, key: str) -> Optional['SearchResponse']:
        with self._cache_lock:
            return self._get_cached_unlocked(key)

    def _put_cache(self, key: str, response: 'SearchResponse') -> None:
        with self._cache_lock:
            self._cache[key] = (time.time(), response)

    def _get_or_fill_cache(
        self,
        key: str,
        producer: Callable[[], 'SearchResponse']
    ) -> 'SearchResponse':
        """Return cached result or coalesce concurrent fills for the same key."""
        with self._cache_lock:
            cached = self._get_cached_unlocked(key)
            if cached is not None:
                return cached

            inflight = self._cache_inflight.get(key)
            if inflight is None:
                inflight = _InflightCacheEntry()
                self._cache_inflight[key] = inflight
                owner = True
            else:
                owner = False

        if not owner:
            inflight.event.wait()
            if inflight.error is not None:
                raise inflight.error
            if inflight.response is not None:
                return inflight.response
            cached = self._get_cached(key)
            if cached is not None:
                return cached
            return SearchResponse(
                query=key,
                results=[],
                provider="None",
                success=False,
                error_message="Inflight search completed without a response"
            )

        response: Optional[SearchResponse] = None
        error: Optional[BaseException] = None
        try:
            response = producer()
            if response.success and response.results:
                self._put_cache(key, response)
            return response
        except BaseException as exc:
            error = exc
            raise
        finally:
            with self._cache_lock:
                inflight.response = response
                inflight.error = error
                self._cache_inflight.pop(key, None)
                inflight.event.set()

    @staticmethod
    def _parse_entity_hints(stock_code: str, stock_name: str) -> Dict[str, Any]:
        """提取股票实体消歧所需的关键字段。"""
        code = (stock_code or "").strip().upper()
        name = (stock_name or "").strip()
        base_ticker = code.split(".")[0]
        exchange_suffix = code.split(".")[-1] if "." in code else ""
        is_asx = exchange_suffix == "AX"

        market_terms = []
        if is_asx:
            market_terms = ["ASX", "Australia", "Australian Securities Exchange", ".AX"]

        return {
            "code": code,
            "name": name,
            "base_ticker": base_ticker,
            "exchange_suffix": exchange_suffix,
            "is_asx": is_asx,
            "market_terms": market_terms
        }

    def _build_grounded_query(self, stock_code: str, stock_name: str, intent_terms: List[str]) -> str:
        """构建包含 ticker/exchange/company/market 约束的搜索 query。"""
        hints = self._parse_entity_hints(stock_code, stock_name)
        parts = [hints["name"], hints["code"], hints["base_ticker"]]
        if hints["is_asx"]:
            parts.extend(["ASX", "Australia", "English-first"])
        parts.extend(intent_terms)
        return " ".join([p for p in parts if p])

    @staticmethod
    def _contains_exchange_conflict(text: str) -> bool:
        conflict_terms = ["nasdaq", "nyse", "hkex", "lse", "tsx", "sgx"]
        return any(term in text for term in conflict_terms)

    def _score_result_entity_match(self, result: SearchResult, stock_code: str, stock_name: str) -> Tuple[int, List[str]]:
        """对搜索结果进行实体一致性打分。"""
        hints = self._parse_entity_hints(stock_code, stock_name)
        haystack = " ".join([
            result.title or "",
            result.snippet or "",
            result.url or "",
            result.source or "",
        ]).lower()

        score = 0
        reasons: List[str] = []
        code_lower = hints["code"].lower()
        base_lower = hints["base_ticker"].lower()
        name_lower = hints["name"].lower()

        if code_lower and code_lower in haystack:
            score += 3
            reasons.append("ticker_exact")
        elif base_lower and len(base_lower) >= 3 and re.search(rf"\b{re.escape(base_lower)}\b", haystack):
            score += 2
            reasons.append("ticker_base")

        if name_lower and name_lower in haystack:
            score += 2
            reasons.append("company_name")

        if hints["is_asx"]:
            has_market_hit = any(term.lower() in haystack for term in hints["market_terms"])
            if has_market_hit:
                score += 2
                reasons.append("asx_market")
            if self._contains_exchange_conflict(haystack) and not has_market_hit:
                score -= 2
                reasons.append("conflict_market")

        return score, reasons

    def _is_low_risk_name_only_fallback(
        self,
        score: int,
        reasons: List[str],
        dimension: Optional[str],
        stock_code: str,
    ) -> bool:
        """
        受控兜底：latest_news 维度允许“仅公司名强命中”的低风险结果保留，
        但仍禁止出现明确市场冲突信号的结果。
        """
        hints = self._parse_entity_hints(stock_code=stock_code, stock_name="")
        if not hints["is_asx"]:
            return False
        if dimension != "latest_news":
            return False
        if score != 2:
            return False
        if "company_name" not in reasons:
            return False
        if "conflict_market" in reasons:
            return False
        return True

    def _filter_entity_consistent_results(
        self,
        response: SearchResponse,
        stock_code: str,
        stock_name: str,
        dimension: Optional[str] = None
    ) -> SearchResponse:
        """
        过滤可能串台的结果：低分结果留在 debug，不进入主分析上下文。
        """
        if not response.results:
            return response

        scored: List[Tuple[int, SearchResult, List[str]]] = []
        for result in response.results:
            score, reasons = self._score_result_entity_match(result, stock_code, stock_name)
            scored.append((score, result, reasons))

        threshold = 3
        kept: List[SearchResult] = []
        dropped: List[Tuple[int, SearchResult, List[str]]] = []
        for score, result, reasons in scored:
            if score >= threshold or self._is_low_risk_name_only_fallback(score, reasons, dimension, stock_code):
                kept.append(result)
            else:
                dropped.append((score, result, reasons))

        if dropped:
            logger.debug(
                "实体消歧过滤: %s(%s) 丢弃 %d 条低分结果: %s",
                stock_name,
                stock_code,
                len(dropped),
                [{"title": r.title[:80], "score": s, "reasons": rs} for s, r, rs in dropped]
            )

        if not kept:
            return SearchResponse(
                query=response.query,
                results=[],
                provider=response.provider,
                success=response.success,
                error_message=response.error_message,
                search_time=response.search_time
            )

        return SearchResponse(
            query=response.query,
            results=kept,
            provider=response.provider,
            success=response.success,
            error_message=response.error_message,
            search_time=response.search_time
        )

    def _parse_published_datetime(
        self,
        result: SearchResult,
        now_utc: Optional[datetime] = None
    ) -> Tuple[Optional[datetime], Optional[str], Optional[str]]:
        """解析新闻发布时间，返回 (datetime_utc, field_name, reason)。"""
        raw_candidates: List[Tuple[str, Any]] = []
        if result.published_date:
            raw_candidates.append(("published_date", result.published_date))

        for field_name in self._PUBLISHED_TIME_FIELDS:
            raw_value = (result.published_fields or {}).get(field_name)
            if raw_value is not None:
                raw_candidates.append((field_name, raw_value))

        if not raw_candidates:
            return None, None, "missing"

        ref_now = now_utc or datetime.now(timezone.utc)
        for field_name, raw_value in raw_candidates:
            dt = self._parse_datetime_value(raw_value, now_utc=ref_now)
            if dt is not None:
                return dt, field_name, None

        return None, raw_candidates[0][0], "invalid"

    @staticmethod
    def _parse_datetime_value(raw_value: Any, now_utc: Optional[datetime] = None) -> Optional[datetime]:
        """尽量兼容常见时间格式并统一为 UTC。"""
        if raw_value is None:
            return None

        if isinstance(raw_value, datetime):
            dt = raw_value
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        text = str(raw_value).strip()
        if not text:
            return None

        ref_now = now_utc or datetime.now(timezone.utc)
        if ref_now.tzinfo is None:
            ref_now = ref_now.replace(tzinfo=timezone.utc)
        else:
            ref_now = ref_now.astimezone(timezone.utc)

        relative_match = re.match(r"^\s*(\d+)\s+(minute|minutes|hour|hours|day|days)\s+ago\s*$", text, re.IGNORECASE)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2).lower()
            if unit.startswith("minute"):
                return ref_now - timedelta(minutes=amount)
            if unit.startswith("hour"):
                return ref_now - timedelta(hours=amount)
            if unit.startswith("day"):
                return ref_now - timedelta(days=amount)

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        iso_candidate = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_candidate)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        try:
            dt = parsedate_to_datetime(text)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _is_news_fresh_enough(self, published_at_utc: datetime, now_utc: datetime) -> Tuple[bool, str]:
        max_age = timedelta(days=self.news_max_age_days)
        future_tolerance = timedelta(days=1)

        if published_at_utc > now_utc + future_tolerance:
            return False, "future_over_tolerance"
        if published_at_utc < now_utc - max_age:
            return False, "too_old"
        return True, "ok"

    def _filter_by_news_age(self, response: SearchResponse, now: Optional[datetime] = None) -> SearchResponse:
        """统一时效硬过滤：缺失/非法/超龄/未来超容差的新闻全部丢弃。"""
        if not response.results:
            return response

        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        kept: List[SearchResult] = []
        dropped_count = 0
        for result in response.results:
            published_at, field_name, parse_reason = self._parse_published_datetime(result, now_utc=now_utc)
            if published_at is None:
                dropped_count += 1
                logger.info(
                    "新闻时效过滤丢弃: title=%s reason=%s field=%s raw=%s",
                    (result.title or "")[:80],
                    parse_reason,
                    field_name,
                    (result.published_fields or {}).get(field_name) if field_name else result.published_date,
                )
                continue

            fresh_enough, stale_reason = self._is_news_fresh_enough(published_at, now_utc)
            if not fresh_enough:
                dropped_count += 1
                logger.info(
                    "新闻时效过滤丢弃: title=%s reason=%s published=%s now=%s max_age_days=%d",
                    (result.title or "")[:80],
                    stale_reason,
                    published_at.isoformat(),
                    now_utc.isoformat(),
                    self.news_max_age_days,
                )
                continue

            kept.append(result)

        if dropped_count:
            logger.debug(
                "新闻时效过滤完成: query=%s provider=%s kept=%d dropped=%d",
                response.query,
                response.provider,
                len(kept),
                dropped_count,
            )

        return SearchResponse(
            query=response.query,
            results=kept,
            provider=response.provider,
            success=response.success,
            error_message=response.error_message,
            search_time=response.search_time,
        )
    
    def search_stock_news(self, stock_code: str, stock_name: str, max_results: int = 5, focus_keywords: Optional[List[str]] = None) -> SearchResponse:
        today_weekday = self._now_in_market_timezone().weekday()
    
        # 1. 先计算常规情况下的建议天数
        weekday_days = 3 if today_weekday == 0 else (2 if today_weekday >= 5 else 1)

        # 2. 取建议天数和你 .env 配置天数的最小值
        search_days = min(weekday_days, self.news_max_age_days)

        is_foreign = self._is_foreign_stock(stock_code)
        if focus_keywords:
            query = " ".join(focus_keywords)
        elif is_foreign:
            query = self._build_grounded_query(stock_code, stock_name, ["stock", "latest news"])
        else:
            query = f"{stock_name} {stock_code} 股票 最新消息"

        logger.info(f"搜索股票新闻: {stock_name}({stock_code}), query='{query}'")
        
        cache_key = self._cache_key(query, max_results, search_days)

        def fill() -> SearchResponse:
            for provider in self._providers:
                if not provider.is_available:
                    continue
                if not self._should_use_provider_for_stock_news(
                    provider,
                    stock_code=stock_code,
                ):
                    logger.info(
                        "大盘复盘默认跳过低频 fallback provider: provider=%s stock_code=%s",
                        provider.name,
                        stock_code,
                    )
                    continue
                response = provider.search(query, max_results, days=search_days)
                if response.success and response.results:
                    fresh_response = self._filter_by_news_age(response)
                    if not fresh_response.results:
                        logger.debug(
                            "搜索结果在时效过滤后为空，继续尝试下一个 provider: %s(%s) provider=%s",
                            stock_name,
                            stock_code,
                            provider.name
                        )
                        continue
                    filtered_response = self._filter_entity_consistent_results(
                        fresh_response,
                        stock_code=stock_code,
                        stock_name=stock_name,
                        dimension="latest_news"
                    )
                    if filtered_response.results:
                        return filtered_response
                    logger.debug(
                        "搜索结果在实体消歧后为空，继续尝试下一个 provider: %s(%s) provider=%s",
                        stock_name,
                        stock_code,
                        provider.name
                    )

            return SearchResponse(query=query, results=[], provider="None", success=False, error_message="All providers failed")

        return self._get_or_fill_cache(cache_key, fill)

    def search_stock_events(self, stock_code: str, stock_name: str, event_types: Optional[List[str]] = None) -> SearchResponse:
        if event_types is None:
            if self._is_foreign_stock(stock_code):
                event_types = ["earnings report", "insider selling", "quarterly results"]
            else:
                event_types = ["年报预告", "减持公告", "业绩快报"]
        
        query = f"{stock_name} ({' OR '.join(event_types)})"
        for provider in self._providers:
            if not provider.is_available: continue
            response = provider.search(query, max_results=5)
            if response.success: return response
            
        return SearchResponse(query=query, results=[], provider="None", success=False, error_message="Events search failed")

    def build_comprehensive_intel_dimensions(self, stock_code: str, stock_name: str) -> List[Dict[str, Any]]:
        is_foreign = self._is_foreign_stock(stock_code)

        if is_foreign:
            # 针对外盘（澳股/美股），直接使用 stock_code 搜索，避开中文名干扰
            return [
                {'name': 'latest_news', 'query': self._build_grounded_query(stock_code, stock_name, ["latest news events"]), 'desc': '最新消息', 'strict_freshness': True},
                {'name': 'market_analysis', 'query': self._build_grounded_query(stock_code, stock_name, ["analyst rating target price report"]), 'desc': '机构分析', 'strict_freshness': False},
                {'name': 'risk_check', 'query': self._build_grounded_query(stock_code, stock_name, ["risk insider selling lawsuit litigation"]), 'desc': '风险排查', 'strict_freshness': True},
                {'name': 'earnings', 'query': self._build_grounded_query(stock_code, stock_name, ["earnings revenue profit growth forecast"]), 'desc': '业绩预期', 'strict_freshness': False},
                {'name': 'industry', 'query': self._build_grounded_query(stock_code, stock_name, ["industry competitors market share outlook"]), 'desc': '行业分析', 'strict_freshness': False},
            ]

        return [
            {'name': 'latest_news', 'query': f"{stock_name} 最新新闻", 'desc': '最新消息', 'strict_freshness': True},
            {'name': 'market_analysis', 'query': f"{stock_name} 研报 评级", 'desc': '机构分析', 'strict_freshness': False},
            {'name': 'risk_check', 'query': f"{stock_name} 利空 风险", 'desc': '风险排查', 'strict_freshness': True},
            {'name': 'earnings', 'query': f"{stock_name} 业绩预告", 'desc': '业绩预期', 'strict_freshness': False},
            {'name': 'industry', 'query': f"{stock_name} 行业分析", 'desc': '行业分析', 'strict_freshness': False},
        ]

    @staticmethod
    def _format_news_intel_datetime(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    def build_news_intel_cache_response(
        self,
        *,
        stock_code: str,
        stock_name: str,
        dimension: str,
        query: str,
        records: List[Any],
        min_results: int,
    ) -> Optional[SearchResponse]:
        """Build a SearchResponse from persisted news_intel rows when still entity-consistent."""
        cache_results: List[SearchResult] = []
        for record in records:
            title = str(getattr(record, "title", "") or "").strip()
            url = str(getattr(record, "url", "") or "").strip()
            if not title and not url:
                continue
            source = str(getattr(record, "source", "") or "").strip()
            published_date = self._format_news_intel_datetime(getattr(record, "published_date", None))
            fetched_at = self._format_news_intel_datetime(getattr(record, "fetched_at", None))
            provider = str(getattr(record, "provider", "") or "").strip()
            cache_results.append(
                SearchResult(
                    title=title,
                    snippet=str(getattr(record, "snippet", "") or "").strip(),
                    url=url,
                    source=source,
                    published_date=published_date,
                    published_fields={
                        "news_intel_provider": provider,
                        "news_intel_fetched_at": fetched_at,
                    },
                )
            )

        response = SearchResponse(
            query=query,
            results=cache_results,
            provider=self.NEWS_INTEL_CACHE_PROVIDER,
            success=bool(cache_results),
        )
        filtered = self._filter_entity_consistent_results(
            response,
            stock_code=stock_code,
            stock_name=stock_name,
            dimension=dimension,
        )
        required_count = max(1, int(min_results or 1))
        if len(filtered.results) < required_count:
            return None
        return filtered

    @staticmethod
    def _select_comprehensive_intel_providers(providers: List[BaseSearchProvider]) -> List[BaseSearchProvider]:
        """Keep scarce SerpAPI quota out of routine multi-dimension rotation."""
        available_providers = [p for p in providers if p.is_available]
        primary_providers = [p for p in available_providers if p.supports_comprehensive_intel_rotation]
        return primary_providers or available_providers

    def search_comprehensive_intel(
        self,
        stock_code: str,
        stock_name: str,
        max_searches: int = 5,
        cached_intel: Optional[Dict[str, SearchResponse]] = None,
        dimensions: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, SearchResponse]:
        results = {}
        dims = list(dimensions) if dimensions is not None else self.build_comprehensive_intel_dimensions(stock_code, stock_name)
        try:
            search_limit = max(0, int(max_searches))
        except (TypeError, ValueError):
            search_limit = len(dims)

        available_providers = self._select_comprehensive_intel_providers(self._providers)
        provider_index = 0

        for dim in dims[:search_limit]:
            cached_response = (cached_intel or {}).get(dim['name'])
            if cached_response and cached_response.success and cached_response.results:
                results[dim['name']] = cached_response
                continue

            if not available_providers:
                results[dim['name']] = SearchResponse(
                    query=dim['query'],
                    results=[],
                    provider="None",
                    success=False,
                    error_message="No available providers"
                )
                continue

            provider = available_providers[provider_index % len(available_providers)]
            provider_index += 1
            logger.info("[情报搜索] %s: 使用 %s", dim.get("desc", dim["name"]), provider.name)

            resp = provider.search(dim['query'], max_results=3)
            filtered_resp = resp
            if resp.success and resp.results:
                if dim.get("strict_freshness", True):
                    filtered_resp = self._filter_by_news_age(resp)
                if filtered_resp.results:
                    filtered_resp = self._filter_entity_consistent_results(
                        filtered_resp,
                        stock_code=stock_code,
                        stock_name=stock_name,
                        dimension=dim['name']
                    )

            if filtered_resp.success and filtered_resp.results:
                results[dim['name']] = filtered_resp
            else:
                logger.debug(
                    "维度 %s 使用 provider 后无可用结果，不再同维度继续兜底: %s(%s) provider=%s",
                    dim['name'],
                    stock_name,
                    stock_code,
                    provider.name,
                )
                results[dim['name']] = SearchResponse(
                    query=dim['query'],
                    results=[],
                    provider="None",
                    success=False,
                    error_message="No entity-consistent results"
                )

        return results

    def format_intel_report(self, intel_results: Dict[str, SearchResponse], stock_name: str) -> str:
        lines = [f"【{stock_name} 情报搜索结果】"]
        order = ['latest_news', 'market_analysis', 'risk_check', 'earnings', 'industry']
        
        for dim_name in order:
            if dim_name not in intel_results: continue
            resp = intel_results[dim_name]
            dim_desc = {'latest_news': '📰 最新消息', 'market_analysis': '📈 机构分析', 'risk_check': '⚠️ 风险排查', 'earnings': '📊 业绩预期', 'industry': '🏭 行业分析'}.get(dim_name, dim_name)
            
            lines.append(f"\n{dim_desc} (来源: {resp.provider}):")
            if resp.success and resp.results:
                for i, r in enumerate(resp.results[:3], 1):
                    meta_parts = []
                    if r.source:
                        meta_parts.append(f"来源: {r.source}")
                    if r.published_date:
                        meta_parts.append(f"日期: {r.published_date}")
                    if r.url:
                        meta_parts.append(f"URL: {r.url}")
                    meta = f" ({'; '.join(meta_parts)})" if meta_parts else ""
                    lines.append(f"  {i}. {r.title}{meta}")
            else:
                lines.append("  未找到相关信息")
        
        return "\n".join(lines)
    
    def batch_search(
        self,
        stocks: List[Dict[str, str]],
        max_results_per_stock: int = 3,
        delay_between: float = 1.0
    ) -> Dict[str, SearchResponse]:
        """
        Batch search news for multiple stocks.
        """
        results = {}
        
        for i, stock in enumerate(stocks):
            if i > 0:
                time.sleep(delay_between)
            
            code = stock.get('code', '')
            name = stock.get('name', '')
            
            response = self.search_stock_news(code, name, max_results_per_stock)
            results[code] = response
        
        return results

    def search_stock_price_fallback(
        self,
        stock_code: str,
        stock_name: str,
        max_attempts: int = 3,
        max_results: int = 5
    ) -> SearchResponse:
        """
        Enhance search when data sources fail.
        """

        if not self.is_available:
            return SearchResponse(
                query=f"{stock_name} 股价走势",
                results=[],
                provider="None",
                success=False,
                error_message="未配置搜索引擎 API Key"
            )
        
        logger.info(f"[增强搜索] 数据源失败，启动增强搜索: {stock_name}({stock_code})")
        
        all_results = []
        seen_urls = set()
        successful_providers = []
        
        # 使用多个关键词模板搜索
        is_foreign = self._is_foreign_stock(stock_code)
        keywords = self.ENHANCED_SEARCH_KEYWORDS_EN if is_foreign else self.ENHANCED_SEARCH_KEYWORDS
        for i, keyword_template in enumerate(keywords[:max_attempts]):
            query = keyword_template.format(name=stock_name, code=stock_code)
            
            logger.info(f"[增强搜索] 第 {i+1}/{max_attempts} 次搜索: {query}")
            
            # 依次尝试各个搜索引擎
            for provider in self._providers:
                if not provider.is_available:
                    continue
                
                try:
                    response = provider.search(query, max_results=3)
                    
                    if response.success and response.results:
                        # 去重并添加结果
                        for result in response.results:
                            if result.url not in seen_urls:
                                seen_urls.add(result.url)
                                all_results.append(result)
                                
                        if provider.name not in successful_providers:
                            successful_providers.append(provider.name)
                        
                        logger.info(f"[增强搜索] {provider.name} 返回 {len(response.results)} 条结果")
                        break  # 成功后跳到下一个关键词
                    else:
                        logger.debug(f"[增强搜索] {provider.name} 无结果或失败")
                        
                except Exception as e:
                    logger.warning(f"[增强搜索] {provider.name} 搜索异常: {e}")
                    continue
            
            # 短暂延迟避免请求过快
            if i < max_attempts - 1:
                time.sleep(0.5)
        
        # 汇总结果
        if all_results:
            # 截取前 max_results 条
            final_results = all_results[:max_results]
            provider_str = ", ".join(successful_providers) if successful_providers else "None"
            
            logger.info(f"[增强搜索] 完成，共获取 {len(final_results)} 条结果（来源: {provider_str}）")
            
            return SearchResponse(
                query=f"{stock_name}({stock_code}) 股价走势",
                results=final_results,
                provider=provider_str,
                success=True,
            )
        else:
            logger.warning(f"[增强搜索] 所有搜索均未返回结果")
            return SearchResponse(
                query=f"{stock_name}({stock_code}) 股价走势",
                results=[],
                provider="None",
                success=False,
                error_message="增强搜索未找到相关信息"
            )

    def search_stock_with_enhanced_fallback(
        self,
        stock_code: str,
        stock_name: str,
        include_news: bool = True,
        include_price: bool = False,
        max_results: int = 5
    ) -> Dict[str, SearchResponse]:
        """
        综合搜索接口（支持新闻和股价信息）
        """
        results = {}
        
        if include_news:
            results['news'] = self.search_stock_news(
                stock_code, 
                stock_name, 
                max_results=max_results
            )
        
        if include_price:
            results['price'] = self.search_stock_price_fallback(
                stock_code,
                stock_name,
                max_attempts=3,
                max_results=max_results
            )
        
        return results

    def format_price_search_context(self, response: SearchResponse) -> str:
        """
        将股价搜索结果格式化为 AI 分析上下文
        """
        if not response.success or not response.results:
            return "【股价走势搜索】未找到相关信息，请以其他渠道数据为准。"
        
        lines = [
            f"【股价走势搜索结果】（来源: {response.provider}）",
            "⚠️ 注意：以下信息来自网络搜索，仅供参考，可能存在延迟或不准确。",
            ""
        ]
        
        for i, result in enumerate(response.results, 1):
            date_str = f" [{result.published_date}]" if result.published_date else ""
            lines.append(f"{i}. 【{result.source}】{result.title}{date_str}")
            lines.append(f"   {result.snippet[:200]}...")
            lines.append("")
        
        return "\n".join(lines)


# === 便捷函数 ===
_search_service: Optional[SearchService] = None

def get_search_service() -> SearchService:
    """获取搜索服务单例"""
    global _search_service
    
    if _search_service is None:
        from src.config import get_config
        config = get_config()
        
        _search_service = SearchService(
            tavily_keys=config.tavily_api_keys,
            serpapi_keys=config.serpapi_keys,
            gemini_keys=config.gemini_api_keys,
            gemini_grounding_enabled=config.gemini_grounding_search_enabled,
            gemini_grounding_model=config.gemini_grounding_model,
            gemini_grounding_max_results=config.gemini_grounding_max_results,
            news_max_age_days=config.news_max_age_days,
            market_timezone=config.market_timezone,
            serpapi_market_review_fallback_enabled=config.serpapi_market_review_fallback_enabled,
        )
    
    return _search_service

def reset_search_service() -> None:
    """重置搜索服务（用于测试）"""
    global _search_service
    _search_service = None

if __name__ == "__main__":
    # 测试搜索服务
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    )
    
    # 手动测试（需要配置 API Key）
    service = get_search_service()
    
    if service.is_available:
        print("=== 测试股票新闻搜索 ===")
        # 测试澳股代码
        response = service.search_stock_news("CBA.AX", "CommBank")
        print(f"搜索状态: {'成功' if response.success else '失败'}")
        print(f"搜索引擎: {response.provider}")
        print(f"结果数量: {len(response.results)}")
        print(f"耗时: {response.search_time:.2f}s")
        print("\n" + response.to_context())
    else:
        print("未配置搜索引擎 API Key，跳过测试")
