          """Core logic for generating a user-friendly stock analysis."""

import re
from typing import TypedDict

from tools.market_data import get_stock_snapshot
from tools.news import get_company_news_summary
from tools.portfolio import get_portfolio_context
from llm_analysis import (
    build_llm_full_analysis,
    build_llm_news_analysis,
    build_llm_risks_analysis,
    build_llm_idea,
    build_llm_today_ideas,
)


USER_TICKER_ALIASES = {
    "sber": "SBER",
    "sberbank": "SBER",
    "сбер": "SBER",
    "сбербанк": "SBER",
    "сбер банк": "SBER",
    "gazp": "GAZP",
    "gazprom": "GAZP",
    "газпром": "GAZP",
    "lkoh": "LKOH",
    "lukoil": "LKOH",
    "лукойл": "LKOH",
    "лукоил": "LKOH",
    "vtbr": "VTBR",
    "втб": "VTBR",
    "rosn": "ROSN",
    "rosneft": "ROSN",
    "роснефть": "ROSN",
}


def normalize_user_ticker_input(text: str) -> str:
    """Converts a user-friendly stock name into a MOEX ticker when possible."""

    cleaned_text = (text or "").strip()
    normalized_key = " ".join(
        cleaned_text.lower().replace("ё", "е").replace("-", " ").split()
    )

    if normalized_key in USER_TICKER_ALIASES:
        return USER_TICKER_ALIASES[normalized_key]

    return cleaned_text.upper()


def analyze_ticker(ticker: str) -> dict[str, str | None]:
    """Safely wraps stock analysis into a stable response dict for integrations."""

    normalized_ticker = normalize_user_ticker_input(ticker)

    try:
        analysis_text = build_stock_analysis(normalized_ticker)
    except Exception as error:
        return {
            "ticker": normalized_ticker,
            "analysis_text": None,
            "error": str(error),
        }

    return {
        "ticker": normalized_ticker,
        "analysis_text": analysis_text,
        "error": None,
    }


# ─────────────────────────────────────────────
#  Новые LLM-форматтеры (через Google Gemini)
# ─────────────────────────────────────────────

DISCLAIMER = "\n\n⚠️ Не является индивидуальной инвестиционной рекомендацией."


def format_for_telegram(result: dict[str, str | None]) -> str:
    """Основной анализ через LLM."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text") or ""

    if error:
        return f"❌ Не удалось выполнить анализ по {ticker}: {error}"
    if not analysis_text:
        return f"❌ Нет данных по {ticker}."

    llm_result = build_llm_full_analysis(ticker, analysis_text)
    return llm_result + DISCLAIMER


def format_news_for_telegram(result: dict[str, str | None]) -> str:
    """Новостной анализ через LLM."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text") or ""

    if error:
        return f"❌ Не удалось получить новости по {ticker}: {error}"
    if not analysis_text:
        return f"❌ Нет данных по {ticker}."

    llm_result = build_llm_news_analysis(ticker, analysis_text)
    return llm_result + DISCLAIMER


def format_risks_for_telegram(result: dict[str, str | None]) -> str:
    """Анализ рисков через LLM."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text") or ""

    if error:
        return f"❌ Не удалось получить риски по {ticker}: {error}"
    if not analysis_text:
        return f"❌ Нет данных по {ticker}."

    llm_result = build_llm_risks_analysis(ticker, analysis_text)
    return llm_result + DISCLAIMER


def format_idea_for_telegram(result: dict[str, str | None]) -> str:
    """Торговая идея через LLM."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text") or ""

    if error:
        return f"❌ Не удалось построить идею по {ticker}: {error}"
    if not analysis_text:
        return f"❌ Нет данных по {ticker}."

    llm_result = build_llm_idea(ticker, analysis_text)
    return llm_result + DISCLAIMER


def format_full_for_telegram(result: dict[str, str | None]) -> str:
    """Полный разбор через LLM."""

    return format_for_telegram(result)


