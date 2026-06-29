"""Morning digest scheduler — sends daily ideas at 09:00 Perm time."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import urllib.request


# Perm timezone offset = UTC+5
PERM_UTC_OFFSET = 5

SEND_HOUR = 9
SEND_MINUTE = 0

SUBSCRIBER_IDS = [
    1727749857,
]

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def _now_perm() -> datetime.datetime:
    utc_now = datetime.datetime.utcnow()
    return utc_now + datetime.timedelta(hours=PERM_UTC_OFFSET)


def _seconds_until_next_send() -> float:
    now = _now_perm()
    target = now.replace(hour=SEND_HOUR, minute=SEND_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def _build_affirmation() -> str:
    if not DEEPSEEK_API_KEY:
        return "Сегодня ты притягиваешь изобилие своей уверенностью. Вселенная уже движется тебе навстречу."

    today = _now_perm().strftime("%d.%m.%Y")

    system_text = (
        "Ты — вдохновляющий коуч в стиле книги и фильма Тайна (The Secret). "
        "Ты веришь в закон притяжения, силу мысли и то что вселенная отвечает на наши желания. "
        "Пиши тепло, с верой и энергией. Без markdown, только обычный текст и эмодзи."
    )

    user_text = (
        "Напиши одну уникальную аффирмацию на сегодня " + today + " "
        "для мужчины который инвестирует деньги и строит финансовую свободу. "
        "В стиле Тайны — про притяжение богатства, изобилие, силу намерения. "
        "Обращайся в мужском роде — ты готов, ты притягиваешь, твои мысли. "
        "2-3 предложения максимум. Начни с обращения Сегодня."
    )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.9,
        "max_tokens": 150,
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
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except Exception:
        return "Сегодня ты притягиваешь изобилие своей уверенностью. Вселенная уже движется тебе навстречу."


async def send_morning_digest(bot) -> None:
    from agent import build_today_ideas_message

    now = _now_perm()
    date_str = now.strftime("%d.%m.%Y")
    affirmation = _build_affirmation()

    try:
        ideas = build_today_ideas_message()
    except Exception as e:
        ideas = "Не удалось собрать идеи дня: " + str(e)

    full_text = (
        "🌅 Доброе утро! " + date_str + "\n\n"
        "✨ Аффирмация дня:\n" + affirmation + "\n\n"
        "────────────────────\n\n"
        + ideas
    )

    for user_id in SUBSCRIBER_IDS:
        try:
            await bot.send_message(user_id, full_text)
        except Exception as e:
            print("Ошибка отправки дайджеста пользователю " + str(user_id) + ": " + str(e))


async def run_morning_scheduler(bot) -> None:
    print("Планировщик утренней рассылки запущен.")

    while True:
        seconds = _seconds_until_next_send()
        now_perm = _now_perm()
        send_at = now_perm + datetime.timedelta(seconds=seconds)
        print(
            "Следующая рассылка в "
            + send_at.strftime("%d.%m.%Y %H:%M")
            + " по Перми"
        )
        await asyncio.sleep(seconds)
        await send_morning_digest(bot)
        await asyncio.sleep(60)
