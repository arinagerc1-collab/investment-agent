"""News access layer with simple investment-oriented relevance heuristics."""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_NEWS_PROVIDER = "google_news_rss"
DEFAULT_NEWS_MAX_ITEMS = 5
DEFAULT_GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

RELEVANCE_LABELS_RU = {
    "investment_significant": "инвестиционно значимая",
    "neutral": "нейтральная",
    "weak": "слабо релевантная",
}

ISSUER_MATCH_LABELS_RU = {
    "emitter": "по эмитенту",
    "group": "по группе",
    "other": "другая компания",
}

# Масштабируемые профили эмитентов.
# main: прямые сущности самого эмитента;
# exclude: более точные похожие сущности, которые не должны считаться прямым совпадением;
# group: связанные компании/структуры группы;
# group_roots: корни бренда для fallback-эвристики вида "эмитент + дочерняя структура".
EMITTER_PROFILES = {
    "GAZP": {
        "main": (
            "gazp",
            "газпром",
            "пао газпром",
            "газпрома",
            "акции газпрома",
            "акции газпром",
            "gazprom",
        ),
        "exclude": (
            "газпром нефть",
            "газпром нефти",
            "газпромнефть",
            "газпром-нефть",
            "газпромбанк",
            "газпром банк",
            "газпром межрегионгаз",
            "газпром-межрегионгаз",
            "газпром арена",
            "газпром-арена",
            "газпром инвест",
            "газпром-инвест",
            "газпром инвестхолдинг",
            "газпром-инвестхолдинг",
            "газпром инвестгазификация",
            "газпром-инвестгазификация",
            "газпром медиа",
            "газпром-медиа",
            "газпром экспорт",
            "газпром-экспорт",
            "газпром энергохолдинг",
            "газпром-энергохолдинг",
            "gazprom neft",
            "gazpromneft",
        ),
        "group": (
            "газпром нефть",
            "газпром нефти",
            "газпромнефть",
            "газпром-нефть",
            "газпромбанк",
            "газпром банк",
            "газпром межрегионгаз",
            "газпром-межрегионгаз",
            "газпром арена",
            "газпром-арена",
            "газпром инвест",
            "газпром-инвест",
            "газпром инвестхолдинг",
            "газпром-инвестхолдинг",
            "газпром инвестгазификация",
            "газпром-инвестгазификация",
            "газпром экспорт",
            "газпром-экспорт",
            "газпром энергохолдинг",
            "газпром-энергохолдинг",
            "газпром добыча",
            "газпром-добыча",
            "газпром трансгаз",
            "газпром-трансгаз",
            "газпром медиа",
            "газпром-медиа",
            "газпром академия",
            "газпром-академия",
            "газпром югра",
            "газпром-югра",
            "gazprom neft",
            "gazpromneft",
        ),
        "group_roots": ("газпром", "gazprom"),
    },
    "SIBN": {
        "main": (
            "sibn",
            "газпром нефть",
            "газпром-нефть",
            "газпромнефть",
            "пао газпром нефть",
            "газпром нефти",
            "акции газпром нефти",
            "gazprom neft",
            "gazpromneft",
        ),
        "exclude": (),
        "group": (
            "газпром",
            "газпрома",
            "пао газпром",
            "gazp",
            "gazprom",
        ),
        "group_roots": ("газпром нефть", "газпромнефть"),
    },
    "SBER": {
        "main": (
            "sber",
            "сбер",
            "сбербанк",
            "пао сбербанк",
            "сбербанка",
            "акции сбера",
            "акции сбербанка",
        ),
        "exclude": (),
        "group": (),
        "group_roots": (),
    },
}

GROUP_STRUCTURE_KEYWORDS = (
    "академия",
    "арена",
    "нефть",
    "банк",
    "страхование",
    "лизинг",
    "капитал",
    "инвестиции",
    "энерго",
    "энергосбыт",
    "логистика",
    "технологии",
    "медиа",
    "маркет",
    "газораспределение",
    "межрегионгаз",
    "инвестгазификация",
    "югра",
    "добыча",
    "бурение",
)

POSITIVE_NEWS_KEYWORDS = (
    "рост",
    "вырос",
    "выросла",
    "выросли",
    "рекорд",
    "прибыль",
    "дивиденд",
    "дивиденды",
    "улучш",
    "сильн",
    "отчет",
    "отчёт",
    "buy",
    "покупать",
    "повысил прогноз",
    "роста",
    "рекомендовал покупать",
    "целевая цена повышена",
)

NEGATIVE_NEWS_KEYWORDS = (
    "паден",
    "упал",
    "упала",
    "снижен",
    "снижение",
    "убыт",
    "штраф",
    "сбой",
    "иск",
    "суд",
    "санкц",
    "проблем",
    "дефолт",
    "обвал",
    "риск",
    "манипулир",
    "нарушен",
    "понизил прогноз",
    "рекомендовал продавать",
)

# Эти темы ближе к инвестиционному анализу российских акций.
INVESTMENT_NEWS_TOPICS = {
    "reporting": {
        "label": "отчетность",
        "weight": 4,
        "keywords": (
            "отчет",
            "отчёт",
            "отчетность",
            "финансовые результаты",
            "операционные результаты",
            "рсбу",
            "мсфо",
            "ebitda",
            "выручк",
            "квартал",
            "полугод",
            "9 месяцев",
            "годовые результаты",
        ),
    },
    "dividends": {
        "label": "дивиденды",
        "weight": 4,
        "keywords": (
            "дивиденд",
            "дивиденды",
            "дивидендная",
            "дивидендов",
            "дивидендную политику",
            "дивидендная доходность",
            "выплату дивидендов",
            "отсечк",
        ),
    },
    "profit": {
        "label": "прибыль",
        "weight": 4,
        "keywords": (
            "прибыл",
            "чистая прибыль",
            "убыт",
            "убыток",
            "маржа",
            "рентабельност",
        ),
    },
    "crediting_rates": {
        "label": "кредитование и ставки",
        "weight": 3,
        "keywords": (
            "кредит",
            "кредитован",
            "ключевая ставка",
            "ставк",
            "процентн",
            "стоимость фондирования",
            "долг",
            "обслуживание долга",
        ),
    },
    "sanctions": {
        "label": "санкции и регулирование",
        "weight": 4,
        "keywords": (
            "санкц",
            "ограничени",
            "запрет",
            "эмбарго",
            "регулятор",
            "регуляторн",
        ),
    },
    "strategy": {
        "label": "стратегия",
        "weight": 3,
        "keywords": (
            "стратег",
            "инвестпрограмм",
            "прогноз",
            "guidance",
            "capex",
            "план развития",
            "развит",
            "цель компании",
            "долгосрочная цель",
        ),
    },
    "ratings": {
        "label": "рейтинги и рекомендации",
        "weight": 4,
        "keywords": (
            "рейтинг",
            "рейтингов",
            "рекомендац",
            "аналитики",
            "аналитик",
            "целевая цена",
            "таргет",
            "buy",
            "hold",
            "sell",
            "покупать",
            "держать",
            "продавать",
        ),
    },
    "corporate_events": {
        "label": "корпоративные события",
        "weight": 4,
        "keywords": (
            "совет директоров",
            "совета директоров",
            "собрание акционеров",
            "внеочередное собрание",
            "байбэк",
            "buyback",
            "spo",
            "ipo",
            "допэмисс",
            "реорганизац",
            "слияни",
            "поглощени",
            "смена гендиректора",
            "гендиректор",
            "ceo",
            "листинг",
            "делистинг",
        ),
    },
    "trading": {
        "label": "биржевая торговля",
        "weight": 2,
        "keywords": (
            "акции",
            "бумаги",
            "котировк",
            "торги",
            "бирж",
            "ликвидност",
            "индекс",
            "объем торгов",
            "волатильн",
        ),
    },
}