def build_today_ideas_message() -> str:
    """Идеи дня через LLM для нескольких тикеров."""

    tickers = ["SBER", "LKOH", "GAZP", "VTBR", "ROSN"]
    tickers_data = []

    for ticker in tickers:
        try:
            result = analyze_ticker(ticker)
            tickers_data.append({
                "ticker": ticker,
                "raw_analysis": result.get("analysis_text") or "",
            })
        except Exception as e:
            tickers_data.append({
                "ticker": ticker,
                "raw_analysis": f"Ошибка: {e}",
            })

    return build_llm_today_ideas(tickers_data) + DISCLAIMER


# ─────────────────────────────────────────────
#  Сборка сырых данных (не менялась)
# ─────────────────────────────────────────────

def build_stock_analysis(ticker: str) -> str:
    """Формирует простой русскоязычный анализ по тикеру."""

    stock_data = get_stock_snapshot(ticker)

    if not stock_data["found"]:
        return stock_data["message"]

    news_summary = get_company_news_summary(ticker, stock_data)
    portfolio_context = get_portfolio_context(ticker)

    short_summary = _build_short_summary(stock_data)
    price_dynamics = _build_price_dynamics_block(stock_data)
    growth_drivers = _build_growth_drivers(stock_data, news_summary)
    risks = _build_risks(stock_data, news_summary)
    neutral_conclusion = _build_neutral_conclusion(stock_data, portfolio_context)
    news_block = _build_news_block(news_summary)
    notes = stock_data.get("notes", [])

    result = [
        f"Кратко по бумаге: {short_summary}",
        "",
    ]

    if price_dynamics:
        result.extend(
            [
                "Динамика:",
                *[f"- {item}" for item in price_dynamics],
                "",
            ]
        )

    result.extend(
        [
            "Новостной фон:",
            *[f"- {item}" for item in news_block],
            "",
            "Возможные драйверы роста:",
            *[f"- {item}" for item in growth_drivers],
            "",
            "Риски:",
            *[f"- {item}" for item in risks],
            "",
            f"Нейтральный вывод: {neutral_conclusion}",
        ]
    )

    if notes:
        result.extend(
            [
                "",
                "Примечания:",
                *[f"- {item}" for item in notes],
            ]
        )

    return "\n".join(result)


def _build_short_summary(stock_data: dict) -> str:
    """Собирает короткое описание бумаги на основе рыночных данных."""

    security_name = stock_data.get("full_name") or stock_data.get("short_name") or stock_data["ticker"]
    description = stock_data.get("description") or "MOEX ISS API не вернул отдельное описание бумаги."

    if stock_data.get("price") is None:
        price_part = "MOEX нашёл бумагу, но актуальная цена сейчас недоступна."
    else:
        price_part = (
            f"Актуальная цена на MOEX: {stock_data['price']:.2f} {stock_data.get('currency') or 'RUB'} "
            f"(источник цены: {stock_data.get('price_source') or 'не указан'})."
        )

    if stock_data.get("sector"):
        sector_part = f"Сектор по данным MOEX: {stock_data['sector']}."
    else:
        sector_part = "Сектор: MOEX ISS API не вернул данные по сектору."

    board_part = ""
    if stock_data.get("board_id"):
        board_part = f" Основной режим торгов: {stock_data['board_id']}."

    return f"{security_name}. {description} {price_part} {sector_part}{board_part}"


def _build_price_dynamics_block(stock_data: dict) -> list[str]:
    """Formats raw price-dynamics data into short text lines for the analysis."""

    items: list[str] = []

    for item in stock_data.get("price_dynamics", []):
        label = item.get("label")
        change_pct = item.get("change_pct")

        if not label or change_pct is None:
            continue

        items.append(f"{label}: {_format_signed_percent(change_pct)}")

    return items


def _format_signed_percent(value: float) -> str:
    """Formats percentage changes with a sign and a sensible precision."""

    precision = 2 if 0 < abs(value) < 0.1 else 1
    return f"{value:+.{precision}f}%"


