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


@router.message(F.text == "📈 Идеи дня")
async def handle_today_button(message: Message) -> None:
    """Handles the reply-keyboard button for daily ideas."""

    clear_pending_action(message)
    await message.answer("Смотрю идеи дня по списку бумаг, секунду...")

    try:
        reply = build_today_ideas_message()
    except Exception as error:
        reply = f"Не удалось собрать идеи дня: {error}"

    await message.answer(reply)


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


@router.message(Command("today"))
async def handle_today_command(message: Message) -> None:
    """Handles the /today command."""

    clear_pending_action(message)
    await message.answer("Смотрю идеи дня по списку бумаг, секунду...")

    try:
        reply = build_today_ideas_message()
    except Exception as error:
        reply = f"Не удалось собрать идеи дня: {error}"

    await message.answer(reply)


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