GENERAL_MARKET_KEYWORDS = (
    "акции",
    "бумаги",
    "котировк",
    "рынок",
    "бирж",
    "торги",
    "эмитент",
    "инвестор",
    "капитализац",
    "стоимость компании",
    "цена акции",
)

WEAK_NEWS_KEYWORDS = (
    "приложени",
    "сервис",
    "клиент",
    "банкомат",
    "карта",
    "кешбэк",
    "офис",
    "отделени",
    "филиал",
    "магазин",
    "доставк",
    "маркетплейс",
    "подписк",
    "скидк",
    "бонус",
    "промокод",
    "реклам",
    "фестиваль",
    "конкурс",
    "розыгрыш",
    "мобильн",
    "абонент",
    "тариф",
    "пользовател",
    "потребител",
    "туризм",
    "путешеств",
    "ресторан",
)

INVESTMENT_SOURCE_HINTS = (
    "инвестиции",
    "интерфакс",
    "прайм",
    "финам",
    "бкс",
    "cbonds",
    "ведомости",
    "smart-lab",
)


class NewsProviderError(Exception):
    """Ошибка при получении новостей из внешнего источника."""


STORY_DEDUP_STOPWORDS = {
    "а",
    "без",
    "в",
    "во",
    "для",
    "до",
    "за",
    "из",
    "и",
    "или",
    "к",
    "как",
    "на",
    "над",
    "не",
    "но",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "у",
    "что",
    "это",
    "the",
    "an",
    "and",
    "for",
    "of",
    "to",
    "in",
    "on",
}

STORY_GENERIC_TOKENS = {
    "акции",
    "бумаги",
    "компания",
    "эмитент",
    "рынок",
    "торги",
    "биржа",
    "инвестор",
    "аналитик",
    "аналитики",
    "рубль",
    "рублей",
    "руб",
    "млрд",
    "млн",
    "тыс",
}

STORY_NUMERIC_TOKENS = {
    "2024",
    "2025",
    "2026",
    "q1",
    "q2",
    "q3",
    "q4",
    "h1",
    "h2",
    "9m",
    "1к",
    "2к",
    "3к",
    "4к",
    "1п",
    "2п",
    "1кв",
    "2кв",
    "3кв",
    "4кв",
}

STORY_SOURCE_PRIORITY_HINTS = (
    (5, ("интерфакс", "interfax")),
    (4, ("forbes", "форбс", "moex", "мосбирж", "e-disclosure", "раскрытие")),
    (3, ("ведомости", "prime", "прайм", "рбк", "reuters", "tass", "тасс")),
    (2, ("бкс", "финам", "альфа", "sberbank-cib", "втб", "cbonds")),
    (1, ("smart-lab", "смартлаб", "blog", "блог")),
)


def get_company_news_summary(ticker: str, stock_data: dict | None = None) -> dict:
    """Публичная точка входа для получения новостей по компании.

    По умолчанию используется бесплатный RSS-поиск Google News без API-ключа.
    Если источник не ответил или новостей не нашлось, функция не придумывает
    результаты, а честно возвращает сообщение об этом.
    """

    normalized_ticker = ticker.strip().upper()
    provider = get_news_provider()

    if provider == "stub":
        return get_company_news_summary_stub(normalized_ticker)

    if provider != "google_news_rss":
        return _build_news_error(
            ticker=normalized_ticker,
            provider=provider,
            message=(
                f"Провайдер новостей '{provider}' не поддерживается. "
                "Сейчас доступны только google_news_rss и stub."
            ),
        )

    return get_company_news_summary_from_google_news(normalized_ticker, stock_data)


def get_news_provider() -> str:
    """Читает название провайдера новостей из переменных окружения."""

    provider = os.getenv("NEWS_PROVIDER", DEFAULT_NEWS_PROVIDER)
    normalized_provider = provider.strip().lower()
    return normalized_provider or DEFAULT_NEWS_PROVIDER


def get_company_news_summary_stub(ticker: str) -> dict:
    """Возвращает честную заглушку для новостей."""

    return {
        "ticker": ticker,
        "available": False,
        "headline": None,
        "summary": "Источник новостей отключен: используется локальная заглушка.",
        "sentiment": "unknown",
        "items": [],
        "provider": "stub",
        "source": "stub",
        "is_stub": True,
        "message": "Источник новостей отключен: используется локальная заглушка.",
        "query": None,
        "relevant_items_available": False,
        "all_items_weak": False,
        "significant_items_count": 0,
        "neutral_items_count": 0,
        "weak_items_count": 0,
        "emitter_items_count": 0,
        "group_items_count": 0,
        "other_company_items_count": 0,
        "total_items_found": 0,
        "shown_items_count": 0,
        "hidden_weak_items_count": 0,
        "hidden_duplicate_items_count": 0,
    }


