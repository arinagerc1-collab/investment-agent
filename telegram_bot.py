"""Minimal Telegram bot for the investment-agent MVP."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from agent import (
    analyze_ticker,
    format_for_telegram,
    format_news_for_telegram,
    format_risks_for_telegram,
    format_idea_for_telegram,
    format_full_for_telegram,
    normalize_user_ticker_input,
    build_today_ideas_message,
)

router = Router()

pending_actions_by_user: dict[int, str] = {}

action_formatters: dict[str, Callable[[dict[str, str | None]], str]] = {
    "news": format_news_for_telegram,
    "risks": format_risks_for_telegram,
    "idea": format_idea_for_telegram,
    "full": format_full_for_telegram,
}


def get_telegram_bot_token() -> str:
    """Reads Telegram bot token from env."""

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        raise SystemExit(
            "Переменная TELEGRAM_BOT_TOKEN не задана."
        )

    return token


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Creates reply keyboard."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Анализ"),
                KeyboardButton(text="📰 Новости"),
            ],
            [
                KeyboardButton(text="⚠️ Риски"),
                KeyboardButton(text="💡 Идея"),
            ],
            [
                KeyboardButton(text="📈 Идеи дня"),
            ],
        ],
        resize_keyboard=True,
    )


def extract_message_text(message: Message) -> str:
    """Extracts message text."""

    return (message.text or "").strip()


def extract_command_argument(message: Message) -> str:
    """Extracts command argument."""

    text = extract_message_text(message)
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return ""

    return parts[1].strip()


def get_message_user_id(message: Message) -> int | None:
    """Returns Telegram user id."""

    if message.from_user is None:
        return None

    return message.from_user.id


def set_pending_action(message: Message, action: str) -> None:
    """Stores pending action."""

    user_id = get_message_user_id(message)

    if user_id is None:
        return

    pending_actions_by_user[user_id] = action


def get_pending_action(message: Message) -> str | None:
    """Returns pending action."""

    user_id = get_message_user_id(message)

    if user_id is None:
        return None

    return pending_actions_by_user.get(user_id)


def clear_pending_action(message: Message) -> None:
    """Clears pending action."""

    user_id = get_message_user_id(message)

    if user_id is None:
        return

    pending_actions_by_user.pop(user_id, None)


async def _handle_command_analysis_request(
    message: Message,
    raw_ticker: str,
    formatter,
) -> None:
    """Handles analysis request."""

    await message.answer("Смотрю данные по бумаге, секунду...")

    try:
        normalized_ticker = normalize_user_ticker_input(raw_ticker)
        result = analyze_ticker(normalized_ticker)
        reply = formatter(result)
    except Exception as error:
        reply = f"Не удалось обработать запрос: {error}"

    await message.answer(reply)


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handles /start."""

    await message.answer(
        "Привет! Я бот для анализа акций 📊\n\n"
        "Что я умею:\n"
        "• анализировать акции\n"
        "• показывать новости\n"
        "• показывать риски\n"
        "• давать краткие идеи\n\n"
        "Просто отправь тикер:\n"
        "SBER\n\n"
        "Или используй команды:\n"
        "/news SBER\n"
        "/risks SBER\n"
        "/idea SBER\n"
        "/full SBER\n"
        "/today",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Handles /help."""

    await message.answer(
        "Команды:\n\n"
        "/news SBER — новости\n"
        "/risks SBER — риски\n"
        "/idea SBER — идея\n"
        "/full SBER — полный разбор\n"
        "/today — идеи дня",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(F.text == "📊 Анализ")
async def handle_analysis_button(message: Message) -> None:
    """Handles analysis button."""

    clear_pending_action(message)
    await message.answer("Напишите тикер, например: SBER")


@router.message(F.text == "📰 Новости")
async def handle_news_button(message: Message) -> None:
    """Handles news button."""

    set_pending_action(message, "news")
    await message.answer("Напишите тикер для новостей, например: SBER")


@router.message(F.text == "⚠️ Риски")
async def handle_risks_button(message: Message) -> None:
    """Handles risks button."""

    set_pending_action(message, "risks")
    await message.answer("Напишите тикер для анализа рисков, например: SBER")


@router.message(F.text == "💡 Идея")
async def handle_idea_button(message: Message) -> None:
    """Handles idea button."""

    set_pending_action(message, "idea")
    await message.answer("Напишите тикер для идеи, например: SBER")


@router.message(F.text == "📈 Идеи дня")
async def handle_today_button(message: Message) -> None:
    """Handles ideas button."""

    clear_pending_action(message)
    await message.answer("Смотрю идеи дня по списку бумаг...")

    try:
        reply = build_today_ideas_message()
    except Exception as error:
        reply = f"Ошибка: {error}"

    await message.answer(reply)


@router.message(Command("news"))
async def handle_news_command(message: Message) -> None:
    """Handles /news."""

    raw_ticker = extract_command_argument(message)

    if not raw_ticker:
        set_pending_action(message, "news")
        await message.answer("Напишите тикер после /news")
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(
        message, raw_ticker, format_news_for_telegram,
    )


@router.message(Command("risks"))
async def handle_risks_command(message: Message) -> None:
    """Handles /risks."""

    raw_ticker = extract_command_argument(message)

    if not raw_ticker:
        set_pending_action(message, "risks")
        await message.answer("Напишите тикер после /risks")
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(
        message, raw_ticker, format_risks_for_telegram,
    )


@router.message(Command("idea"))
async def handle_idea_command(message: Message) -> None:
    """Handles /idea."""

    raw_ticker = extract_command_argument(message)

    if not raw_ticker:
        set_pending_action(message, "idea")
        await message.answer("Напишите тикер после /idea")
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(
        message, raw_ticker, format_idea_for_telegram,
    )


@router.message(Command("full"))
async def handle_full_command(message: Message) -> None:
    """Handles /full."""

    raw_ticker = extract_command_argument(message)

    if not raw_ticker:
        set_pending_action(message, "full")
        await message.answer("Напишите тикер после /full")
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(
        message, raw_ticker, format_full_for_telegram,
    )


@router.message(Command("today"))
async def handle_today_command(message: Message) -> None:
    """Handles /today."""

    clear_pending_action(message)
    await message.answer("Смотрю идеи дня по списку бумаг...")

    try:
        reply = build_today_ideas_message()
    except Exception as error:
        reply = f"Ошибка: {error}"

    await message.answer(reply)


@router.message(Command("morning"))
async def handle_morning_command(message: Message) -> None:
    """Handles /morning — sends morning digest right now for testing."""
    from scheduler import send_morning_digest

    await message.answer("Отправляю утренний дайджест...")

    try:
        await send_morning_digest(message.bot)
    except Exception as error:
        await message.answer(f"Ошибка: {error}")


@router.message()
async def handle_ticker_message(message: Message) -> None:
    """Handles ticker message."""

    user_text = extract_message_text(message)

    if not user_text:
        await message.answer("Пожалуйста, отправьте тикер, например SBER.")
        return

    pending_action = get_pending_action(message)
    formatter = format_for_telegram

    if pending_action and pending_action in action_formatters:
        formatter = action_formatters[pending_action]

    await message.answer("Смотрю данные по бумаге, секунду...")

    try:
        normalized_ticker = normalize_user_ticker_input(user_text)
        result = analyze_ticker(normalized_ticker)
        reply = formatter(result)
    except Exception as error:
        reply = f"Не удалось обработать запрос: {error}"
    finally:
        if pending_action:
            clear_pending_action(message)

    await message.answer(reply)


async def main() -> None:
    """Starts bot polling and morning scheduler."""
    from scheduler import run_morning_scheduler

    bot = Bot(token=get_telegram_bot_token())
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    # Запускаем бота и планировщик параллельно
    await asyncio.gather(
        dispatcher.start_polling(bot),
        run_morning_scheduler(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
