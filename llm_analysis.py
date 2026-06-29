from __future__ import annotations

import os
import urllib.request
import urllib.error
import json


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key={key}"
)

ANALYST_SYSTEM_PROMPT = """Ты — опытный российский инвестиционный аналитик с 15-летним стажем торговли на MOEX.
Твоя задача — давать чёткий, конкретный анализ акций который помогает зарабатывать деньги.

Правила:
- Пиши как профессионал, не как робот
- Давай конкретные выводы, не уходи от ответа
- Указывай реальные риски честно
- Используй данные которые тебе дали — цену, динамику, новости
- Не пиши "не является инвестиционной рекомендацией" внутри анализа — это будет добавлено отдельно
- Пиши кратко и по делу, без воды
- Используй эмодзи умеренно для читаемости"""


def _call_gemini(prompt: str) -> str:
    """Makes a request to Gemini API and returns the response text."""
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY не задан в переменных окружения."

    url = GEMINI_API_URL.format(key=GEMINI_API_KEY)
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
        }
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return (
                result["candidates"][0]["content"]["parts"][0]["text"]
                .strip()
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return f"❌ Ошибка Gemini API ({e.code}): {body[:200]}"
    except Exception as e:
        return f"❌ Ошибка запроса к Gemini: {e}"


def build_llm_full_analysis(ticker: str, raw_analysis: str) -> str:
    """Full analysis — price, news, drivers, risks, verdict."""
    prompt = f"""{ANALYST_SYSTEM_PROMPT}

Вот сырые данные по акции {ticker} с MOEX и Google News:

{raw_analysis}

Напиши полный анализ в формате:

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
• Краткосрок (1-2 нед): [вывод]
• Среднесрок (1-3 мес): [вывод]
• Долгосрок (от 6 мес): [вывод]"""

    return _call_gemini(prompt)


def build_llm_news_analysis(ticker: str, raw_analysis: str) -> str:
    """News-focused analysis."""
    prompt = f"""{ANALYST_SYSTEM_PROMPT}

Данные по акции {ticker}:

{raw_analysis}

Напиши новостной разбор в формате:

{ticker} — новостной фон

📰 Ключевые новости:
[топ-3 новости которые реально важны для инвестора, объясни почему каждая важна]

📈 Как новости влияют на цену:
[конкретно — позитив или негатив и почему]

👁 На что смотреть дальше:
[какие события/новости ждать в ближайшее время по этой бумаге]"""

    return _call_gemini(prompt)


def build_llm_risks_analysis(ticker: str, raw_analysis: str) -> str:
    """Risk-focused analysis."""
    prompt = f"""{ANALYST_SYSTEM_PROMPT}

Данные по акции {ticker}:

{raw_analysis}

Напиши разбор рисков в формате:

{ticker} — риски

🔴 Главный риск:
[самый важный риск прямо сейчас и его влияние на цену]

⚠️ Другие риски:
[2-3 реальных риска с объяснением]

🛡 Что снижает риски:
[факторы которые защищают позицию]

📉 Сценарий падения:
[при каких условиях цена может упасть и насколько]"""

    return _call_gemini(prompt)


def build_llm_idea(ticker: str, raw_analysis: str) -> str:
    """Trade idea — entry, target, stop."""
    prompt = f"""{ANALYST_SYSTEM_PROMPT}

Данные по акции {ticker}:

{raw_analysis}

Напиши торговую идею в формате:

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

    return _call_gemini(prompt)


def build_llm_today_ideas(tickers_data: list[dict]) -> str:
    """Ideas of the day for multiple tickers."""
    summaries = []
    for item in tickers_data:
        ticker = item.get("ticker", "")
        raw = item.get("raw_analysis", "")
        # Берём только первые 800 символов чтобы не раздувать промпт
        short_raw = raw[:800] if raw else "Данные недоступны"
        summaries.append(f"=== {ticker} ===\n{short_raw}")

    combined = "\n\n".join(summaries)

    prompt = f"""{ANALYST_SYSTEM_PROMPT}

Вот данные по нескольким акциям MOEX:

{combined}

Напиши краткий дайджест "Идеи дня" в формате:

📈 Идеи дня

Для каждой акции одним блоком:

[ТИКЕР] — [одна строка: суть ситуации]
💰 Цена: [цена и динамика за день]
🎯 Идея: [конкретно что делать и почему]
⚡️ Риск: [главный риск одной строкой]

В конце:
🏆 Лучшая идея дня: [тикер и почему именно он]"""

    return _call_gemini(prompt)
