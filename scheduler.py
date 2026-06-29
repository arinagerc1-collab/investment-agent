"""Morning digest scheduler — sends daily ideas at 09:00 Moscow time."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import urllib.request
import urllib.error


# Moscow timezone offset = UTC+5
MOSCOW_UTC_OFFSET = 5

# Время рассылки — 09:00 по Москве
SEND_HOUR_MOSCOW = 9
SEND_MINUTE = 0

# Твой Telegram ID — сюда придёт утренняя рассылка
SUBSCRIBER_IDS = [
    1727749857,
]

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def _now_moscow() -> datetime.datetime:
    """Returns current time in Moscow timezone."""
    utc_now = datetime.datetime.utcnow()
    return utc_now + datetime.timedelta(hours=MOSCOW_UTC_OFFSET)


def _seconds_until_next_send() -> float:
    """Calculates seconds until next 09:00 Moscow time."""
    now = _now_moscow()
    target = now.replace(
        hour=SEND_HOUR_MOSCOW,
        minute=SEND_MINUTE,
        second=0,
        microsecond=0,
    )

    if now >= target:
        target += datetime.timedelta(days=1)

    delta = target - now
    return delta.total_seconds()


def _build_affirmation() -> str:
    """Generates a daily affirmation in the style of The Secret via DeepSeek."""
    if not DEEPSEEK_API_KEY:
        return "✨ Вселенная уже готовит для тебя лучшее. Просто доверяй процессу."

    today = _now_moscow().strftime("%d.%m.%Y")

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — вдохновляющий коуч в стиле книги и фильма Тайна (The Secret). "
                    "Ты веришь в закон притяжения, силу мысли и то что вселенная отвечает на наши желания. "
                    "Пиши тепло, с верой и энергией. Без markdown, только обычный текст и эмодзи."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Напиши одну уникальную аффирмацию на сегодня {today} "
                    "для мужчины который инвестирует деньги и строит финансовую свободу. "
                    "В стиле Тайны — про притяжение богатства, изобилие, силу намерения. "
                    "2-3 предложения максимум. Начни с обращения "Сегодня". Обращайся в мужском роде — "ты готов", "ты притягиваешь", "твои мысли"."
                ),
            },
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
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except Exception:
        return "✨ Сегодня вселенная работает на тебя. Твои мысли о богатстве притягивают изобилие прямо сейчас."


async def send_morning_digest(bot) -> None:
    """Builds and sends morning digest with affirmation to all subscribers."""
    from agent import build_today_ideas_message

    now = _now_moscow()
    date_str = now.strftime("%d.%m.%Y")

    # Аффирмация
    affirmation = _build_affirmation()

    # Идеи дня
    try:
        ideas = build_today_ideas_message()
    except Exception as e:
        ideas = f"❌ Не удалось собрать идеи дня: {e}"

    full_text = (
        f"🌅 Доброе утро! {date_str}\n\n"
        f"✨ Аффирмация дня:\n{affirmation}\n\n"
        f"{'─' * 20}\n\n"
        f"{ideas}"
    )

    for user_id in SUBSCRIBER_IDS:
        try:
            await bot.send_message(user_id, full_text)
        except Exception as e:
            print(f"Ошибка отправки дайджеста пользователю {user_id}: {e}")


async def run_morning_scheduler(bot) -> None:
    """Infinite loop — waits until 09:00 Moscow and sends digest."""
    print("📅 Планировщик утренней рассылки запущен.")

    while True:
        seconds = _seconds_until_next_send()
        now_moscow = _now_moscow()
        send_at = now_moscow + datetime.timedelta(seconds=seconds)

        print(
            f"⏰ Следующая рассылка в {send_at.strftime('%d.%m.%Y %H:%M')} по Москве "
            f"(через {int(seconds // 3600)}ч {int((seconds % 3600) // 60)}мин)"
        )

        await asyncio.sleep(seconds)
        await send_morning_digest(bot)

        # Пауза 60 секунд чтобы не отправить дважды
        await asyncio.sleep(60)