def get_company_news_summary_from_google_news(ticker: str, stock_data: dict | None = None) -> dict:
    """Получает новости по компании через бесплатный RSS-поиск Google News."""

    query = _build_google_news_query(ticker, stock_data)
    feed_url = _build_google_news_rss_url(query)

    try:
        xml_text = _fetch_rss_text(feed_url)
    except NewsProviderError as error:
        return _build_news_error(
            ticker=ticker,
            provider="google_news_rss",
            message=(
                f"Не удалось получить новости по {ticker}. "
                f"Причина: {error}"
            ),
            query=query,
        )

    try:
        items = _parse_google_news_rss(xml_text)
    except NewsProviderError as error:
        return _build_news_error(
            ticker=ticker,
            provider="google_news_rss",
            message=(
                f"Не удалось разобрать новостную ленту по {ticker}. "
                f"Причина: {error}"
            ),
            query=query,
        )

    unique_items = _deduplicate_news_items(items)

    if not unique_items:
        return _build_news_error(
            ticker=ticker,
            provider="google_news_rss",
            message=(
                f"По {ticker} не удалось найти свежие новости в бесплатной ленте Google News RSS."
            ),
            query=query,
        )

    issuer_profile = _build_issuer_profile(ticker, stock_data)
    ranked_items = _rank_news_items(unique_items, issuer_profile)
    issuer_items = [item for item in ranked_items if item["issuer_match"] != "other"]
    deduplicated_items, hidden_duplicate_items = _deduplicate_story_items(ranked_items, issuer_profile)
    max_items = _get_news_max_items()
    display_items = _select_items_for_output(deduplicated_items, max_items)
    relevant_items = _select_items_for_analysis(deduplicated_items)

    sentiment = _estimate_news_sentiment(relevant_items)
    summary = _build_news_summary_text(
        ranked_items,
        issuer_items,
        display_items,
        sentiment,
        hidden_duplicate_items,
    )
    counts = _count_relevance_groups(issuer_items)
    issuer_counts = _count_issuer_match_groups(ranked_items)

    return {
        "ticker": ticker,
        "available": True,
        "headline": display_items[0]["title"] if display_items else None,
        "summary": summary,
        "sentiment": sentiment,
        "items": display_items,
        "provider": "google_news_rss",
        "source": "google_news_rss",
        "is_stub": False,
        "message": None,
        "query": query,
        "relevant_items_available": bool(relevant_items),
        "all_items_weak": not relevant_items,
        "significant_items_count": counts["investment_significant"],
        "neutral_items_count": counts["neutral"],
        "weak_items_count": counts["weak"],
        "emitter_items_count": issuer_counts["emitter"],
        "group_items_count": issuer_counts["group"],
        "other_company_items_count": issuer_counts["other"],
        "total_items_found": len(ranked_items),
        "shown_items_count": len(display_items),
        "hidden_weak_items_count": max(0, counts["weak"] - _count_weak_items(display_items)),
        "hidden_duplicate_items_count": hidden_duplicate_items,
    }


def _build_google_news_query(ticker: str, stock_data: dict | None = None) -> str:
    """Собирает поисковый запрос для ленты новостей.

    Стараемся искать и по тикеру, и по названию компании, если оно уже
    пришло из MOEX. Это повышает шанс получить релевантные публикации.
    """

    aliases = [ticker]

    if stock_data:
        aliases.extend(
            [
                stock_data.get("short_name"),
                stock_data.get("full_name"),
            ]
        )

    normalized_aliases: list[str] = []

    for alias in aliases:
        normalized_alias = _normalize_company_alias(alias)
        if normalized_alias and normalized_alias not in normalized_aliases:
            normalized_aliases.append(normalized_alias)

    quoted_aliases = [f'"{alias}"' for alias in normalized_aliases[:3]]

    if not quoted_aliases:
        return ticker

    return " OR ".join(quoted_aliases)


def _normalize_company_alias(value: Any) -> str | None:
    """Очищает название компании для поискового запроса."""

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace('"', " ").replace("«", " ").replace("»", " ")
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\b(ПАО|АО|ОАО|ао|ап|PJSC|PAO)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")

    return text or None


