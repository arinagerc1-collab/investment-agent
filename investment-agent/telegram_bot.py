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
    format_full_for_telegram,
    format_for_telegram,
    format_idea_for_telegram,
    format_news_for_telegram,
    format_risks_for_telegram,
    normalize_user_ticker_input,
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
    """Reads the Telegram bot token from environment variables."""

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        raise SystemExit(
            "Переменная окружения TELEGRAM_BOT_TOKEN не задана. "
            "Укажите токен бота перед запуском."
        )

    return token


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Builds the main reply keyboard for the bot."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Анализ"), KeyboardButton(text="📰 Новости")],
            [KeyboardButton(text="⚠️ Риски"), KeyboardButton(text="💡 Идея")],
        ],
        resize_keyboard=True,
    )


def extract_message_text(message: Message) -> str:
    """Extracts and trims plain user text from a Telegram message."""

    return (message.text or "").strip()


def extract_command_argument(message: Message) -> str:
    """Extracts the argument part that goes after a bot command."""

    text = extract_message_text(message)
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return ""

    return parts[1].strip()


def get_message_user_id(message: Message) -> int | None:
    """Returns the Telegram user id when it is available."""

    if message.from_user is None:
        return None

    return message.from_user.id


def set_pending_action(message: Message, action: str) -> None:
    """Stores the next expected action for the current user."""

    user_id = get_message_user_id(message)
    if user_id is None:
        return

    pending_actions_by_user[user_id] = action


def get_pending_action(message: Message) -> str | None:
    """Returns the pending action for the current user, if any."""

    user_id = get_message_user_id(message)
    if user_id is None:
        return None

    return pending_actions_by_user.get(user_id)


def clear_pending_action(message: Message) -> None:
    """Clears the pending action for the current user."""

    user_id = get_message_user_id(message)
    if user_id is None:
        return

    pending_actions_by_user.pop(user_id, None)


async def _handle_command_analysis_request(
    message: Message,
    raw_ticker: str,
    formatter,
) -> None:
    """Runs analysis for a command handler and sends the formatted response."""

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
    """Sends a short start instruction to the user."""

    await message.answer(
        "Привет! Я твой личный бот Владимир для анализа акций 📊\n\n"
        "Помогаю быстро понять, что сейчас происходит с бумагой без лишнего шума.\n\n"
        "Что я умею:\n"
        "• анализирую акции по тикеру или названию (SBER, сбер, gazp и т.д.)\n"
        "• показываю краткий разбор по бумаге\n"
        "• выделяю риски и ключевые новости\n"
        "• даю ориентир по горизонту: краткосрок / средний / долгий срок\n\n"
        "Что нового:\n"
        "• можно использовать команды без тикера (например, /idea → потом просто отправить SBER)\n"
        "• добавлены режимы:\n"
        "  /news — важные новости\n"
        "  /risks — риски по бумаге\n"
        "  /idea — краткая идея по бумаге\n\n"
        "Как пользоваться:\n"
        "Просто отправь тикер:\n"
        "SBER\n\n"
        "или используй команды:\n"
        "/news SBER\n"
        "/risks SBER\n"
        "/idea SBER\n\n"
        "Если есть идеи по улучшению — пиши @Arinocka_g",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Sends a short help message with available bot commands."""

    await message.answer(
        "Как пользоваться ботом:\n\n"
        "Отправьте тикер или название бумаги:\n"
        "SBER или сбер\n\n"
        "Доступные команды:\n"
        "/news SBER — важные новости\n"
        "/risks SBER — риски по бумаге\n"
        "/idea SBER — краткая идея\n"
        "/full SBER — подробный разбор\n\n"
        "Пример:\n"
        "/idea SBER\n\n"
        "Если есть идеи по улучшению — пишите @Arinocka_g",
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(F.text == "📊 Анализ")
async def handle_analysis_button(message: Message) -> None:
    """Prompts the user to send a ticker for the standard short analysis."""

    clear_pending_action(message)
    await message.answer(
        "Напишите тикер или название бумаги для краткого анализа, например: SBER или сбер"
    )


@router.message(F.text == "📰 Новости")
async def handle_news_button(message: Message) -> None:
    """Enables pending news mode from the reply keyboard."""

    set_pending_action(message, "news")
    await message.answer(
        "Напишите тикер или название бумаги для новостей, например: SBER или сбер"
    )


@router.message(F.text == "⚠️ Риски")
async def handle_risks_button(message: Message) -> None:
    """Enables pending risks mode from the reply keyboard."""

    set_pending_action(message, "risks")
    await message.answer(
        "Напишите тикер или название бумаги для анализа рисков, например: SBER или сбер"
    )


@router.message(F.text == "💡 Идея")
async def handle_idea_button(message: Message) -> None:
    """Enables pending idea mode from the reply keyboard."""

    set_pending_action(message, "idea")
    await message.answer(
        "Напишите тикер или название бумаги для идеи по бумаге, например: SBER или сбер"
    )


@router.message(Command("news"))
async def handle_news_command(message: Message) -> None:
    """Handles the /news command with a ticker argument."""

    raw_ticker = extract_command_argument(message)
    if not raw_ticker:
        set_pending_action(message, "news")
        await message.answer(
            "Напишите тикер или название бумаги для команды /news, например: SBER или сбер"
        )
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(message, raw_ticker, format_news_for_telegram)


@router.message(Command("risks"))
async def handle_risks_command(message: Message) -> None:
    """Handles the /risks command with a ticker argument."""

    raw_ticker = extract_command_argument(message)
    if not raw_ticker:
        set_pending_action(message, "risks")
        await message.answer(
            "Напишите тикер или название бумаги для команды /risks, например: SBER или сбер"
        )
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(message, raw_ticker, format_risks_for_telegram)


@router.message(Command("idea"))
async def handle_idea_command(message: Message) -> None:
    """Handles the /idea command with a ticker argument."""

    raw_ticker = extract_command_argument(message)
    if not raw_ticker:
        set_pending_action(message, "idea")
        await message.answer(
            "Напишите тикер или название бумаги для команды /idea, например: SBER или сбер"
        )
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(message, raw_ticker, format_idea_for_telegram)


@router.message(Command("full"))
async def handle_full_command(message: Message) -> None:
    """Handles the /full command with a ticker argument."""

    raw_ticker = extract_command_argument(message)
    if not raw_ticker:
        set_pending_action(message, "full")
        await message.answer(
            "Напишите тикер или название бумаги для подробного разбора, например: SBER или сбер"
        )
        return

    clear_pending_action(message)
    await _handle_command_analysis_request(message, raw_ticker, format_full_for_telegram)


@router.message()
async def handle_ticker_message(message: Message) -> None:
    """Handles a text message as a stock ticker request."""

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
    """Starts bot polling."""

    bot = Bot(token=get_telegram_bot_token())
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
