"""Core logic for generating a user-friendly stock analysis."""

import re
from typing import TypedDict

from tools.market_data import get_stock_snapshot
from tools.news import get_company_news_summary
from tools.portfolio import get_portfolio_context


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


def _legacy_format_for_telegram_v1(result: dict[str, str | None]) -> str:
    """Formats an analysis result into a short Telegram-friendly message."""

    import re

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text")

    if error:
        return f"Не удалось выполнить анализ по тикеру {ticker}: {error}"

    if not analysis_text:
        return f"Не удалось получить результат анализа по тикеру {ticker}."

    normalized_text = analysis_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized_text.split("\n")]

    def extract_section_items(section_title: str) -> list[str]:
        items: list[str] = []
        inside_section = False

        for line in lines:
            stripped_line = line.strip()

            if stripped_line == section_title:
                inside_section = True
                continue

            if not inside_section:
                continue

            if not stripped_line:
                if items:
                    break
                continue

            if stripped_line.endswith(":") and not stripped_line.startswith("- "):
                break

            if stripped_line.startswith("- "):
                items.append(stripped_line[2:].strip())

        return items

    def extract_single_value(prefix: str) -> str | None:
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith(prefix):
                return stripped_line[len(prefix):].strip()
        return None

    def is_technical_noise(text: str) -> bool:
        lowered_text = text.lower()
        technical_markers = (
            "moex iss api",
            "источник цены",
            "основной режим торгов",
            "найдено ",
            "прямо по эмитенту",
            "по группе",
            "по другой компании",
            "слабо релевант",
            "биржевой статус",
            "торговый статус",
            "режим торгов",
            "котировка moex",
        )
        return any(marker in lowered_text for marker in technical_markers)

    def clean_news_item(text: str) -> str | None:
        cleaned_text = text.strip()
        cleaned_text = re.sub(r"^(?:\[[^\]]+\])+\s*", "", cleaned_text)
        cleaned_text = re.sub(r"^\d{2}\.\d{2}\.\d{4}(?: \d{2}:\d{2})?\s*-\s*", "", cleaned_text)
        cleaned_text = re.sub(r"\s+—\s+темы:.*$", "", cleaned_text)
        cleaned_text = re.sub(r"\s+\([^()\n]{1,80}\)\s*$", "", cleaned_text)
        cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip(" -")

        if not cleaned_text or is_technical_noise(cleaned_text):
            return None

        return cleaned_text

    def clean_bullet(text: str) -> str | None:
        cleaned_text = re.sub(r"\s+", " ", text).strip(" -")

        if not cleaned_text or is_technical_noise(cleaned_text):
            return None

        return cleaned_text

    def should_skip_plus_item(text: str) -> bool:
        lowered_text = text.lower()
        plus_noise_markers = (
            "в ленте есть",
            "новостной фон",
            "стоит отдельно проверить",
            "помогает быстро проверить",
            "инвестор видит",
            "биржевой статус",
            "торговый статус",
            "может выиграть",
            "помогает",
            "стоит проверить",
        )
        plus_concrete_markers = (
            "дивид",
            "прибыл",
            "выруч",
            "отчет",
            "отчёт",
            "отчетност",
            "отчётност",
            "рсбу",
            "мсфо",
            "рейтинг",
            "рекомендац",
            "целевая цена",
            "таргет",
            "аналитик",
        )
        if any(marker in lowered_text for marker in plus_noise_markers):
            return True
        return not any(marker in lowered_text for marker in plus_concrete_markers)

    def should_skip_risk_item(text: str) -> bool:
        lowered_text = text.lower()
        risk_noise_markers = (
            "цена акции может быстро меняться",
            "не заменяет анализ",
            "важно самостоятельно проверить",
            "место бумаги в портфеле",
            "позиция слишком большой",
        )
        return any(marker in lowered_text for marker in risk_noise_markers)

    def build_human_conclusion(sentiment: str | None, has_pluses: bool, has_risks: bool) -> str | None:
        sentiment_value = (sentiment or "").strip().lower()
        sentences: list[str] = []

        if sentiment_value:
            if "негатив" in sentiment_value:
                sentences.append(f"Фон сейчас {sentiment_value}, поэтому по бумаге пока стоит сохранять осторожность.")
            elif "позитив" in sentiment_value:
                sentences.append(f"Фон сейчас {sentiment_value}, и бумага выглядит интересно для наблюдения.")
            elif "смешан" in sentiment_value:
                sentences.append("Ситуация по бумаге сейчас выглядит смешанной.")
            elif "нейтраль" in sentiment_value:
                sentences.append("Фон сейчас скорее нейтральный.")

        if has_pluses and has_risks:
            sentences.append("Бумагу лучше смотреть через баланс сильных драйверов и заметных рисков.")
        elif has_pluses:
            sentences.append("Бумагу можно держать в фокусе, если следите за отчетностью, дивидендами и оценками аналитиков.")
        elif has_risks:
            sentences.append("Бумагу лучше смотреть выборочно и ждать более сильных сигналов.")

        if not sentences:
            return None

        return " ".join(sentences[:2])

    def build_main_scenario(sentiment: str | None, has_pluses: bool, has_risks: bool) -> str | None:
        sentiment_value = (sentiment or "").strip().lower()

        if "негатив" in sentiment_value:
            return "Фон скорее сдержанный, бумагу стоит смотреть осторожно."
        if "позитив" in sentiment_value:
            return "Фон выглядит умеренно позитивно, интерес к бумаге может сохраняться."
        if "смешан" in sentiment_value:
            return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
        if "нейтраль" in sentiment_value:
            if has_pluses and has_risks:
                return "Фон скорее нейтральный, дальше важнее баланс драйверов и рисков."
            if has_pluses:
                return "Фон скорее нейтральный, но отдельные сильные факторы есть."
            if has_risks:
                return "Фон скорее нейтральный, но риски пока заметны."
            return "Фон пока нейтральный, явного сильного сценария не видно."

        if has_pluses and has_risks:
            return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
        if has_pluses:
            return "Есть отдельные позитивные сигналы, но за бумагой лучше следить спокойно."
        if has_risks:
            return "Пока в фокусе скорее риски, поэтому спешить с выводами не стоит."

        return None

    def has_fundamental_positive_signal(items: list[str]) -> bool:
        fundamental_markers = (
            "дивид",
            "прибыл",
            "выруч",
            "отчет",
            "отчёт",
            "отчетност",
            "отчётност",
            "рсбу",
            "мсфо",
            "рейтинг",
            "рекомендац",
            "целевая цена",
            "таргет",
            "аналитик",
        )

        for item in items:
            lowered_item = item.lower()
            if any(marker in lowered_item for marker in fundamental_markers):
                return True

        return False

    def build_horizon_view(sentiment: str | None, pluses: list[str], risks: list[str]) -> list[str]:
        sentiment_value = (sentiment or "").strip().lower()
        has_pluses = bool(pluses)
        has_risks = bool(risks)
        has_fundamental_signal = has_fundamental_positive_signal(pluses)

        short_term = "данных пока недостаточно"
        if "негатив" in sentiment_value and has_risks:
            short_term = "скорее осторожно"
        elif "позитив" in sentiment_value and has_pluses and not has_risks:
            short_term = "можно следить за реакцией рынка"
        elif has_risks:
            short_term = "лучше без спешки"
        elif has_pluses:
            short_term = "можно держать под наблюдением"
        elif sentiment_value:
            short_term = "лучше наблюдать"

        medium_term = "данных пока недостаточно"
        if has_pluses and has_risks:
            medium_term = "можно держать под наблюдением, но с учетом рисков"
        elif has_pluses:
            medium_term = "можно держать под наблюдением"
        elif has_risks:
            medium_term = "лучше наблюдать со стороны"
        elif sentiment_value:
            medium_term = "лучше дождаться более ясной картины"

        long_term = "данных пока недостаточно"
        if has_fundamental_signal and has_risks:
            long_term = "стоит смотреть глубже по фундаменталу, но без спешки"
        elif has_fundamental_signal:
            long_term = "стоит смотреть глубже по фундаменталу"
        elif has_pluses:
            long_term = "можно изучить бумагу глубже"
        elif has_risks:
            long_term = "сначала лучше проверить фундаментал глубже"
        elif sentiment_value:
            long_term = "стоит проверить глубже, но данных пока мало"

        return [
            f"• Краткосрок: {short_term}",
            f"• Средний срок: {medium_term}",
            f"• Долгий срок: {long_term}",
        ]

    def normalize_sentiment(text: str) -> str:
        replacements = {
            "умеренно позитивным": "умеренно позитивный",
            "умеренно негативным": "умеренно негативный",
            "смешанным": "смешанный",
            "скорее нейтральным": "скорее нейтральный",
            "нейтральным": "нейтральный",
            "неопределенным": "неопределенный",
            "неопределённым": "неопределенный",
            "позитивным": "позитивный",
            "негативным": "негативный",
        }

        normalized_value = text.strip()

        for source_text, target_text in replacements.items():
            if normalized_value == source_text:
                return target_text

        return normalized_value

    price_line: str | None = None
    price_match = re.search(
        r"Актуальная цена на MOEX:\s*([\d.,]+)\s+([A-Za-zА-Яа-я]+)",
        normalized_text,
    )
    if price_match:
        price_value, currency = price_match.groups()
        price_line = f"Цена: {price_value} {currency}"

    sentiment_line: str | None = None
    sentiment_match = re.search(
        r"(?:новостной\s+)?фон выглядит ([^.]+?)(?:\.|$)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if sentiment_match:
        sentiment_value = normalize_sentiment(sentiment_match.group(1))
        sentiment_line = f"Фон: {sentiment_value}"

    important_now_items: list[str] = []
    for news_item in extract_section_items("Новостной фон:"):
        if "[инвестиционно значимая]" not in news_item:
            continue

        cleaned_item = clean_news_item(news_item)
        if cleaned_item and cleaned_item not in important_now_items:
            important_now_items.append(cleaned_item)

        if len(important_now_items) == 3:
            break

    plus_items: list[str] = []
    for item in extract_section_items("Возможные драйверы роста:"):
        cleaned_item = clean_bullet(item)
        if cleaned_item and not should_skip_plus_item(cleaned_item) and cleaned_item not in plus_items:
            plus_items.append(cleaned_item)

        if len(plus_items) == 3:
            break

    risk_items: list[str] = []
    for item in extract_section_items("Риски:"):
        cleaned_item = clean_bullet(item)
        if cleaned_item and not should_skip_risk_item(cleaned_item) and cleaned_item not in risk_items:
            risk_items.append(cleaned_item)

        if len(risk_items) == 3:
            break

    sentiment_value: str | None = None
    if sentiment_line:
        sentiment_value = sentiment_line.replace("Фон:", "", 1).strip()

    main_positive = plus_items[0] if plus_items else None
    main_risk = risk_items[0] if risk_items else None
    main_scenario = build_main_scenario(
        sentiment=sentiment_value,
        has_pluses=bool(plus_items),
        has_risks=bool(risk_items),
    )
    horizon_items = build_horizon_view(
        sentiment=sentiment_value,
        pluses=plus_items,
        risks=risk_items,
    )

    conclusion_text = build_human_conclusion(
        sentiment=sentiment_value,
        has_pluses=bool(plus_items),
        has_risks=bool(risk_items),
    )

    if not conclusion_text:
        fallback_conclusion = extract_single_value("Нейтральный вывод:")
        if fallback_conclusion:
            fallback_conclusion = re.sub(
                rf"^По\s+{re.escape(ticker)}\s+сейчас\s+можно\s+получить\s+реальную\s+цену\s+и\s+карточку\s+бумаги\s+с\s+MOEX,\s*но\s*",
                "",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bдля полноценного решения\b",
                "сейчас",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bважно самостоятельно проверить\b",
                "лучше дополнительно проверить",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(r"\s+", " ", fallback_conclusion).strip()
            fallback_sentences = re.split(r"(?<=[.!?])\s+", fallback_conclusion, maxsplit=1)
            conclusion_text = fallback_sentences[0].strip()
            if conclusion_text:
                conclusion_text = conclusion_text[0].upper() + conclusion_text[1:]

    blocks: list[str] = []

    intro_lines = [line for line in (price_line, sentiment_line) if line]
    if intro_lines:
        blocks.append("\n".join(intro_lines))

    if important_now_items:
        blocks.append(
            "Что важно сейчас:\n" + "\n".join(f"• {item}" for item in important_now_items)
        )

    main_points: list[str] = []
    if main_positive:
        main_points.append(f"• Позитив: {main_positive}")
    if main_risk:
        main_points.append(f"• Риск: {main_risk}")
    if main_scenario:
        main_points.append(f"• Сценарий: {main_scenario}")

    if main_points:
        blocks.append("Главное:\n" + "\n".join(main_points))
    else:
        if plus_items:
            blocks.append("Плюсы:\n" + "\n".join(f"• {item}" for item in plus_items))

        if risk_items:
            blocks.append("Риски:\n" + "\n".join(f"• {item}" for item in risk_items))

    if conclusion_text:
        blocks.append(f"Вывод:\n{conclusion_text}")

    if horizon_items:
        blocks.append("Горизонт:\n" + "\n".join(horizon_items))

    if not blocks:
        blocks.append(normalized_text)

    return f"{ticker} — краткий разбор\n\n" + "\n\n".join(blocks)


def _legacy_format_for_telegram_v2(result: dict[str, str | None]) -> str:
    """Formats an analysis result into a short Telegram-friendly message."""

    import re

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text")

    if error:
        return f"Не удалось выполнить анализ по тикеру {ticker}: {error}"

    if not analysis_text:
        return f"Не удалось получить результат анализа по тикеру {ticker}."

    normalized_text = analysis_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized_text.split("\n")]

    def extract_section_items(section_title: str) -> list[str]:
        items: list[str] = []
        inside_section = False

        for line in lines:
            stripped_line = line.strip()

            if stripped_line == section_title:
                inside_section = True
                continue

            if not inside_section:
                continue

            if not stripped_line:
                if items:
                    break
                continue

            if stripped_line.endswith(":") and not stripped_line.startswith("- "):
                break

            if stripped_line.startswith("- "):
                items.append(stripped_line[2:].strip())

        return items

    def extract_single_value(prefix: str) -> str | None:
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith(prefix):
                return stripped_line[len(prefix):].strip()
        return None

    def is_technical_noise(text: str) -> bool:
        lowered_text = text.lower()
        technical_markers = (
            "moex iss api",
            "источник цены",
            "основной режим торгов",
            "найдено ",
            "прямо по эмитенту",
            "по группе",
            "по другой компании",
            "слабо релевант",
            "биржевой статус",
            "торговый статус",
            "режим торгов",
            "котировка moex",
        )
        return any(marker in lowered_text for marker in technical_markers)

    def clean_news_item(text: str) -> str | None:
        cleaned_text = text.strip()
        cleaned_text = re.sub(r"^(?:\[[^\]]+\])+\s*", "", cleaned_text)
        cleaned_text = re.sub(r"^\d{2}\.\d{2}\.\d{4}(?: \d{2}:\d{2})?\s*-\s*", "", cleaned_text)
        cleaned_text = re.sub(r"\s+[—-]\s+темы:.*$", "", cleaned_text)
        cleaned_text = re.sub(r"\s+\([^()\n]{1,80}\)\s*$", "", cleaned_text)
        cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip(" -")

        if not cleaned_text or is_technical_noise(cleaned_text):
            return None

        return cleaned_text

    def clean_bullet(text: str) -> str | None:
        cleaned_text = re.sub(r"\s+", " ", text).strip(" -")

        if not cleaned_text or is_technical_noise(cleaned_text):
            return None

        return cleaned_text

    def should_skip_plus_item(text: str) -> bool:
        lowered_text = text.lower()
        plus_noise_markers = (
            "в ленте есть",
            "новостной фон",
            "стоит отдельно проверить",
            "помогает быстро проверить",
            "инвестор видит",
            "биржевой статус",
            "торговый статус",
            "может выиграть",
            "помогает",
            "стоит проверить",
        )
        plus_concrete_markers = (
            "дивид",
            "прибыл",
            "выруч",
            "отчет",
            "отчёт",
            "отчетност",
            "отчётност",
            "рсбу",
            "мсфо",
            "рейтинг",
            "рекомендац",
            "целевая цена",
            "таргет",
            "аналитик",
        )

        if any(marker in lowered_text for marker in plus_noise_markers):
            return True

        return not any(marker in lowered_text for marker in plus_concrete_markers)

    def should_skip_risk_item(text: str) -> bool:
        lowered_text = text.lower()
        risk_noise_markers = (
            "цена акции может быстро меняться",
            "не заменяет анализ",
            "важно самостоятельно проверить",
            "место бумаги в портфеле",
            "позиция слишком большой",
        )
        return any(marker in lowered_text for marker in risk_noise_markers)

    def build_human_conclusion(sentiment: str | None, has_pluses: bool, has_risks: bool) -> str | None:
        sentiment_value = (sentiment or "").strip().lower()
        sentences: list[str] = []

        if sentiment_value:
            if "негатив" in sentiment_value:
                sentences.append(f"Фон сейчас {sentiment_value}, поэтому по бумаге пока стоит сохранять осторожность.")
            elif "позитив" in sentiment_value:
                sentences.append(f"Фон сейчас {sentiment_value}, и бумага выглядит интересно для наблюдения.")
            elif "смешан" in sentiment_value:
                sentences.append("Ситуация по бумаге сейчас выглядит смешанной.")
            elif "нейтраль" in sentiment_value:
                sentences.append("Фон сейчас скорее нейтральный.")

        if has_pluses and has_risks:
            sentences.append("Бумагу лучше смотреть через баланс сильных драйверов и заметных рисков.")
        elif has_pluses:
            sentences.append("Бумагу можно держать в фокусе, если следите за отчетностью, дивидендами и оценками аналитиков.")
        elif has_risks:
            sentences.append("Бумагу лучше смотреть выборочно и ждать более сильных сигналов.")

        if not sentences:
            return None

        return " ".join(sentences[:2])

    def build_main_scenario(sentiment: str | None, has_pluses: bool, has_risks: bool) -> str | None:
        sentiment_value = (sentiment or "").strip().lower()

        if "негатив" in sentiment_value:
            return "Фон скорее сдержанный, бумагу стоит смотреть осторожно."
        if "позитив" in sentiment_value:
            return "Фон выглядит умеренно позитивно, интерес к бумаге может сохраняться."
        if "смешан" in sentiment_value:
            return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
        if "нейтраль" in sentiment_value:
            if has_pluses and has_risks:
                return "Фон скорее нейтральный, дальше важнее баланс драйверов и рисков."
            if has_pluses:
                return "Фон скорее нейтральный, но отдельные сильные факторы есть."
            if has_risks:
                return "Фон скорее нейтральный, но риски пока заметны."
            return "Фон пока нейтральный, явного сильного сценария не видно."

        if has_pluses and has_risks:
            return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
        if has_pluses:
            return "Есть отдельные позитивные сигналы, но за бумагой лучше следить спокойно."
        if has_risks:
            return "Пока в фокусе скорее риски, поэтому спешить с выводами не стоит."

        return None

    def has_fundamental_positive_signal(items: list[str]) -> bool:
        fundamental_markers = (
            "дивид",
            "прибыл",
            "выруч",
            "отчет",
            "отчёт",
            "отчетност",
            "отчётност",
            "рсбу",
            "мсфо",
            "рейтинг",
            "рекомендац",
            "целевая цена",
            "таргет",
            "аналитик",
        )

        for item in items:
            lowered_item = item.lower()
            if any(marker in lowered_item for marker in fundamental_markers):
                return True

        return False

    def build_horizon_view(sentiment: str | None, pluses: list[str], risks: list[str]) -> list[str]:
        sentiment_value = (sentiment or "").strip().lower()
        has_pluses = bool(pluses)
        has_risks = bool(risks)
        has_fundamental_signal = has_fundamental_positive_signal(pluses)

        short_term = "данных пока недостаточно"
        if "негатив" in sentiment_value and has_risks:
            short_term = "скорее осторожно"
        elif "позитив" in sentiment_value and has_pluses and not has_risks:
            short_term = "можно следить за реакцией рынка"
        elif has_risks:
            short_term = "лучше без спешки"
        elif has_pluses:
            short_term = "можно держать под наблюдением"
        elif sentiment_value:
            short_term = "лучше наблюдать"

        medium_term = "данных пока недостаточно"
        if has_pluses and has_risks:
            medium_term = "можно держать под наблюдением, но с учетом рисков"
        elif has_pluses:
            medium_term = "можно держать под наблюдением"
        elif has_risks:
            medium_term = "лучше наблюдать со стороны"
        elif sentiment_value:
            medium_term = "лучше дождаться более ясной картины"

        long_term = "данных пока недостаточно"
        if has_fundamental_signal and has_risks:
            long_term = "стоит смотреть глубже по фундаменталу, но без спешки"
        elif has_fundamental_signal:
            long_term = "стоит смотреть глубже по фундаменталу"
        elif has_pluses:
            long_term = "можно изучить бумагу глубже"
        elif has_risks:
            long_term = "сначала лучше проверить фундаментал глубже"
        elif sentiment_value:
            long_term = "стоит проверить глубже, но данных пока мало"

        return [
            f"• Краткосрок: {short_term}",
            f"• Средний срок: {medium_term}",
            f"• Долгий срок: {long_term}",
        ]

    def normalize_sentiment(text: str) -> str:
        replacements = {
            "умеренно позитивным": "умеренно позитивный",
            "умеренно негативным": "умеренно негативный",
            "смешанным": "смешанный",
            "скорее нейтральным": "скорее нейтральный",
            "нейтральным": "нейтральный",
            "неопределенным": "неопределенный",
            "неопределённым": "неопределенный",
            "позитивным": "позитивный",
            "негативным": "негативный",
        }

        normalized_value = text.strip()

        for source_text, target_text in replacements.items():
            if normalized_value == source_text:
                return target_text

        return normalized_value

    price_line: str | None = None
    price_match = re.search(
        r"Актуальная цена на MOEX:\s*([\d.,]+)\s+([A-Za-zА-Яа-я]+)",
        normalized_text,
    )
    if price_match:
        price_value, currency = price_match.groups()
        price_line = f"Цена: {price_value} {currency}"

    sentiment_line: str | None = None
    sentiment_match = re.search(
        r"(?:новостной\s+)?фон выглядит ([^.]+?)(?:\.|$)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if sentiment_match:
        sentiment_value = normalize_sentiment(sentiment_match.group(1))
        sentiment_line = f"Фон: {sentiment_value}"

    important_now_items: list[str] = []
    for news_item in extract_section_items("Новостной фон:"):
        if "[инвестиционно значимая]" not in news_item:
            continue

        cleaned_item = clean_news_item(news_item)
        if cleaned_item and cleaned_item not in important_now_items:
            important_now_items.append(cleaned_item)

        if len(important_now_items) == 3:
            break

    plus_items: list[str] = []
    for item in extract_section_items("Возможные драйверы роста:"):
        cleaned_item = clean_bullet(item)
        if cleaned_item and not should_skip_plus_item(cleaned_item) and cleaned_item not in plus_items:
            plus_items.append(cleaned_item)

        if len(plus_items) == 3:
            break

    risk_items: list[str] = []
    for item in extract_section_items("Риски:"):
        cleaned_item = clean_bullet(item)
        if cleaned_item and not should_skip_risk_item(cleaned_item) and cleaned_item not in risk_items:
            risk_items.append(cleaned_item)

        if len(risk_items) == 3:
            break

    sentiment_value: str | None = None
    if sentiment_line:
        sentiment_value = sentiment_line.replace("Фон:", "", 1).strip()

    main_positive = plus_items[0] if plus_items else None
    main_risk = risk_items[0] if risk_items else None
    main_scenario = build_main_scenario(
        sentiment=sentiment_value,
        has_pluses=bool(plus_items),
        has_risks=bool(risk_items),
    )
    horizon_items = build_horizon_view(
        sentiment=sentiment_value,
        pluses=plus_items,
        risks=risk_items,
    )

    conclusion_text = build_human_conclusion(
        sentiment=sentiment_value,
        has_pluses=bool(plus_items),
        has_risks=bool(risk_items),
    )

    if not conclusion_text:
        fallback_conclusion = extract_single_value("Нейтральный вывод:")
        if fallback_conclusion:
            fallback_conclusion = re.sub(
                rf"^По\s+{re.escape(ticker)}\s+сейчас\s+можно\s+получить\s+реальную\s+цену\s+и\s+карточку\s+бумаги\s+с\s+MOEX,\s*но\s*",
                "",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bдля полноценного решения\b",
                "сейчас",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bважно самостоятельно проверить\b",
                "лучше дополнительно проверить",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(r"\s+", " ", fallback_conclusion).strip()
            fallback_sentences = re.split(r"(?<=[.!?])\s+", fallback_conclusion, maxsplit=1)
            conclusion_text = fallback_sentences[0].strip()
            if conclusion_text:
                conclusion_text = conclusion_text[0].upper() + conclusion_text[1:]

    blocks: list[str] = []

    intro_lines = [line for line in (price_line, sentiment_line) if line]
    if intro_lines:
        blocks.append("\n".join(intro_lines))

    if important_now_items:
        blocks.append(
            "Что важно сейчас:\n" + "\n".join(f"• {item}" for item in important_now_items)
        )

    main_points: list[str] = []
    if main_positive:
        main_points.append(f"• Позитив: {main_positive}")
    if main_risk:
        main_points.append(f"• Риск: {main_risk}")
    if main_scenario:
        main_points.append(f"• Сценарий: {main_scenario}")

    if main_points:
        blocks.append("Главное:\n" + "\n".join(main_points))
    else:
        if plus_items:
            blocks.append("Плюсы:\n" + "\n".join(f"• {item}" for item in plus_items))

        if risk_items:
            blocks.append("Риски:\n" + "\n".join(f"• {item}" for item in risk_items))

    if horizon_items:
        blocks.append("Горизонт:\n" + "\n".join(horizon_items))

    if conclusion_text:
        blocks.append(f"Вывод:\n{conclusion_text}")

    if not blocks:
        blocks.append(normalized_text)

    return f"{ticker} — краткий разбор\n\n" + "\n\n".join(blocks)


class _TelegramFormatParts(TypedDict):
    """Structured intermediate data for the Telegram response builder."""

    normalized_text: str
    price_line: str | None
    price_dynamics_items: list[str]
    sentiment_line: str | None
    sentiment_value: str | None
    important_now_items: list[str]
    plus_items: list[str]
    risk_items: list[str]
    main_positive: str | None
    main_risk: str | None
    main_scenario: str | None
    interest_score: int
    interest_reason: str
    signal_entry: str
    signal_tactic: str
    horizon_items: list[str]
    conclusion_text: str | None


_POSITIVE_NEWS_MARKERS = (
    "рост выручки",
    "увеличил прибыль",
    "чистая прибыль",
    "чистую прибыль",
    "увеличил чистую прибыль",
    "дивиден",
    "рекомендовал дивиденды",
    "повысили рейтинг",
    "целевая цена",
    "слияние",
    "лидер рейтинга",
    "отсрочили санкции",
    "сняли санкции",
)

_NEGATIVE_NEWS_MARKERS = (
    "убыток",
    "снижение прогноза",
    "понизил прогноз",
    "давление на сектор",
    "санкц",
    "падение",
    "слабая отчетность",
    "сокращение",
    "ухудшение",
    "снизил",
)

_NEUTRAL_NEWS_MARKERS = (
    "главное к ",
    "обзор рынка",
    "обзор торгов",
    "итоги дня",
    "к открытию торгов",
    "на открытии рынка",
)

_POSITIVE_NEWS_THEMES = (
    (("дивиден", "рекомендовал дивиденды"), "дивидендная тема поддерживает интерес к бумаге"),
    (
        ("рост выручки", "увеличил прибыль", "чистая прибыль", "чистую прибыль", "увеличил чистую прибыль"),
        "сильные финансовые результаты поддерживают бумагу",
    ),
    (
        ("повысили рейтинг", "целевая цена", "лидер рейтинга"),
        "поддержка аналитиков выглядит позитивно",
    ),
    (("слияние",), "корпоративные события могут поддерживать интерес к бумаге"),
    (
        ("отсрочили санкции", "сняли санкции"),
        "внешний фон по бумаге выглядит мягче",
    ),
)

_NEGATIVE_NEWS_THEMES = (
    (("санкц",), "санкционные риски по бумаге сохраняются"),
    (("давление на сектор",), "давление на сектор остается фактором риска"),
    (
        (
            "убыток",
            "снижение прогноза",
            "понизил прогноз",
            "падение",
            "слабая отчетность",
            "сокращение",
            "ухудшение",
            "снизил",
        ),
        "негативные ожидания по результатам сдерживают интерес к бумаге",
    ),
)


def _normalize_news_match_text(text: str) -> str:
    """Normalizes a news headline for simple keyword matching."""

    return " ".join((text or "").lower().replace("ё", "е").split())


def _detect_news_signal(text: str) -> str | None:
    """Classifies a news headline as positive, negative or neutral noise."""

    normalized_text = _normalize_news_match_text(text)

    if any(marker in normalized_text for marker in _NEUTRAL_NEWS_MARKERS):
        return None

    positive_hits = sum(1 for marker in _POSITIVE_NEWS_MARKERS if marker in normalized_text)
    negative_hits = sum(1 for marker in _NEGATIVE_NEWS_MARKERS if marker in normalized_text)

    if positive_hits == 0 and negative_hits == 0:
        return None
    if positive_hits > negative_hits:
        return "positive"
    if negative_hits > positive_hits:
        return "negative"

    return None


def _extract_news_signals(news_items: list[str]) -> tuple[str | None, str | None]:
    """Returns the first strong positive and negative headlines from key news."""

    positive_item: str | None = None
    negative_item: str | None = None

    for item in news_items:
        signal = _detect_news_signal(item)
        if signal == "positive" and positive_item is None:
            positive_item = item
        elif signal == "negative" and negative_item is None:
            negative_item = item

        if positive_item and negative_item:
            break

    return positive_item, negative_item


def _summarize_news_theme(text: str | None, signal_type: str) -> str | None:
    """Maps a concrete news headline to a short analytical theme."""

    if not text:
        return None

    normalized_text = _normalize_news_match_text(text)
    theme_map = _POSITIVE_NEWS_THEMES if signal_type == "positive" else _NEGATIVE_NEWS_THEMES

    for markers, summary in theme_map:
        if any(marker in normalized_text for marker in markers):
            return summary

    return None


def _lowercase_first(text: str) -> str:
    """Lowercases the first letter to connect two short clauses."""

    if not text:
        return text

    return text[0].lower() + text[1:]


def _extract_section_items(lines: list[str], section_title: str) -> list[str]:
    """Collects bullet items from a named section in the analysis text."""

    items: list[str] = []
    inside_section = False

    for line in lines:
        stripped_line = line.strip()

        if stripped_line == section_title:
            inside_section = True
            continue

        if not inside_section:
            continue

        if not stripped_line:
            if items:
                break
            continue

        if stripped_line.endswith(":") and not stripped_line.startswith("- "):
            break

        if stripped_line.startswith("- "):
            items.append(stripped_line[2:].strip())

    return items


def _extract_important_news(lines: list[str], limit: int = 3) -> list[str]:
    """Collects cleaned investment-significant news items from the news block."""

    important_items: list[str] = []

    for news_item in _extract_section_items(lines, "Новостной фон:"):
        if "[инвестиционно значимая]" not in news_item:
            continue

        cleaned_item = _clean_news_item(news_item)
        if cleaned_item and cleaned_item not in important_items:
            important_items.append(cleaned_item)

        if len(important_items) == limit:
            break

    return important_items


def _extract_growth_driver_items(lines: list[str], limit: int = 3) -> list[str]:
    """Collects cleaned positive factors for Telegram output."""

    items: list[str] = []

    for item in _extract_section_items(lines, "Возможные драйверы роста:"):
        cleaned_item = _clean_bullet(item)
        if cleaned_item and not _should_skip_plus_item(cleaned_item) and cleaned_item not in items:
            items.append(cleaned_item)

        if len(items) == limit:
            break

    return items


def _extract_risk_items(lines: list[str], limit: int = 3) -> list[str]:
    """Collects cleaned risk factors for Telegram output."""

    items: list[str] = []

    for item in _extract_section_items(lines, "Риски:"):
        cleaned_item = _clean_bullet(item)
        if cleaned_item and not _should_skip_risk_item(cleaned_item) and cleaned_item not in items:
            items.append(cleaned_item)

        if len(items) == limit:
            break

    return items


def _extract_price_dynamics_items(lines: list[str]) -> list[str]:
    """Collects already formatted price-dynamics lines from the analysis text."""

    preferred_labels = ("1ч", "1д", "1н")
    items_by_label: dict[str, str] = {}

    for item in _extract_section_items(lines, "Динамика:"):
        cleaned_item = re.sub(r"\s+", " ", item).strip()
        if not cleaned_item or ":" not in cleaned_item:
            continue

        label, value = cleaned_item.split(":", maxsplit=1)
        normalized_label = label.strip()
        normalized_value = value.strip()

        if normalized_label and normalized_value:
            items_by_label[normalized_label] = f"{normalized_label}: {normalized_value}"

    return [items_by_label[label] for label in preferred_labels if label in items_by_label]


def _extract_short_summary_for_telegram(lines: list[str], ticker: str) -> str | None:
    """Builds a cleaned paper summary without technical service noise."""

    summary = _extract_single_value(lines, "Кратко по бумаге:")
    if not summary:
        return None

    normalized_summary = re.sub(r"\s+", " ", summary).strip()
    sentences = re.split(r"(?<=[.!?])\s+", normalized_summary)
    cleaned_sentences: list[str] = []

    for sentence in sentences:
        cleaned_sentence = sentence.strip()
        lowered_sentence = cleaned_sentence.lower()

        if not cleaned_sentence:
            continue
        if "актуальная цена на moex" in lowered_sentence:
            continue
        if "источник цены" in lowered_sentence:
            continue
        if "основной режим торгов" in lowered_sentence:
            continue
        if "moex iss api не вернул" in lowered_sentence:
            continue

        cleaned_sentence = cleaned_sentence.replace("Сектор по данным MOEX:", "Сектор:")
        cleaned_sentences.append(cleaned_sentence)

    cleaned_summary = " ".join(cleaned_sentences).strip()
    if cleaned_summary:
        return cleaned_summary

    return ticker


def _extract_single_value(lines: list[str], prefix: str) -> str | None:
    """Returns the value that follows a single-line prefix."""

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith(prefix):
            return stripped_line[len(prefix):].strip()

    return None


def _is_technical_noise(text: str) -> bool:
    """Filters out technical service lines that are not useful in Telegram."""

    lowered_text = text.lower()
    technical_markers = (
        "moex iss api",
        "источник цены",
        "основной режим торгов",
        "найдено ",
        "прямо по эмитенту",
        "по группе",
        "по другой компании",
        "слабо релевант",
        "биржевой статус",
        "торговый статус",
        "режим торгов",
        "котировка moex",
    )
    return any(marker in lowered_text for marker in technical_markers)


def _clean_news_item(text: str) -> str | None:
    """Removes service labels from a news line and keeps only the headline."""

    cleaned_text = text.strip()
    cleaned_text = re.sub(r"^(?:\[[^\]]+\])+\s*", "", cleaned_text)
    cleaned_text = re.sub(r"^\d{2}\.\d{2}\.\d{4}(?: \d{2}:\d{2})?\s*-\s*", "", cleaned_text)
    cleaned_text = re.sub(r"\s+[—-]\s+темы:.*$", "", cleaned_text)
    cleaned_text = re.sub(r"\s+\([^()\n]{1,80}\)\s*$", "", cleaned_text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip(" -")

    if not cleaned_text or _is_technical_noise(cleaned_text):
        return None

    return cleaned_text


def _clean_bullet(text: str) -> str | None:
    """Normalizes a bullet item and drops technical noise."""

    cleaned_text = re.sub(r"\s+", " ", text).strip(" -")

    if not cleaned_text or _is_technical_noise(cleaned_text):
        return None

    return cleaned_text


def _should_skip_plus_item(text: str) -> bool:
    """Skips weak or overly generic positives in the short Telegram format."""

    lowered_text = text.lower()
    plus_noise_markers = (
        "в ленте есть",
        "новостной фон",
        "стоит отдельно проверить",
        "помогает быстро проверить",
        "инвестор видит",
        "биржевой статус",
        "торговый статус",
        "может выиграть",
        "помогает",
        "стоит проверить",
    )
    plus_concrete_markers = (
        "дивид",
        "прибыл",
        "выруч",
        "отчет",
        "отчёт",
        "отчетност",
        "отчётност",
        "рсбу",
        "мсфо",
        "рейтинг",
        "рекомендац",
        "целевая цена",
        "таргет",
        "аналитик",
    )

    if any(marker in lowered_text for marker in plus_noise_markers):
        return True

    return not any(marker in lowered_text for marker in plus_concrete_markers)


def _should_skip_risk_item(text: str) -> bool:
    """Skips generic disclaimers inside the risks block."""

    lowered_text = text.lower()
    risk_noise_markers = (
        "цена акции может быстро меняться",
        "не заменяет анализ",
        "важно самостоятельно проверить",
        "место бумаги в портфеле",
        "позиция слишком большой",
    )
    return any(marker in lowered_text for marker in risk_noise_markers)


def _build_human_conclusion(
    sentiment: str | None,
    has_pluses: bool,
    has_risks: bool,
    positive_theme: str | None = None,
    negative_theme: str | None = None,
) -> str | None:
    """Builds the final short conclusion in a human Telegram style."""

    if positive_theme and negative_theme:
        return (
            f"{positive_theme.capitalize()}, но {_lowercase_first(negative_theme)}. "
            "Бумагу пока лучше держать в фокусе без спешки."
        )

    if positive_theme:
        return (
            f"{positive_theme.capitalize()}. "
            "Бумагу можно держать в поле зрения, но решение лучше принимать спокойно."
        )

    if negative_theme:
        return (
            f"{negative_theme.capitalize()}. "
            "По бумаге сейчас лучше сохранять осторожность."
        )

    sentiment_value = (sentiment or "").strip().lower()
    sentences: list[str] = []

    if sentiment_value:
        if "негатив" in sentiment_value:
            sentences.append(
                f"Фон сейчас {sentiment_value}, поэтому по бумаге пока стоит сохранять осторожность."
            )
        elif "позитив" in sentiment_value:
            sentences.append(
                f"Фон сейчас {sentiment_value}, и бумага выглядит интересно для наблюдения."
            )
        elif "смешан" in sentiment_value:
            sentences.append("Ситуация по бумаге сейчас выглядит смешанной.")
        elif "нейтраль" in sentiment_value:
            sentences.append("Фон сейчас скорее нейтральный.")

    if has_pluses and has_risks:
        sentences.append("Бумагу лучше смотреть через баланс сильных драйверов и заметных рисков.")
    elif has_pluses:
        sentences.append(
            "Бумагу можно держать в фокусе, если следите за отчетностью, дивидендами и оценками аналитиков."
        )
    elif has_risks:
        sentences.append("Бумагу лучше смотреть выборочно и ждать более сильных сигналов.")

    if not sentences:
        return None

    return " ".join(sentences[:2])


def _build_main_scenario(
    sentiment: str | None,
    has_pluses: bool,
    has_risks: bool,
    positive_news: str | None = None,
    negative_news: str | None = None,
) -> str | None:
    """Builds the short scenario line for the 'Главное' block."""

    sentiment_value = (sentiment or "").strip().lower()
    has_positive_news = bool(positive_news)
    has_negative_news = bool(negative_news)

    if has_positive_news and has_negative_news:
        if "позитив" in sentiment_value:
            return "Новостной фон скорее поддерживающий, но часть рисков сохраняется."
        if "негатив" in sentiment_value:
            return "Негативный фон пока заметен, хотя сильные новости по бумаге тоже есть."
        return "По бумаге есть сильные драйверы, но и риски пока заметны."

    if has_positive_news:
        if "негатив" in sentiment_value:
            return "Позитивные новости есть, но общий фон пока не дает расслабляться."
        return "Новостной фон скорее поддерживающий, интерес к бумаге может сохраняться."

    if has_negative_news:
        if "позитив" in sentiment_value:
            return "Поддерживающие сигналы есть, но риски пока не сняты."
        return "В фокусе скорее риски, и бумагу пока лучше смотреть осторожно."

    if "негатив" in sentiment_value:
        return "Фон скорее сдержанный, бумагу стоит смотреть осторожно."
    if "позитив" in sentiment_value:
        return "Фон выглядит умеренно позитивно, интерес к бумаге может сохраняться."
    if "смешан" in sentiment_value:
        return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
    if "нейтраль" in sentiment_value:
        if has_pluses and has_risks:
            return "Фон скорее нейтральный, дальше важнее баланс драйверов и рисков."
        if has_pluses:
            return "Фон скорее нейтральный, но отдельные сильные факторы есть."
        if has_risks:
            return "Фон скорее нейтральный, но риски пока заметны."
        return "Фон пока нейтральный, явного сильного сценария не видно."

    if has_pluses and has_risks:
        return "Картина смешанная: есть сильные стороны, но и риски пока заметны."
    if has_pluses:
        return "Есть отдельные позитивные сигналы, но за бумагой лучше следить спокойно."
    if has_risks:
        return "Пока в фокусе скорее риски, поэтому спешить с выводами не стоит."

    return None


def _has_fundamental_positive_signal(items: list[str]) -> bool:
    """Checks whether positives contain more fundamental long-term signals."""

    fundamental_markers = (
        "дивид",
        "прибыл",
        "выруч",
        "отчет",
        "отчёт",
        "отчетност",
        "отчётност",
        "рсбу",
        "мсфо",
        "рейтинг",
        "рекомендац",
        "целевая цена",
        "таргет",
        "аналитик",
    )

    for item in items:
        lowered_item = item.lower()
        if any(marker in lowered_item for marker in fundamental_markers):
            return True

    return False


def _build_horizon_view(sentiment: str | None, pluses: list[str], risks: list[str]) -> list[str]:
    """Builds more concrete horizon hints for short, medium and long views."""

    sentiment_value = (sentiment or "").strip().lower()
    has_pluses = bool(pluses)
    has_risks = bool(risks)
    has_fundamental_signal = _has_fundamental_positive_signal(pluses)

    if not sentiment_value and not has_pluses and not has_risks:
        return []

    has_negative_sentiment = "негатив" in sentiment_value
    has_positive_sentiment = "позитив" in sentiment_value
    has_mixed_sentiment = "смешан" in sentiment_value
    has_neutral_sentiment = "нейтрал" in sentiment_value

    short_term = "данных для уверенной оценки мало"
    if has_negative_sentiment and has_risks:
        short_term = "скорее не для входа сейчас"
    elif has_positive_sentiment and has_pluses and not has_risks:
        short_term = "краткосрочно выглядит интересно"
    elif has_mixed_sentiment and has_pluses and has_risks:
        short_term = "можно рассматривать только спекулятивно"
    elif has_risks:
        short_term = "краткосрочно сигнал пока слабый"
    elif has_pluses:
        short_term = "краткосрочно выглядит интересно"
    elif sentiment_value:
        short_term = "сигнал пока слабый"

    medium_term = "данных для уверенной оценки мало"
    if has_negative_sentiment and has_risks:
        medium_term = "идея скорее для наблюдения, чем для входа"
    elif has_positive_sentiment and has_pluses and not has_risks:
        medium_term = "среднесрочно выглядит рабоче"
    elif has_mixed_sentiment and has_pluses and has_risks:
        medium_term = "идея спорная, нужен контроль новостей"
    elif has_neutral_sentiment and has_pluses and has_risks:
        medium_term = "можно рассматривать при подтверждении новостей"
    elif has_pluses:
        medium_term = "можно рассматривать при подтверждении новостей"
    elif has_risks:
        medium_term = "среднесрочно история спорная"
    elif sentiment_value:
        medium_term = "идея скорее для наблюдения, чем для входа"

    long_term = "данных для уверенной оценки мало"
    if has_fundamental_signal and not has_risks and (has_pluses or has_positive_sentiment):
        long_term = "можно рассматривать как долгосрочную идею"
    elif has_fundamental_signal and has_risks:
        long_term = "подходит только после проверки фундаментала"
    elif has_pluses and not has_risks:
        long_term = "долгосрочно история выглядит интересно"
    elif has_risks and not has_fundamental_signal:
        long_term = "для долгого срока пока слабовато"
    elif has_pluses:
        long_term = "подходит только после проверки фундаментала"
    elif sentiment_value:
        long_term = "для долгого срока пока слабовато"

    return [
        f"• Краткосрок: {short_term}",
        f"• Средний срок: {medium_term}",
        f"• Долгий срок: {long_term}",
    ]


def _calculate_interest_score(
    sentiment: str | None,
    has_positive_signal: bool,
    has_risk_signal: bool,
    has_fundamental_signal: bool,
) -> int:
    """Calculates a cautious 1-10 attractiveness score for the current setup."""

    sentiment_value = (sentiment or "").strip().lower()
    if not sentiment_value and not has_positive_signal and not has_risk_signal:
        return 4

    score = 5

    if "негатив" in sentiment_value:
        score -= 2
    elif "позитив" in sentiment_value:
        score += 1

    if has_positive_signal:
        score += 1
    if has_risk_signal:
        score -= 1
    if has_fundamental_signal:
        score += 1

    if has_positive_signal and not has_risk_signal and "позитив" in sentiment_value:
        score += 1
    elif has_risk_signal and not has_positive_signal and "негатив" in sentiment_value:
        score -= 1

    return max(3, min(score, 8))


def _build_interest_reason(
    sentiment: str | None,
    interest_score: int,
    has_positive_signal: bool,
    has_risk_signal: bool,
    has_fundamental_signal: bool,
) -> str:
    """Builds a short human explanation for the current interest score."""

    sentiment_value = (sentiment or "").strip().lower()

    if not sentiment_value and not has_positive_signal and not has_risk_signal:
        return "данных для уверенной идеи пока маловато"

    if interest_score <= 4:
        if "негатив" in sentiment_value and has_risk_signal:
            return "негативный фон и сильный риск давят на идею"
        if has_risk_signal and has_positive_signal:
            return "есть поддержка, но риски сейчас перевешивают"
        if has_risk_signal:
            return "риски пока заметнее, чем поддерживающие сигналы"
        return "данных для уверенной идеи пока маловато"

    if interest_score >= 7:
        if "позитив" in sentiment_value and has_fundamental_signal:
            return "позитивный фон и фундаментальные факторы поддерживают интерес"
        if has_positive_signal and not has_risk_signal:
            return "поддерживающие сигналы сейчас выглядят достаточно уверенно"
        return "по бумаге сейчас больше поддержки, чем ограничений"

    if has_positive_signal and has_risk_signal:
        return "есть поддерживающие сигналы, но риски пока не сняты"
    if has_positive_signal and has_fundamental_signal:
        return "фундаментальные сигналы есть, но картина пока не безрисковая"
    if has_positive_signal:
        return "умеренный позитив есть, но он пока не выглядит полным"
    if has_risk_signal:
        return "фон и риски пока ограничивают интерес к идее"

    return "данных для уверенной идеи пока маловато"


def _build_signal_view(
    sentiment: str | None,
    interest_score: int,
    has_positive_signal: bool,
    has_risk_signal: bool,
    has_fundamental_signal: bool,
    horizon_items: list[str],
) -> tuple[str, str]:
    """Builds the short entry signal and the matching tactical hint."""

    sentiment_value = (sentiment or "").strip().lower()
    horizon_text = " ".join(item.lower() for item in horizon_items)
    has_negative_sentiment = "негатив" in sentiment_value
    has_positive_sentiment = "позитив" in sentiment_value
    has_mixed_sentiment = "смешан" in sentiment_value

    if (
        interest_score >= 7
        and has_positive_signal
        and not has_risk_signal
        and (has_positive_sentiment or has_fundamental_signal)
    ):
        signal_entry = "сильный"
    elif interest_score >= 5 and has_positive_signal:
        signal_entry = "умеренный"
    else:
        signal_entry = "слабый"

    if "не для входа" in horizon_text or (has_negative_sentiment and has_risk_signal):
        signal_tactic = "сейчас разумнее наблюдать"
    elif "только спекулятивно" in horizon_text or (has_mixed_sentiment and has_risk_signal):
        signal_tactic = "идея пока не выглядит достаточно чистой"
    elif "подтверждении новостей" in horizon_text or (has_positive_signal and has_risk_signal):
        signal_tactic = "лучше дождаться подтверждения"
    elif signal_entry == "сильный" and not has_risk_signal:
        signal_tactic = "можно держать бумагу в фокусе"
    elif "проверки фундаментала" in horizon_text and has_fundamental_signal:
        signal_tactic = "история интересна после более глубокой проверки"
    elif interest_score <= 4:
        signal_tactic = "сейчас разумнее наблюдать"
    elif has_fundamental_signal and has_positive_signal:
        signal_tactic = "история интересна после более глубокой проверки"
    elif has_risk_signal:
        signal_tactic = "идея пока не выглядит достаточно чистой"
    else:
        signal_tactic = "лучше дождаться подтверждения"

    return signal_entry, signal_tactic


def _normalize_sentiment(text: str) -> str:
    """Normalizes sentiment wording to a stable nominative form."""

    replacements = {
        "умеренно позитивным": "умеренно позитивный",
        "умеренно негативным": "умеренно негативный",
        "смешанным": "смешанный",
        "скорее нейтральным": "скорее нейтральный",
        "нейтральным": "нейтральный",
        "неопределенным": "неопределенный",
        "неопределённым": "неопределенный",
        "позитивным": "позитивный",
        "негативным": "негативный",
    }

    normalized_value = text.strip()

    for source_text, target_text in replacements.items():
        if normalized_value == source_text:
            return target_text

    return normalized_value


def _parse_telegram_analysis(ticker: str, analysis_text: str) -> _TelegramFormatParts:
    """Parses the analysis text into reusable pieces for Telegram formatting."""

    normalized_text = analysis_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized_text.split("\n")]

    price_line: str | None = None
    price_match = re.search(
        r"Актуальная цена на MOEX:\s*([\d.,]+)\s+([A-Za-zА-Яа-я]+)",
        normalized_text,
    )
    if price_match:
        price_value, currency = price_match.groups()
        price_line = f"Цена: {price_value} {currency}"

    price_dynamics_items = _extract_price_dynamics_items(lines)

    sentiment_line: str | None = None
    sentiment_match = re.search(
        r"(?:новостной\s+)?фон выглядит ([^.]+?)(?:\.|$)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if sentiment_match:
        normalized_sentiment = _normalize_sentiment(sentiment_match.group(1))
        sentiment_line = f"Фон: {normalized_sentiment}"

    important_now_items = _extract_important_news(lines, limit=3)

    plus_items = _extract_growth_driver_items(lines, limit=3)
    risk_items = _extract_risk_items(lines, limit=3)

    sentiment_value: str | None = None
    if sentiment_line:
        sentiment_value = sentiment_line.replace("Фон:", "", 1).strip()

    positive_news_item, negative_news_item = _extract_news_signals(important_now_items)
    positive_theme = _summarize_news_theme(positive_news_item, "positive")
    negative_theme = _summarize_news_theme(negative_news_item, "negative")

    conclusion_text = _build_human_conclusion(
        sentiment=sentiment_value,
        has_pluses=bool(plus_items),
        has_risks=bool(risk_items),
        positive_theme=positive_theme,
        negative_theme=negative_theme,
    )

    if not conclusion_text:
        fallback_conclusion = _extract_single_value(lines, "Нейтральный вывод:")
        if fallback_conclusion:
            fallback_conclusion = re.sub(
                rf"^По\s+{re.escape(ticker)}\s+сейчас\s+можно\s+получить\s+реальную\s+цену\s+и\s+карточку\s+бумаги\s+с\s+MOEX,\s*но\s*",
                "",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bдля полноценного решения\b",
                "сейчас",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(
                r"\bважно самостоятельно проверить\b",
                "лучше дополнительно проверить",
                fallback_conclusion,
                flags=re.IGNORECASE,
            )
            fallback_conclusion = re.sub(r"\s+", " ", fallback_conclusion).strip()
            fallback_sentences = re.split(r"(?<=[.!?])\s+", fallback_conclusion, maxsplit=1)
            conclusion_text = fallback_sentences[0].strip()
            if conclusion_text:
                conclusion_text = conclusion_text[0].upper() + conclusion_text[1:]

    main_positive = positive_news_item or (plus_items[0] if plus_items else None)
    main_risk = negative_news_item or (risk_items[0] if risk_items else None)
    has_positive_signal = bool(main_positive or plus_items)
    has_risk_signal = bool(main_risk or risk_items)
    has_fundamental_signal = _has_fundamental_positive_signal(plus_items)
    horizon_items = _build_horizon_view(
        sentiment=sentiment_value,
        pluses=plus_items,
        risks=risk_items,
    )
    interest_score = _calculate_interest_score(
        sentiment=sentiment_value,
        has_positive_signal=has_positive_signal,
        has_risk_signal=has_risk_signal,
        has_fundamental_signal=has_fundamental_signal,
    )
    interest_reason = _build_interest_reason(
        sentiment=sentiment_value,
        interest_score=interest_score,
        has_positive_signal=has_positive_signal,
        has_risk_signal=has_risk_signal,
        has_fundamental_signal=has_fundamental_signal,
    )
    signal_entry, signal_tactic = _build_signal_view(
        sentiment=sentiment_value,
        interest_score=interest_score,
        has_positive_signal=has_positive_signal,
        has_risk_signal=has_risk_signal,
        has_fundamental_signal=has_fundamental_signal,
        horizon_items=horizon_items,
    )

    return {
        "normalized_text": normalized_text,
        "price_line": price_line,
        "price_dynamics_items": price_dynamics_items,
        "sentiment_line": sentiment_line,
        "sentiment_value": sentiment_value,
        "important_now_items": important_now_items,
        "plus_items": plus_items,
        "risk_items": risk_items,
        "main_positive": main_positive,
        "main_risk": main_risk,
        "main_scenario": _build_main_scenario(
            sentiment=sentiment_value,
            has_pluses=bool(plus_items),
            has_risks=bool(risk_items),
            positive_news=positive_news_item,
            negative_news=negative_news_item,
        ),
        "interest_score": interest_score,
        "interest_reason": interest_reason,
        "signal_entry": signal_entry,
        "signal_tactic": signal_tactic,
        "horizon_items": horizon_items,
        "conclusion_text": conclusion_text,
    }


def _build_main_points(parts: _TelegramFormatParts) -> list[str]:
    """Builds the short 'Главное' block items."""

    main_points: list[str] = []

    if parts["main_positive"]:
        main_points.append(f"• Позитив: {parts['main_positive']}")
    if parts["main_risk"]:
        main_points.append(f"• Риск: {parts['main_risk']}")
    if parts["main_scenario"]:
        main_points.append(f"• Сценарий: {parts['main_scenario']}")

    return main_points


def _build_telegram_blocks(parts: _TelegramFormatParts) -> list[str]:
    """Assembles the final Telegram blocks in the same order as before."""

    blocks: list[str] = []

    if parts["price_dynamics_items"]:
        if parts["price_line"]:
            blocks.append(parts["price_line"])

        blocks.append(
            "Динамика:\n"
            + "\n".join(f"• {item}" for item in parts["price_dynamics_items"])
        )

        if parts["sentiment_line"]:
            blocks.append(parts["sentiment_line"])
    else:
        intro_lines = [line for line in (parts["price_line"], parts["sentiment_line"]) if line]
        if intro_lines:
            blocks.append("\n".join(intro_lines))

    if parts["important_now_items"]:
        blocks.append(
            "Что важно сейчас:\n"
            + "\n".join(f"• {item}" for item in parts["important_now_items"])
        )

    main_points = _build_main_points(parts)
    if main_points:
        blocks.append("Главное:\n" + "\n".join(main_points))
    else:
        if parts["plus_items"]:
            blocks.append("Плюсы:\n" + "\n".join(f"• {item}" for item in parts["plus_items"]))

        if parts["risk_items"]:
            blocks.append("Риски:\n" + "\n".join(f"• {item}" for item in parts["risk_items"]))

    blocks.append(
        "Оценка:\n"
        + "\n".join(
            [
                f"• Интерес: {parts['interest_score']}/10",
                f"• Почему: {parts['interest_reason']}",
            ]
        )
    )
    blocks.append(
        "Сигнал:\n"
        + "\n".join(
            [
                f"• Вход: {parts['signal_entry']}",
                f"• Тактика: {parts['signal_tactic']}",
            ]
        )
    )

    if parts["horizon_items"]:
        blocks.append("Горизонт:\n" + "\n".join(parts["horizon_items"]))

    if parts["conclusion_text"]:
        blocks.append(f"Вывод:\n{parts['conclusion_text']}")

    if not blocks:
        blocks.append(parts["normalized_text"])

    return blocks


def format_for_telegram(result: dict[str, str | None]) -> str:
    """Formats an analysis result into a short Telegram-friendly message."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text")

    if error:
        return f"Не удалось выполнить анализ по тикеру {ticker}: {error}"

    if not analysis_text:
        return f"Не удалось получить результат анализа по тикеру {ticker}."

    parts = _parse_telegram_analysis(ticker, analysis_text)
    blocks = _build_telegram_blocks(parts)
    return f"{ticker} — краткий разбор\n\n" + "\n\n".join(blocks)


def _prepare_telegram_result(
    result: dict[str, str | None],
) -> tuple[str, _TelegramFormatParts | None, str | None]:
    """Validates the adapter result and prepares parsed parts for Telegram views."""

    ticker = (result.get("ticker") or "").strip().upper() or "UNKNOWN"
    error = (result.get("error") or "").strip()
    analysis_text = result.get("analysis_text")

    if error:
        return ticker, None, f"Не удалось выполнить анализ по тикеру {ticker}: {error}"

    if not analysis_text:
        return ticker, None, f"Не удалось получить результат анализа по тикеру {ticker}."

    return ticker, _parse_telegram_analysis(ticker, analysis_text), None


def _build_news_short_line(parts: _TelegramFormatParts) -> str:
    """Builds a short one-line summary for the news-focused response."""

    sentiment_value = (parts["sentiment_value"] or "").strip().lower()

    if parts["main_positive"] and parts["main_risk"]:
        return "Фон по новостям сейчас противоречивый."
    if "негатив" in sentiment_value:
        return "Фон по новостям сейчас скорее сдержанный."
    if "позитив" in sentiment_value:
        return "Фон по новостям сейчас скорее поддерживающий."
    if "смешан" in sentiment_value:
        return "Фон по новостям сейчас противоречивый."
    if "нейтрал" in sentiment_value:
        return "Фон по новостям сейчас ближе к нейтральному."
    if parts["main_positive"]:
        return "По новостям сейчас есть поддерживающие сигналы."
    if parts["main_risk"]:
        return "По новостям сейчас важнее смотреть на риски."
    return "По новостям сейчас сильных сигналов немного."


def _build_risks_short_line(parts: _TelegramFormatParts) -> str:
    """Builds a short summary for the risks-focused response."""

    if parts["main_risk"] and parts["main_positive"]:
        return "Ключевые риски по бумаге заметны, хотя поддерживающие сигналы тоже есть."
    if parts["main_risk"]:
        return "Ключевой риск по бумаге пока не снят."
    if parts["risk_items"]:
        return "По бумаге есть риск-факторы, за которыми стоит следить отдельно."
    return "Явных сильных риск-сигналов в текущем тексте немного."


def _first_sentence(text: str | None) -> str | None:
    """Returns the first sentence from a text block when possible."""

    if not text:
        return None

    normalized_text = re.sub(r"\s+", " ", text).strip()
    if not normalized_text:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", normalized_text, maxsplit=1)
    return sentences[0].strip()


def _collect_unique_items(*groups: list[str], limit: int) -> list[str]:
    """Collects unique items from several ordered groups with a size limit."""

    collected: list[str] = []

    for group in groups:
        for item in group:
            if item and item not in collected:
                collected.append(item)
            if len(collected) == limit:
                return collected

    return collected


def _build_idea_intro(parts: _TelegramFormatParts) -> str:
    """Builds the opening sentence for the idea-focused response."""

    if parts["main_scenario"]:
        return parts["main_scenario"]

    conclusion_text = _first_sentence(parts["conclusion_text"])
    if conclusion_text:
        return conclusion_text

    sentiment_value = (parts["sentiment_value"] or "").strip().lower()
    if "негатив" in sentiment_value:
        return "По бумаге пока важнее контроль рисков, чем быстрые выводы."
    if "позитив" in sentiment_value:
        return "По бумаге есть сигналы, за которыми имеет смысл следить."
    if "смешан" in sentiment_value:
        return "По бумаге сейчас есть и поддержка, и поводы для осторожности."

    return "По бумаге пока лучше смотреть на баланс факторов без спешки."


def format_news_for_telegram(result: dict[str, str | None]) -> str:
    """Formats the analysis into a Telegram message focused only on news."""

    ticker, parts, error_message = _prepare_telegram_result(result)
    if error_message:
        return error_message

    assert parts is not None
    lines = [line.rstrip() for line in parts["normalized_text"].split("\n")]
    news_items = _extract_important_news(lines, limit=5)

    if not news_items:
        return (
            f"{ticker} — важные новости\n\n"
            "Инвестиционно значимых новостей по бумаге сейчас не удалось выделить.\n\n"
            f"Коротко:\n{_build_news_short_line(parts)}"
        )

    return (
        f"{ticker} — важные новости\n\n"
        + "\n".join(f"• {item}" for item in news_items)
        + f"\n\nКоротко:\n{_build_news_short_line(parts)}"
    )


def format_risks_for_telegram(result: dict[str, str | None]) -> str:
    """Formats the analysis into a Telegram message focused on the risk profile."""

    ticker, parts, error_message = _prepare_telegram_result(result)
    if error_message:
        return error_message

    assert parts is not None

    main_risk = parts["main_risk"]
    extra_risks = _collect_unique_items(parts["risk_items"], limit=4)
    if main_risk and main_risk in extra_risks:
        extra_risks = [item for item in extra_risks if item != main_risk]
    extra_risks = extra_risks[:3]

    blocks = [f"{ticker} — риски"]

    if main_risk:
        blocks.append(f"Главный риск:\n• {main_risk}")
    elif extra_risks:
        blocks.append(f"Главный риск:\n• {extra_risks[0]}")
        extra_risks = extra_risks[1:]
    else:
        blocks.append("Главный риск:\n• Явный доминирующий риск по текущему тексту не выделился.")

    if extra_risks:
        blocks.append("Что ещё важно:\n" + "\n".join(f"• {item}" for item in extra_risks))

    blocks.append(f"Коротко:\n{_build_risks_short_line(parts)}")
    return "\n\n".join(blocks)


def format_idea_for_telegram(result: dict[str, str | None]) -> str:
    """Formats the analysis into a Telegram message focused on the current idea."""

    ticker, parts, error_message = _prepare_telegram_result(result)
    if error_message:
        return error_message

    assert parts is not None

    support_items = _collect_unique_items(
        [parts["main_positive"]] if parts["main_positive"] else [],
        parts["plus_items"],
        limit=2,
    )
    obstacle_items = _collect_unique_items(
        [parts["main_risk"]] if parts["main_risk"] else [],
        parts["risk_items"],
        limit=2,
    )

    blocks = [f"{ticker} — идея по бумаге", _build_idea_intro(parts)]

    if support_items:
        blocks.append("Что поддерживает:\n" + "\n".join(f"• {item}" for item in support_items))

    if obstacle_items:
        blocks.append("Что мешает:\n" + "\n".join(f"• {item}" for item in obstacle_items))

    if parts["horizon_items"]:
        blocks.append("Как смотреть:\n" + "\n".join(parts["horizon_items"]))

    return "\n\n".join(blocks)


def format_full_for_telegram(result: dict[str, str | None]) -> str:
    """Formats the analysis into a more detailed Telegram message."""

    ticker, parts, error_message = _prepare_telegram_result(result)
    if error_message:
        return error_message

    assert parts is not None
    lines = [line.rstrip() for line in parts["normalized_text"].split("\n")]
    short_summary = _extract_short_summary_for_telegram(lines, ticker)
    news_items = _extract_important_news(lines, limit=5)
    plus_items = _collect_unique_items(
        [parts["main_positive"]] if parts["main_positive"] else [],
        _extract_growth_driver_items(lines, limit=3),
        limit=3,
    )
    risk_items = _collect_unique_items(
        [parts["main_risk"]] if parts["main_risk"] else [],
        _extract_risk_items(lines, limit=3),
        limit=3,
    )

    blocks: list[str] = []

    if short_summary:
        blocks.append(f"Кратко по бумаге:\n{short_summary}")

    if parts["price_line"]:
        blocks.append(parts["price_line"])

    if parts["price_dynamics_items"]:
        blocks.append("Динамика:\n" + "\n".join(f"• {item}" for item in parts["price_dynamics_items"]))

    if parts["sentiment_line"]:
        blocks.append(parts["sentiment_line"])

    if news_items:
        blocks.append("Что важно сейчас:\n" + "\n".join(f"• {item}" for item in news_items))

    if plus_items:
        blocks.append("Позитив:\n" + "\n".join(f"• {item}" for item in plus_items))

    if risk_items:
        blocks.append("Риски:\n" + "\n".join(f"• {item}" for item in risk_items))

    blocks.append(
        "Оценка:\n"
        + "\n".join(
            [
                f"• Интерес: {parts['interest_score']}/10",
                f"• Почему: {parts['interest_reason']}",
            ]
        )
    )
    blocks.append(
        "Сигнал:\n"
        + "\n".join(
            [
                f"• Вход: {parts['signal_entry']}",
                f"• Тактика: {parts['signal_tactic']}",
            ]
        )
    )

    if parts["horizon_items"]:
        blocks.append("Горизонт:\n" + "\n".join(parts["horizon_items"]))

    if parts["conclusion_text"]:
        blocks.append(f"Вывод:\n{parts['conclusion_text']}")

    if not blocks:
        blocks.append(parts["normalized_text"])

    return f"{ticker} — подробный разбор\n\n" + "\n\n".join(blocks)


def build_stock_analysis(ticker: str) -> str:
    """Формирует простой русскоязычный анализ по тикеру.

    Важно: этот модуль отвечает только за смысл и формат ответа.
    Откуда именно пришли данные, решают модули внутри папки `tools`.
    Такой подход удобен: позже можно подключить реальный API и почти
    не менять код, который собирает итоговый анализ.
    """

    stock_data = get_stock_snapshot(ticker)

    # Если биржа не нашла бумагу или не ответила, честно показываем это пользователю.
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

    # Возвращаем готовый многострочный текст, который удобно показать в CLI.
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
            "В более релевантных новостях есть и сильные, и осторожные сигналы, поэтому стоит смотреть не только на один заголовок, а на весь фон."
        )

    return drivers


def _build_risks(stock_data: dict, news_summary: dict) -> list[str]:
    """Возвращает базовые риски, понятные даже без реального API."""

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
        risks.append("Новостной фон выглядит смешанным: в публикациях могут одновременно встречаться и позитивные, и негативные сигналы.")

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

        lines.append(f"{relevance_prefix}{issuer_prefix} {date_prefix}{item['title']}{source_suffix}{topics_suffix}")

    return lines


if __name__ == "__main__":
    import sys

    ticker = "SBER"

    if len(sys.argv) > 1:
        ticker = sys.argv[1]

    print(f"Запуск анализа для {ticker}")
    result = build_stock_analysis(ticker)
    print(result)