def _normalize_text_for_matching(value: str) -> str:
    """Нормализует текст для сравнения названий компаний в заголовках."""

    text = value.lower().replace("ё", "е")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace('"', " ").replace("«", " ").replace("»", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_issuer_profile(ticker: str, stock_data: dict | None = None) -> dict:
    """Собирает профиль эмитента для проверки точности заголовков.

    Здесь мы отделяем саму компанию от дочерних и связанных структур,
    чтобы похожие названия не загрязняли ленту по конкретной бумаге.
    """

    main_aliases: list[str] = []
    exclude_aliases: list[str] = []
    group_aliases: list[str] = []

    raw_aliases = [ticker]

    if stock_data:
        raw_aliases.extend(
            [
                stock_data.get("short_name"),
                stock_data.get("full_name"),
            ]
        )

    for alias in raw_aliases:
        normalized_alias = _normalize_company_alias(alias)
        if normalized_alias:
            main_aliases.append(_normalize_text_for_matching(normalized_alias))

    profile = EMITTER_PROFILES.get(ticker, {})

    for alias in profile.get("main", ()):
        main_aliases.append(_normalize_text_for_matching(alias))

    for alias in profile.get("exclude", ()):
        exclude_aliases.append(_normalize_text_for_matching(alias))

    for alias in profile.get("group", ()):
        group_aliases.append(_normalize_text_for_matching(alias))

    return {
        "ticker": ticker,
        "main_aliases": _unique_non_empty_values(main_aliases),
        "exclude_aliases": _unique_non_empty_values(exclude_aliases),
        "group_aliases": _unique_non_empty_values(group_aliases),
        "group_roots": _unique_non_empty_values(
            [_normalize_text_for_matching(value) for value in profile.get("group_roots", ())]
        ),
    }


def _build_google_news_rss_url(query: str) -> str:
    """Собирает URL RSS-ленты Google News для конкретного запроса."""

    base_url = os.getenv("GOOGLE_NEWS_RSS_URL", DEFAULT_GOOGLE_NEWS_RSS_URL)
    params = {
        "q": query,
        "hl": "ru",
        "gl": "RU",
        "ceid": "RU:ru",
    }
    return f"{base_url}?{urlencode(params)}"


def _fetch_rss_text(url: str) -> str:
    """Загружает RSS-ленту как текст."""

    timeout_seconds = _get_request_timeout_seconds()
    request = Request(
        url=url,
        headers={
            "User-Agent": "investment-agent/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise NewsProviderError(f"HTTP {error.code} от новостного сервера") from error
    except URLError as error:
        raise NewsProviderError("новостный сервер недоступен или нет подключения к интернету") from error
    except TimeoutError as error:
        raise NewsProviderError("запрос к новостной ленте превысил время ожидания") from error
    except OSError as error:
        raise NewsProviderError("не удалось установить соединение с новостной лентой") from error

    if not body.strip():
        raise NewsProviderError("новостная лента вернула пустой ответ")

    return body


def _parse_google_news_rss(xml_text: str) -> list[dict]:
    """Разбирает XML-ленту Google News RSS в список новостей."""

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise NewsProviderError("RSS-лента вернула некорректный XML") from error

    channel = root.find("channel")
    if channel is None:
        raise NewsProviderError("в RSS-ответе не найден канал новостей")

    items: list[dict] = []

    for item in channel.findall("item"):
        title = _clean_xml_text(item.findtext("title"))
        link = _clean_xml_text(item.findtext("link"))
        pub_date_raw = _clean_xml_text(item.findtext("pubDate"))
        source_element = item.find("source")
        source_name = _clean_xml_text(source_element.text if source_element is not None else None)
        source_url = source_element.attrib.get("url") if source_element is not None else None

        if not title:
            continue

        items.append(
            {
                "title": title,
                "link": link,
                "published_at": _format_pub_date(pub_date_raw),
                "published_at_raw": pub_date_raw,
                "source": source_name,
                "source_url": source_url,
            }
        )

    return items


def _clean_xml_text(value: str | None) -> str | None:
    """Очищает текстовые поля из RSS XML."""

    if value is None:
        return None

    cleaned = html.unescape(value).strip()
    return cleaned or None


def _format_pub_date(value: str | None) -> str | None:
    """Переводит дату публикации в простой формат для CLI."""

    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return value

    return parsed.strftime("%d.%m.%Y %H:%M")


def _deduplicate_news_items(items: list[dict]) -> list[dict]:
    """Убирает дубли по заголовку, чтобы не засорять ответ."""

    seen_titles: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        title_key = item["title"].strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        unique_items.append(item)

    return unique_items


def _rank_news_items(items: list[dict], issuer_profile: dict) -> list[dict]:
    """Классифицирует новости и сортирует более важные выше."""

    ranked_items = [
        _classify_news_item(item, original_index=index, issuer_profile=issuer_profile)
        for index, item in enumerate(items)
    ]

    ranked_items.sort(
        key=lambda item: (
            -_get_issuer_match_rank(item["issuer_match"]),
            -_get_relevance_rank(item["relevance"]),
            -item["relevance_score"],
            item["original_index"],
        )
    )

    return ranked_items


def _classify_news_item(item: dict, original_index: int, issuer_profile: dict) -> dict:
    """Присваивает новости простую инвестиционную классификацию.

    Мы смотрим только на заголовок и источник. Это не умный NLP-анализ,
    а понятная эвристика, которую новичку легко доработать позже.
    """

    title = _normalize_text_for_matching(item["title"])
    source = (item.get("source") or "").lower()
    matched_topic_keys: list[str] = []
    matched_topics: list[str] = []
    score = 0
    issuer_match = _detect_issuer_match_level_from_profile(title, issuer_profile)

    for topic_key, topic_data in INVESTMENT_NEWS_TOPICS.items():
        if any(keyword in title for keyword in topic_data["keywords"]):
            matched_topic_keys.append(topic_key)
            matched_topics.append(topic_data["label"])
            score += topic_data["weight"]

    has_market_hint = any(keyword in title for keyword in GENERAL_MARKET_KEYWORDS)
    has_weak_hint = any(keyword in title for keyword in WEAK_NEWS_KEYWORDS)
    has_investment_source_hint = any(keyword in source for keyword in INVESTMENT_SOURCE_HINTS)
    strong_topic_keys = {
        "reporting",
        "dividends",
        "profit",
        "crediting_rates",
        "sanctions",
        "strategy",
        "ratings",
        "corporate_events",
    }
    has_strong_topic = any(topic_key in strong_topic_keys for topic_key in matched_topic_keys)

    if matched_topics and has_strong_topic:
        relevance = "investment_significant"
    elif matched_topics:
        relevance = "neutral"
    elif has_market_hint:
        relevance = "neutral"
    else:
        relevance = "weak"

    if has_investment_source_hint and relevance != "weak":
        score += 1

    if has_weak_hint:
        score -= 1
        if not matched_topics and not has_market_hint:
            relevance = "weak"
        elif not has_strong_topic:
            relevance = "neutral" if (matched_topics or has_market_hint) else "weak"

    # Точность эмитента важнее темы новости: публикации про другую компанию
    # с похожим названием не должны выглядеть релевантными для текущей бумаги.
    if issuer_match == "other":
        relevance = "weak"
        score -= 4
    elif issuer_match == "group":
        score += 1
    else:
        score += 3

    return {
        **item,
        "original_index": original_index,
        "normalized_title": title,
        "relevance": relevance,
        "relevance_label_ru": RELEVANCE_LABELS_RU[relevance],
        "issuer_match": issuer_match,
        "issuer_match_label_ru": ISSUER_MATCH_LABELS_RU[issuer_match],
        "relevance_score": score,
        "topic_keys": matched_topic_keys,
        "topics": matched_topics,
    }


def _detect_issuer_match_level(ticker: str, title: str, stock_data: dict | None = None) -> str:
    """Определяет итоговый уровень совпадения новости с эмитентом.

    Порядок проверки строгий:
    1. точные исключающие сущности;
    2. групповые сущности;
    3. прямые сущности эмитента;
    4. fallback-эвристика по группе;
    5. иначе другая компания или нет явного совпадения.
    """

    issuer_profile = _build_issuer_profile(ticker, stock_data)
    normalized_title = _normalize_text_for_matching(title)
    return _detect_issuer_match_level_from_profile(normalized_title, issuer_profile)


def _detect_issuer_match_level_from_profile(title: str, issuer_profile: dict) -> str:
    """Определяет уровень совпадения по уже подготовленному профилю эмитента."""

    main_aliases = issuer_profile.get("main_aliases", [])
    exclude_aliases = issuer_profile.get("exclude_aliases", [])
    group_aliases = issuer_profile.get("group_aliases", [])
    group_roots = issuer_profile.get("group_roots", [])

    # 1. Более точные исключающие сущности имеют абсолютный приоритет
    # над общим совпадением по слову из основного бренда.
    if _find_alias_spans(title, exclude_aliases):
        return "group"

    # 2. Явные групповые сущности идут следом.
    # Если групповое совпадение целиком вложено в более точную main-сущность,
    # приоритет получает main. Это защищает кейс SIBN: "Газпром нефть"
    # не должна падать в group только из-за слова "Газпром".
    group_spans = _find_alias_spans(title, group_aliases)
    main_spans = _find_alias_spans(title, main_aliases)

    if _has_match_outside_spans(group_spans, main_spans):
        return "group"

    # 3. Только теперь проверяем прямое совпадение с эмитентом.
    if main_spans:
        return "emitter"

    # 4. Fallback-эвристика: брендовый корень + дочерняя/смежная сущность.
    if _find_group_like_spans(title, group_roots):
        return "group"

    return "other"


def _find_alias_spans(text: str, aliases: list[str]) -> list[tuple[int, int]]:
    """Ищет точные вхождения названий компаний в заголовке."""

    spans: list[tuple[int, int]] = []

    for alias in aliases:
        normalized_alias = _normalize_text_for_matching(alias)
        if not normalized_alias:
            continue

        pattern = _build_alias_regex(normalized_alias)
        spans.extend(match.span() for match in pattern.finditer(text))

    return spans


def _find_group_like_spans(text: str, group_roots: list[str]) -> list[tuple[int, int]]:
    """Ищет конструкции вида 'бренд группы + дочерняя/смежная структура'."""

    spans: list[tuple[int, int]] = []

    for root in group_roots:
        normalized_root = _normalize_text_for_matching(root)
        if not normalized_root:
            continue

        for suffix in GROUP_STRUCTURE_KEYWORDS:
            pattern = re.compile(
                rf"(?<!\w){_build_alias_pattern_body(normalized_root)}(?:\s+|-){re.escape(suffix)}(?!\w)"
            )
            spans.extend(match.span() for match in pattern.finditer(text))

    return spans


def _has_match_outside_spans(
    candidate_spans: list[tuple[int, int]],
    container_spans: list[tuple[int, int]],
) -> bool:
    """Проверяет, есть ли совпадение, не вложенное в более точную сущность."""

    for candidate_span in candidate_spans:
        if not any(_span_is_inside(candidate_span, container_span) for container_span in container_spans):
            return True

    return False


def _span_is_inside(inner_span: tuple[int, int], outer_span: tuple[int, int]) -> bool:
    """Проверяет, что одно совпадение полностью вложено в другое."""

    inner_start, inner_end = inner_span
    outer_start, outer_end = outer_span
    return outer_start <= inner_start and inner_end <= outer_end


def _build_alias_regex(alias: str) -> re.Pattern[str]:
    """Строит регулярное выражение для имени компании.

    Для русских слов разрешаем частые падежные окончания, чтобы
    находить `Газпром`, `Газпрома`, `Газпромом` и похожие формы.
    """

    return re.compile(rf"(?<!\w){_build_alias_pattern_body(alias)}(?!\w)")


def _build_alias_pattern_body(alias: str) -> str:
    """Строит центральную часть регулярного выражения для алиаса компании."""

    token_patterns = [_build_alias_token_pattern(token) for token in alias.split()]
    return r"(?:\s+|-)".join(token_patterns)


def _build_alias_token_pattern(token: str) -> str:
    """Возвращает шаблон для одного слова внутри имени компании."""

    if re.fullmatch(r"[a-z0-9]+", token):
        return re.escape(token)

    if re.fullmatch(r"[а-я]+", token) and len(token) >= 4:
        common_endings = (
            "",
            "а",
            "у",
            "е",
            "ом",
            "ы",
            "ов",
            "ам",
            "ами",
            "ах",
            "и",
            "ю",
            "ья",
            "ью",
            "ям",
            "ями",
            "ях",
        )
        unique_endings = sorted(set(common_endings), key=len, reverse=True)
        endings_pattern = "|".join(re.escape(ending) for ending in unique_endings if ending)
        return rf"{re.escape(token)}(?:{endings_pattern})?"

    return re.escape(token)


def _get_relevance_rank(relevance: str) -> int:
    """Возвращает числовой приоритет для сортировки новостей."""

    return {
        "investment_significant": 3,
        "neutral": 2,
        "weak": 1,
    }.get(relevance, 0)


def _get_issuer_match_rank(issuer_match: str) -> int:
    """Возвращает приоритет по точности совпадения эмитента."""

    return {
        "emitter": 3,
        "group": 2,
        "other": 1,
    }.get(issuer_match, 0)


def _deduplicate_story_items(items: list[dict], issuer_profile: dict) -> tuple[list[dict], int]:
    """Hides near-duplicate headlines about the same story from the final news list."""

    clusters: list[dict] = []
    hidden_count = 0

    for item in items:
        candidate = _attach_story_signature(item, issuer_profile)
        matched_cluster: dict | None = None

        for cluster in clusters:
            if _are_story_duplicates(candidate, cluster["representative"]):
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append({"representative": candidate, "items": [candidate]})
            continue

        matched_cluster["items"].append(candidate)
        hidden_count += 1

        if _is_better_story_representative(candidate, matched_cluster["representative"]):
            matched_cluster["representative"] = candidate

    deduplicated_items = [cluster["representative"] for cluster in clusters]
    deduplicated_items.sort(key=_get_display_sort_key, reverse=True)
    return deduplicated_items, hidden_count


def _attach_story_signature(item: dict, issuer_profile: dict) -> dict:
    """Adds lightweight story features used only for display deduplication."""

    title = item.get("normalized_title") or _normalize_text_for_matching(item["title"])
    topic_keys = tuple(item.get("topic_keys", ()))
    story_periods = _extract_story_periods(title)
    story_tokens = _extract_story_tokens(title, issuer_profile, story_periods)

    return {
        **item,
        "story_periods": tuple(sorted(story_periods)),
        "story_tokens": tuple(sorted(story_tokens)),
        "source_priority": _get_source_priority(item.get("source")),
        "published_timestamp": _get_publication_timestamp(item.get("published_at_raw")),
        "title_information_score": _get_title_information_score(item["title"], story_tokens, story_periods),
        "topic_keys": topic_keys,
    }


def _extract_story_periods(title: str) -> set[str]:
    """Extracts coarse period markers so quarter and year stories compare more accurately."""

    normalized_title = _normalize_text_for_matching(title)
    periods: set[str] = set()

    period_patterns = (
        (r"\b(i|1)\s*(?:квартал|кв)\b", "q1"),
        (r"\b(ii|2)\s*(?:квартал|кв)\b", "q2"),
        (r"\b(iii|3)\s*(?:квартал|кв)\b", "q3"),
        (r"\b(iv|4)\s*(?:квартал|кв)\b", "q4"),
        (r"\bперв\w*\s+квартал", "q1"),
        (r"\bвтор\w*\s+квартал", "q2"),
        (r"\bтреть\w*\s+квартал", "q3"),
        (r"\bчетверт\w*\s+квартал", "q4"),
        (r"\b1к\b|\b1кв\b", "q1"),
        (r"\b2к\b|\b2кв\b", "q2"),
        (r"\b3к\b|\b3кв\b", "q3"),
        (r"\b4к\b|\b4кв\b", "q4"),
        (r"\b1п\b|\bперв\w*\s+полугод", "h1"),
        (r"\b2п\b|\bвтор\w*\s+полугод", "h2"),
        (r"\b9м\b|\b9м\d{2}\b|\b9\s*месяц", "9m"),
    )

    for pattern, marker in period_patterns:
        if re.search(pattern, normalized_title):
            periods.add(marker)

    for year in re.findall(r"\b20\d{2}\b", normalized_title):
        periods.add(year)

    return periods


def _extract_story_tokens(title: str, issuer_profile: dict, story_periods: set[str]) -> set[str]:
    """Builds a small set of informative tokens describing the news story."""

    tokens = re.findall(r"[a-zа-я0-9]+", _normalize_text_for_matching(title))
    issuer_tokens = _collect_issuer_profile_tokens(issuer_profile)
    story_tokens: set[str] = set(story_periods)

    for token in tokens:
        normalized_token = _normalize_story_token(token)
        if not normalized_token:
            continue
        if normalized_token in issuer_tokens:
            continue
        story_tokens.add(normalized_token)

    return story_tokens


def _collect_issuer_profile_tokens(issuer_profile: dict) -> set[str]:
    """Collects generic brand tokens so they do not dominate story similarity."""

    tokens: set[str] = set()

    for aliases_key in ("main_aliases", "exclude_aliases", "group_aliases", "group_roots"):
        for alias in issuer_profile.get(aliases_key, []):
            for token in re.findall(r"[a-zа-я0-9]+", _normalize_text_for_matching(alias)):
                if len(token) >= 3:
                    tokens.add(token)

    return tokens


def _normalize_story_token(token: str) -> str | None:
    """Normalizes a token for coarse story comparison without heavy NLP."""

    if not token or token in STORY_DEDUP_STOPWORDS:
        return None

    if re.fullmatch(r"20\d{2}", token):
        return token

    if token in STORY_NUMERIC_TOKENS:
        return token

    if token in STORY_GENERIC_TOKENS:
        return None

    if len(token) <= 2 and not re.search(r"\d", token):
        return None

    prefix_mapping = (
        ("прибыл", "прибыль"),
        ("убыт", "убыток"),
        ("выруч", "выручка"),
        ("дивид", "дивиденды"),
        ("отчет", "отчет"),
        ("отчит", "отчет"),
        ("рсбу", "рсбу"),
        ("мсфо", "мсфо"),
        ("кварт", "квартал"),
        ("полугод", "полугодие"),
        ("годов", "год"),
        ("прогноз", "прогноз"),
        ("guidance", "прогноз"),
        ("рейтинг", "рейтинг"),
        ("реком", "рекомендация"),
        ("таргет", "рекомендация"),
        ("целе", "рекомендация"),
        ("buy", "рекомендация"),
        ("hold", "рекомендация"),
        ("sell", "рекомендация"),
        ("совет", "совдир"),
        ("директор", "совдир"),
        ("собран", "собрание"),
        ("акционер", "собрание"),
        ("байбек", "buyback"),
        ("buyback", "buyback"),
        ("spo", "spo"),
        ("ipo", "ipo"),
        ("санкц", "санкции"),
        ("ставк", "ставки"),
        ("кредит", "кредит"),
        ("долг", "долг"),
        ("рост", "рост"),
        ("вырос", "рост"),
        ("увелич", "рост"),
        ("нараст", "рост"),
        ("сниз", "снижение"),
        ("сократ", "снижение"),
        ("упал", "снижение"),
        ("паден", "снижение"),
    )

    for prefix, canonical in prefix_mapping:
        if token.startswith(prefix):
            return canonical

    if re.search(r"\d", token):
        return token

    if len(token) < 4:
        return None

    return token


def _are_story_duplicates(left: dict, right: dict) -> bool:
    """Checks whether two classified items look like the same news story."""

    if left["issuer_match"] != right["issuer_match"]:
        return False

    if left["normalized_title"] == right["normalized_title"]:
        return True

    left_tokens = set(left.get("story_tokens", ()))
    right_tokens = set(right.get("story_tokens", ()))

    if not left_tokens or not right_tokens:
        return False

    shared_tokens = left_tokens & right_tokens
    shared_topics = set(left.get("topic_keys", ())) & set(right.get("topic_keys", ()))
    shared_periods = set(left.get("story_periods", ())) & set(right.get("story_periods", ()))
    smaller_story_size = min(len(left_tokens), len(right_tokens))
    overlap_ratio = len(shared_tokens) / smaller_story_size if smaller_story_size else 0

    if shared_periods and shared_topics and len(shared_tokens) >= 2:
        return True

    if "reporting" in shared_topics and "profit" in shared_topics and len(shared_tokens) >= 2:
        return True

    if len(shared_tokens) >= 3 and overlap_ratio >= 0.6 and shared_topics:
        return True

    return False


def _is_better_story_representative(candidate: dict, current: dict) -> bool:
    """Chooses which duplicate headline should remain visible."""

    return _get_display_sort_key(candidate) > _get_display_sort_key(current)


def _get_display_sort_key(item: dict) -> tuple:
    """Returns a stable priority tuple for story representative selection and display order."""

    return (
        _get_relevance_rank(item["relevance"]),
        _get_issuer_match_rank(item["issuer_match"]),
        item.get("source_priority", _get_source_priority(item.get("source"))),
        item.get("published_timestamp", _get_publication_timestamp(item.get("published_at_raw"))),
        item.get(
            "title_information_score",
            _get_title_information_score(
                item["title"],
                set(item.get("story_tokens", ())),
                set(item.get("story_periods", ())),
            ),
        ),
        -item["original_index"],
    )


def _get_source_priority(source: str | None) -> int:
    """Gives a small priority boost to more useful sources when duplicates compete."""

    normalized_source = _normalize_text_for_matching(source or "")

    for priority, hints in STORY_SOURCE_PRIORITY_HINTS:
        if any(hint in normalized_source for hint in hints):
            return priority

    return 0


def _get_publication_timestamp(value: str | None) -> int:
    """Parses the raw RSS publication date into an integer timestamp for sorting."""

    if not value:
        return 0

    try:
        return int(parsedate_to_datetime(value).timestamp())
    except (TypeError, ValueError, IndexError, OSError, OverflowError):
        return 0


def _get_title_information_score(title: str, story_tokens: set[str], story_periods: set[str]) -> int:
    """Rewards titles that carry slightly more concrete information about the same story."""

    normalized_title = _normalize_text_for_matching(title)
    numeric_tokens = re.findall(r"\b\d+(?:[.,]\d+)?%?\b", normalized_title)
    return len(story_tokens) + len(story_periods) + len(numeric_tokens) + min(len(title) // 40, 3)


def _select_items_for_output(items: list[dict], max_items: int) -> list[dict]:
    """Показывает сначала более полезные новости.

    Если есть инвестиционно значимые или нейтральные заголовки, слабые
    новости скрываем из вывода. Если все новости слабые, показываем их,
    но честно предупреждаем об этом в summary.
    """

    preferred_items = [
        item for item in items
        if item["issuer_match"] in {"emitter", "group"} and item["relevance"] != "weak"
    ]

    if preferred_items:
        return preferred_items[:max_items]

    weak_issuer_items = [
        item for item in items
        if item["issuer_match"] in {"emitter", "group"}
    ]

    if weak_issuer_items:
        return weak_issuer_items[:max_items]

    return []


def _select_items_for_analysis(items: list[dict]) -> list[dict]:
    """Выбирает новости для оценки фона.

    Сначала стараемся опираться на прямые новости по эмитенту.
    Если их нет, допускаем косвенно связанные новости по группе.
    """

    emitter_items = [
        item for item in items
        if item["issuer_match"] == "emitter" and item["relevance"] != "weak"
    ]

    if emitter_items:
        return emitter_items

    return [
        item for item in items
        if item["issuer_match"] == "group" and item["relevance"] != "weak"
    ]


def _count_relevance_groups(items: list[dict]) -> dict[str, int]:
    """Считает, сколько новостей попало в каждую группу релевантности."""

    counts = {
        "investment_significant": 0,
        "neutral": 0,
        "weak": 0,
    }

    for item in items:
        counts[item["relevance"]] += 1

    return counts


def _count_issuer_match_groups(items: list[dict]) -> dict[str, int]:
    """Считает, сколько новостей попало в каждую группу по эмитенту."""

    counts = {
        "emitter": 0,
        "group": 0,
        "other": 0,
    }

    for item in items:
        counts[item["issuer_match"]] += 1

    return counts


def _count_weak_items(items: list[dict]) -> int:
    """Считает число слабых новостей в текущем списке."""

    return sum(1 for item in items if item["relevance"] == "weak")


def _estimate_news_sentiment(items: list[dict]) -> str:
    """Очень грубо оценивает фон по более релевантным заголовкам."""

    if not items:
        return "unknown"

    score = 0

    for item in items:
        title = item["title"].lower()
        if any(keyword in title for keyword in POSITIVE_NEWS_KEYWORDS):
            score += 1
        if any(keyword in title for keyword in NEGATIVE_NEWS_KEYWORDS):
            score -= 1

    if score >= 2:
        return "positive"
    if score <= -2:
        return "negative"
    if score != 0:
        return "mixed"
    return "neutral"


def _build_news_summary_text(
    all_items: list[dict],
    issuer_items: list[dict],
    shown_items: list[dict],
    sentiment: str,
    hidden_duplicate_items: int = 0,
) -> str:
    """Собирает короткое описание новостного фона для пользователя."""

    counts = _count_relevance_groups(issuer_items)
    issuer_counts = _count_issuer_match_groups(all_items)
    total_count = len(all_items)

    if issuer_counts["emitter"] == 0 and issuer_counts["group"] == 0:
        return (
            f"Найдено {_format_news_count(total_count)} в бесплатной ленте Google News RSS, "
            "но в заголовках не нашлось явного упоминания самого эмитента. "
            "Публикации по другим компаниям с похожим названием не включены в инвестиционный обзор."
        )

    if counts["investment_significant"] == 0 and counts["neutral"] == 0:
        parts = [
            f"Найдено {_format_news_count(total_count)} в бесплатной ленте Google News RSS.",
            (
                "Прямо по эмитенту: "
                f"{issuer_counts['emitter']}, по группе: {issuer_counts['group']}, "
                f"по другой компании с похожим названием: {issuer_counts['other']}."
            ),
            "По отобранным заголовкам новости пока выглядят слабо релевантными для инвестиционного анализа.",
        ]

        if issuer_counts["emitter"] == 0 and issuer_counts["group"] > 0:
            parts.append(
                "Прямых новостей именно по эмитенту пока не найдено, поэтому показаны только косвенно связанные публикации по группе."
            )

        if issuer_counts["other"] > 0:
            parts.append(
                "Публикации по другим компаниям с похожим названием скрыты."
            )

        if hidden_duplicate_items > 0:
            parts.append(
                "Часть похожих публикаций скрыта как дубли, чтобы новостной блок не повторял один и тот же сюжет."
            )

        return " ".join(parts)

    sentiment_label = {
        "positive": "умеренно позитивным",
        "negative": "умеренно негативным",
        "mixed": "смешанным",
        "neutral": "скорее нейтральным",
        "unknown": "неопределенным",
    }.get(sentiment, "неопределенным")

    parts = [
        f"Найдено {_format_news_count(total_count)} в бесплатной ленте Google News RSS.",
        (
            "Прямо по эмитенту: "
            f"{issuer_counts['emitter']}, по группе: {issuer_counts['group']}, "
            f"по другой компании с похожим названием: {issuer_counts['other']}."
        ),
        (
            "Инвестиционно значимых: "
            f"{counts['investment_significant']}, нейтральных: {counts['neutral']}, "
            f"слабо релевантных: {counts['weak']}."
        ),
        f"По более релевантным заголовкам фон выглядит {sentiment_label}.",
    ]

    if issuer_counts["emitter"] == 0 and issuer_counts["group"] > 0:
        parts.append(
            "Прямых новостей именно по эмитенту пока не найдено, поэтому фон оценивается по косвенно связанным публикациям группы."
        )

    hidden_weak_items = counts["weak"] - _count_weak_items(shown_items)
    if hidden_weak_items > 0:
        parts.append(
            "Часть слабо релевантных публикаций скрыта, чтобы не засорять инвестиционный обзор."
        )

    if issuer_counts["other"] > 0:
        parts.append(
            "Публикации по другим компаниям с похожим названием скрыты."
        )

    if hidden_duplicate_items > 0:
        parts.append(
            "Часть похожих публикаций скрыта как дубли, чтобы в итоговом списке не шли подряд новости об одном сюжете."
        )

    return " ".join(parts)


def _unique_non_empty_values(values: list[str]) -> list[str]:
    """Удаляет пустые и дублирующиеся значения, сохраняя порядок."""

    result: list[str] = []

    for value in values:
        normalized_value = value.strip()
        if normalized_value and normalized_value not in result:
            result.append(normalized_value)

    return result


def _debug_issuer_match_self_check() -> list[dict[str, str]]:
    """Возвращает результаты локальной самопроверки сопоставления эмитента.

    Функция не запускается автоматически и не ломает CLI. Ее можно вызвать
    вручную в локальной отладке, чтобы быстро проверить ключевые кейсы.
    """

    examples = [
        {
            "ticker": "GAZP",
            "title": 'Выручка "Газпром нефти" за 2025 год могла снизиться на 13%',
            "expected": "group",
        },
        {
            "ticker": "GAZP",
            "title": "После устойчивых 9М25 в 4К25 ожидаем ухудшение динамики Газпром нефти за 2025",
            "expected": "group",
        },
        {
            "ticker": "GAZP",
            "title": "Газпром отчитался о чистой прибыли по РСБУ",
            "expected": "emitter",
        },
        {
            "ticker": "GAZP",
            "title": "Газпромбанк улучшил условия по вкладам",
            "expected": "group",
        },
        {
            "ticker": "SIBN",
            "title": 'Выручка "Газпром нефти" за 2025 год могла снизиться на 13%',
            "expected": "emitter",
        },
        {
            "ticker": "SIBN",
            "title": "Газпром нефть отчитается за 2025",
            "expected": "emitter",
        },
        {
            "ticker": "SIBN",
            "title": "Газпром увеличил поставки газа",
            "expected": "group",
        },
        {
            "ticker": "SBER",
            "title": "Сбербанк увеличил чистую прибыль",
            "expected": "emitter",
        },
    ]

    results: list[dict[str, str]] = []

    for example in examples:
        actual = _detect_issuer_match_level(example["ticker"], example["title"])
        results.append(
            {
                "ticker": example["ticker"],
                "title": example["title"],
                "expected": example["expected"],
                "actual": actual,
                "status": "ok" if actual == example["expected"] else "mismatch",
            }
        )

    return results


def _debug_issuer_match_trace(ticker: str, title: str) -> dict[str, Any]:
    """Показывает, какие именно слои профиля сработали для заголовка.

    Эта функция нужна только для локальной диагностики, когда надо понять,
    почему новость ушла в `emitter`, `group` или `other`.
    """

    normalized_title = _normalize_text_for_matching(title)
    issuer_profile = _build_issuer_profile(ticker)

    return {
        "ticker": ticker,
        "title": title,
        "normalized_title": normalized_title,
        "exclude_matches": _find_alias_spans(normalized_title, issuer_profile.get("exclude_aliases", [])),
        "group_matches": _find_alias_spans(normalized_title, issuer_profile.get("group_aliases", [])),
        "main_matches": _find_alias_spans(normalized_title, issuer_profile.get("main_aliases", [])),
        "group_root_matches": _find_group_like_spans(normalized_title, issuer_profile.get("group_roots", [])),
        "final_level": _detect_issuer_match_level_from_profile(normalized_title, issuer_profile),
    }


def _debug_story_dedup_self_check() -> list[dict[str, Any]]:
    """Provides a tiny local self-check for story-level deduplication."""

    examples = [
        {
            "ticker": "SBER",
            "items": [
                {
                    "title": "Сбербанк в I квартале увеличил чистую прибыль по РСБУ",
                    "source": "Интерфакс",
                    "published_at_raw": "Fri, 11 Apr 2026 10:00:00 GMT",
                },
                {
                    "title": "Прибыль Сбербанка в первом квартале выросла до 491 млрд рублей",
                    "source": "Финам",
                    "published_at_raw": "Fri, 11 Apr 2026 09:00:00 GMT",
                },
                {
                    "title": "Сбербанк нарастил прибыль по РСБУ на 21,4%",
                    "source": "Smart-Lab",
                    "published_at_raw": "Fri, 11 Apr 2026 08:00:00 GMT",
                },
                {
                    "title": "Сбербанк может направить дивиденды за 2025 год",
                    "source": "Интерфакс",
                    "published_at_raw": "Fri, 11 Apr 2026 07:00:00 GMT",
                },
            ],
            "expected_count": 2,
        },
        {
            "ticker": "GAZP",
            "items": [
                {
                    "title": "Газпром отчитался о чистой прибыли по РСБУ за 2025 год",
                    "source": "Интерфакс",
                    "published_at_raw": "Fri, 11 Apr 2026 10:00:00 GMT",
                },
                {
                    "title": "Чистая прибыль Газпрома по РСБУ за 2025 год выросла",
                    "source": "Финам",
                    "published_at_raw": "Fri, 11 Apr 2026 09:30:00 GMT",
                },
                {
                    "title": "Газпром может скорректировать дивидендную политику",
                    "source": "РБК",
                    "published_at_raw": "Fri, 11 Apr 2026 08:00:00 GMT",
                },
            ],
            "expected_count": 2,
        },
    ]

    results: list[dict[str, Any]] = []

    for example in examples:
        issuer_profile = _build_issuer_profile(example["ticker"])
        ranked_items = _rank_news_items(example["items"], issuer_profile)
        deduplicated_items, hidden_count = _deduplicate_story_items(ranked_items, issuer_profile)
        results.append(
            {
                "ticker": example["ticker"],
                "expected_count": example["expected_count"],
                "actual_count": len(deduplicated_items),
                "hidden_count": hidden_count,
                "kept_titles": [item["title"] for item in deduplicated_items],
                "status": "ok" if len(deduplicated_items) == example["expected_count"] else "mismatch",
            }
        )

    return results


def _format_news_count(count: int) -> str:
    """Возвращает количество новостей с правильной формой слова."""

    last_two_digits = count % 100
    last_digit = count % 10

    if 11 <= last_two_digits <= 14:
        word = "публикаций"
    elif last_digit == 1:
        word = "публикация"
    elif 2 <= last_digit <= 4:
        word = "публикации"
    else:
        word = "публикаций"

    return f"{count} {word}"


def _get_request_timeout_seconds() -> int:
    """Читает таймаут запроса из переменных окружения."""

    raw_timeout = os.getenv("REQUEST_TIMEOUT_SECONDS", "10")

    try:
        timeout_seconds = int(raw_timeout)
    except ValueError:
        return 10

    return max(1, timeout_seconds)


def _get_news_max_items() -> int:
    """Читает максимальное число новостей для вывода."""

    raw_value = os.getenv("NEWS_MAX_ITEMS", str(DEFAULT_NEWS_MAX_ITEMS))

    try:
        max_items = int(raw_value)
    except ValueError:
        return DEFAULT_NEWS_MAX_ITEMS

    return max(1, min(max_items, 10))


def _build_news_error(ticker: str, provider: str, message: str, query: str | None = None) -> dict:
    """Возвращает единый формат ошибки для новостного модуля."""

    return {
        "ticker": ticker,
        "available": False,
        "headline": None,
        "summary": message,
        "sentiment": "unknown",
        "items": [],
        "provider": provider,
        "source": provider,
        "is_stub": False,
        "message": message,
        "query": query,
        "relevant_items_available": False,
        "all_items_weak": False,
        "significant_items_count": 0,
        "neutral_items_count": 0,
        "weak_items_count": 0,
        "emitter_items_count": 0,
        "group_items_count": 0,
        "other_company_items_count": 0,
        "total_items_found": 0,
        "shown_items_count": 0,
        "hidden_weak_items_count": 0,
        "hidden_duplicate_items_count": 0,
    }
