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
- Используй данные которые тебе дали — цену, динамику, новости
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
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return f"❌ Ошибка DeepSeek API ({e.code}): {body[:200]}"
    except Exception as e:
        return f"❌ Ошибка запроса к DeepSeek: {e}"


def build_llm_full_analysis(ticker: str, raw_analysis: str) -> str:
    """Full analysis."""
    prompt = f"""Данные по акции {ticker} с MOEX и Google News:

{raw_analysis}

Напиши анализ. Без markdown, только обычный текст и эмодзи.

{ticker} — разбор аналитика

💰 Цена и динамика:
[цена, изменение за день/неделю, оцени momentum]

📰 Что происходит:
[2-3 ключевых события из новостей которые реально влияют на цену]

🚀 Драйверы роста:
[конкретные факторы которые могут поднять цену]

⚠️ Риски:
[реальные риски, не общие слова]

🎯 Вывод:
[конкретный вывод: держать/смотреть/избегать и почему]

📊 Горизонт:
• Краткосрок (1-2 нед): [вывод и уровень цены]
• Среднесрок (1-3 мес): [вывод и уровень цены]
• Долгосрок (от 6 мес): [вывод и уровень цены]"""

    return _call_deepseek(prompt)


def build_llm_news_analysis(ticker: str, raw_analysis: str) -> str:
    """News-focused analysis."""
    prompt = f"""Данные по акции {ticker}:

{raw_analysis}

Напиши новостной разбор. Без markdown, только обычный текст и эмодзи.

{ticker} — новостной фон

📰 Ключевые новости:
[топ-3 новости которые реально важны для инвестора, объясни почему каждая важна]

📈 Как новости влияют на цену:
[конкретно — позитив или негатив и почему]

👁 На что смотреть дальше:
[какие события/новости ждать в ближайшее время по этой бумаге]"""

    return _call_deepseek(prompt)


def build_llm_risks_analysis(ticker: str, raw_analysis: str) -> str:
    """Risk-focused analysis."""
    prompt = f"""Данные по акции {ticker}:

{raw_analysis}

Напиши разбор рисков. Без markdown, только обычный текст и эмодзи.

{ticker} — риски

🔴 Главный риск:
[самый важный риск прямо сейчас и его влияние на цену]

⚠️ Другие риски:
[2-3 реальных риска с объяснением]

🛡 Что снижает риски:
[факторы которые защищают позицию]

📉 Сценарий падения:
[при каких условиях цена может упасть и насколько]"""

    return _call_deepseek(prompt)


def build_llm_idea(ticker: str, raw_analysis: str) -> str:
    """Trade idea."""
    prompt = f"""Данные по акции {ticker}:

{raw_analysis}

Напиши торговую идею. Без markdown, только обычный текст и эмодзи.

{ticker} — идея

💡 Суть идеи:
[1-2 предложения — в чём идея]

📊 Параметры:
• Текущая цена: [цена]
• Потенциал роста: [% или уровень цены]
• Горизонт: [срок]
• Риск/доходность: [оценка]

✅ Почему интересно:
[2-3 конкретных аргумента]

❌ Когда идея не работает:
[условия при которых идея отменяется]

🎯 Вывод: [одна чёткая рекомендация]"""

    return _call_deepseek(prompt)


def build_llm_today_ideas(tickers_data: list[dict]) -> str:
    """Ideas of the day for multiple tickers."""
    summaries = []
    for item in tickers_data:
        ticker = item.get("ticker", "")
        raw = item.get("raw_analysis", "")
        short_raw = raw[:800] if raw else "Данные недоступны"
        summaries.append(f"=== {ticker} ===\n{short_raw}")

    combined = "\n\n".join(summaries)

    prompt = f"""Данные по нескольким акциям MOEX:

{combined}

Напиши дайджест идей дня. Без markdown, только обычный текст и эмодзи.

📈 Идеи дня

Для каждой акции:

[ТИКЕР] — [одна строка: суть ситуации]
💰 Цена: [цена и динамика за день]
🎯 Идея: [конкретно что делать и почему]
⚡ Риск: [главный риск одной строкой]

В конце:
🏆 Лучшая идея дня: [тикер и почему именно он]"""

    return _call_deepseek(prompt)
