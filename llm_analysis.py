"""LLM-powered investment analysis using DeepSeek API."""

from __future__ import annotations

import os
import urllib.request
import urllib.error
import json


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

ANALYST_SYSTEM_PROMPT = """Ты — опытный российский инвестиционный аналитик с 15-летним стажем торговли на MOEX.
Твоя задача — давать чёткий, конкретный анализ акций который помогает зарабатывать деньги.

Правила форматирования — очень важно:
- НЕ используй markdown: никаких **, *, ##, __, []()
- Пиши обычным текстом
- Эмодзи можно использовать умеренно
- Каждый раздел с новой строки
- Пиши как профессионал, не как робот
- Давай конкретные выводы, не уходи от ответа
- Указывай реальные риски честно
- Используй данные которые тебе дали — цену, динамику, новости и мультипликаторы
- Не пиши "не является инвестиционной рекомендацией" внутри анализа"""


def _call_deepseek(prompt: str) -> str:
    """Makes a request to DeepSeek API and returns the response text."""
    if not DEEPSEEK_API_KEY:
        return "❌ DEEPSEEK_API_KEY не задан в переменных окружения."

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + DEEPSEEK_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return "❌ Ошибка DeepSeek API (" + str(e.code) + "): " + body[:200]
    except Exception as e:
        return "❌ Ошибка запроса к DeepSeek: " + str(e)


def _get_fundamentals_block(ticker: str) -> str:
    """Tries to get fundamentals from Smart-Lab, returns empty string on error."""
    try:
        from fundamentals import format_fundamentals_for_prompt
        return format_fundamentals_for_prompt(ticker)
    except Exception:
        return ""


def build_llm_full_analysis(ticker: str, raw_analysis: str) -> str:
    """Full analysis with fundamentals."""
    fundamentals = _get_fundamentals_block(ticker)
    fund_block = ("\n\n" + fundamentals) if fundamentals else ""

    prompt = (
        "Данные по акции " + ticker + " с MOEX и Google News:\n\n"
        + raw_analysis
        + fund_block
        + "\n\nНапиши полный анализ. Без markdown, только обычный текст и эмодзи.\n\n"
        + ticker + " — разбор аналитика\n\n"
        "💰 Цена и динамика:\n"
        "[цена, изменение за день/неделю, оцени momentum]\n\n"
        "📊 Мультипликаторы:\n"
        "[оцени P/E, P/BV, дивдоходность — дорого или дёшево относительно рынка]\n\n"
        "📰 Что происходит:\n"
        "[2-3 ключевых события из новостей которые реально влияют на цену]\n\n"
        "🚀 Драйверы роста:\n"
        "[конкретные факторы которые могут поднять цену]\n\n"
        "⚠️ Риски:\n"
        "[реальные риски, не общие слова]\n\n"
        "🎯 Вывод:\n"
        "[конкретный вывод: держать/смотреть/избегать и почему]\n\n"
        "📊 Горизонт:\n"
        "• Краткосрок (1-2 нед): [вывод и уровень цены]\n"
        "• Среднесрок (1-3 мес): [вывод и уровень цены]\n"
        "• Долгосрок (от 6 мес): [вывод и уровень цены]"
    )
    return _call_deepseek(prompt)


def build_llm_news_analysis(ticker: str, raw_analysis: str) -> str:
    """News-focused analysis."""
    prompt = (
        "Данные по акции " + ticker + ":\n\n"
        + raw_analysis
        + "\n\nНапиши новостной разбор. Без markdown, только обычный текст и эмодзи.\n\n"
        + ticker + " — новостной фон\n\n"
        "📰 Ключевые новости:\n"
        "[топ-3 новости которые реально важны для инвестора, объясни почему каждая важна]\n\n"
        "📈 Как новости влияют на цену:\n"
        "[конкретно — позитив или негатив и почему]\n\n"
        "👁 На что смотреть дальше:\n"
        "[какие события/новости ждать в ближайшее время по этой бумаге]"
    )
    return _call_deepseek(prompt)


def build_llm_risks_analysis(ticker: str, raw_analysis: str) -> str:
    """Risk-focused analysis."""
    fundamentals = _get_fundamentals_block(ticker)
    fund_block = ("\n\n" + fundamentals) if fundamentals else ""

    prompt = (
        "Данные по акции " + ticker + ":\n\n"
        + raw_analysis
        + fund_block
        + "\n\nНапиши разбор рисков. Без markdown, только обычный текст и эмодзи.\n\n"
        + ticker + " — риски\n\n"
        "🔴 Главный риск:\n"
        "[самый важный риск прямо сейчас и его влияние на цену]\n\n"
        "⚠️ Другие риски:\n"
        "[2-3 реальных риска с объяснением]\n\n"
        "🛡 Что снижает риски:\n"
        "[факторы которые защищают позицию]\n\n"
        "📉 Сценарий падения:\n"
        "[при каких условиях цена может упасть и насколько]"
    )
    return _call_deepseek(prompt)


def build_llm_idea(ticker: str, raw_analysis: str) -> str:
    """Trade idea with fundamentals."""
    fundamentals = _get_fundamentals_block(ticker)
    fund_block = ("\n\n" + fundamentals) if fundamentals else ""

    prompt = (
        "Данные по акции " + ticker + ":\n\n"
        + raw_analysis
        + fund_block
        + "\n\nНапиши торговую идею. Без markdown, только обычный текст и эмодзи.\n\n"
        + ticker + " — идея\n\n"
        "💡 Суть идеи:\n"
        "[1-2 предложения — в чём идея]\n\n"
        "📊 Параметры:\n"
        "• Текущая цена: [цена]\n"
        "• Потенциал роста: [% или уровень цены]\n"
        "• Горизонт: [срок]\n"
        "• Риск/доходность: [оценка]\n\n"
        "✅ Почему интересно:\n"
        "[2-3 конкретных аргумента включая мультипликаторы если есть]\n\n"
        "❌ Когда идея не работает:\n"
        "[условия при которых идея отменяется]\n\n"
        "🎯 Вывод: [одна чёткая рекомендация]"
    )
    return _call_deepseek(prompt)


def build_llm_today_ideas(tickers_data: list[dict]) -> str:
    """Ideas of the day for multiple tickers."""
    summaries = []
    for item in tickers_data:
        ticker = item.get("ticker", "")
        raw = item.get("raw_analysis", "")
        short_raw = raw[:600] if raw else "Данные недоступны"

        # Пробуем добавить мультипликаторы
        fundamentals = _get_fundamentals_block(ticker)
        if fundamentals:
            short_raw = short_raw + "\n\n" + fundamentals

        summaries.append("=== " + ticker + " ===\n" + short_raw)

    combined = "\n\n".join(summaries)

    prompt = (
        "Данные по нескольким акциям MOEX:\n\n"
        + combined
        + "\n\nНапиши дайджест идей дня. Без markdown, только обычный текст и эмодзи.\n\n"
        "📈 Идеи дня\n\n"
        "Для каждой акции:\n\n"
        "[ТИКЕР] — [одна строка: суть ситуации]\n"
        "💰 Цена: [цена и динамика за день]\n"
        "🎯 Идея: [конкретно что делать и почему]\n"
        "⚡ Риск: [главный риск одной строкой]\n\n"
        "В конце:\n"
        "🏆 Лучшая идея дня: [тикер и почему именно он]"
    )
    return _call_deepseek(prompt)