def _build_growth_drivers(stock_data: dict, news_summary: dict) -> list[str]:
    """Возвращает список возможных драйверов роста."""

    drivers = []
    has_relevant_news = news_summary.get("available") and news_summary.get("relevant_items_available")

    if stock_data.get("listing_level"):
        drivers.append(
            f"Бумага находится в {stock_data['listing_level']}-м уровне листинга MOEX, "
            "что помогает быстро проверить ее базовый биржевой статус."
        )

    if stock_data.get("trading_status") == "T":
        drivers.append(
            "По бумаге есть активный торговый статус на MOEX, поэтому инвестор видит живую биржевую котировку."
        )
    else:
        drivers.append(
            "Перед решением полезно отдельно проверить ликвидность и текущий режим торгов на MOEX."
        )

    if has_relevant_news and news_summary.get("significant_items_count"):
        drivers.append(
            "В ленте есть инвестиционно значимые заголовки, которые стоит отдельно проверить по первоисточникам."
        )

    if has_relevant_news and news_summary.get("sentiment") == "positive":
        drivers.append(
            "По более релевантным заголовкам новостной фон выглядит умеренно позитивным."
        )

    if has_relevant_news and news_summary.get("sentiment") == "mixed":
        drivers.append(
            "В более релевантных новостях есть и сильные, и осторожные сигналы, "
            "поэтому стоит смотреть не только на один заголовок, а на весь фон."
        )

    return drivers


def _build_risks(stock_data: dict, news_summary: dict) -> list[str]:
    """Возвращает базовые риски."""

    risks = [
        "Котировка MOEX показывает рыночную цену, но сама по себе не заменяет анализ отчетности компании.",
        "Цена акции может быстро меняться в течение торговой сессии.",
    ]
    has_relevant_news = news_summary.get("available") and news_summary.get("relevant_items_available")

    if not stock_data.get("sector"):
        risks.append("Отраслевые риски раскрыты не полностью, потому что MOEX ISS API не вернул сектор.")

    if not news_summary.get("available"):
        risks.append("Свежие новости по компании не удалось получить, поэтому анализ новостного фона сейчас неполный.")

    if news_summary.get("available") and news_summary.get("all_items_weak"):
        risks.append(
            "Свежие публикации нашлись, но по заголовкам они выглядят слабо релевантными для инвестиционного анализа."
        )

    if has_relevant_news and news_summary.get("sentiment") == "negative":
        risks.append("По более релевантным заголовкам новостной фон выглядит умеренно негативным.")

    if has_relevant_news and news_summary.get("sentiment") == "mixed":
        risks.append(
            "Новостной фон выглядит смешанным: в публикациях могут одновременно встречаться "
            "и позитивные, и негативные сигналы."
        )

    return risks


def _build_neutral_conclusion(stock_data: dict, portfolio_context: dict) -> str:
    """Собирает нейтральный вывод с учетом портфельного контекста."""

    return (
        f"По {stock_data['ticker']} сейчас можно получить реальную цену и карточку бумаги с MOEX, "
        "но для полноценного решения все еще стоит проверить отчетность, новости и место бумаги в портфеле. "
        f"{portfolio_context['note']}"
    )


def _build_news_block(news_summary: dict) -> list[str]:
    """Собирает отдельный блок по новостям для CLI-ответа."""

    if not news_summary.get("available"):
        return [news_summary["summary"]]

    lines = [news_summary["summary"]]

    for item in news_summary.get("items", []):
        date_prefix = f"{item['published_at']} - " if item.get("published_at") else ""
        source_suffix = f" ({item['source']})" if item.get("source") else ""
        relevance_prefix = f"[{item.get('relevance_label_ru', 'нейтральная')}]"
        issuer_prefix = ""
        topics_suffix = ""

        if item.get("issuer_match_label_ru"):
            issuer_prefix = f"[{item['issuer_match_label_ru']}]"

        if item.get("topics"):
            topics_suffix = f" — темы: {', '.join(item['topics'])}"

        lines.append(
            f"{relevance_prefix}{issuer_prefix} {date_prefix}{item['title']}{source_suffix}{topics_suffix}"
        )

    return lines


if __name__ == "__main__":
    import sys

    ticker = "SBER"

    if len(sys.argv) > 1:
        ticker = sys.argv[1]

    print(f"Запуск анализа для {ticker}")
    result = build_stock_analysis(ticker)
    print(result)
