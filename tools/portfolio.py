"""Portfolio access layer for future portfolio analytics."""

import os


DEFAULT_PORTFOLIO_PROVIDER = "stub"


def get_portfolio_context(ticker: str) -> dict:
    """Публичная точка входа для портфельного контекста по бумаге."""

    provider = get_portfolio_provider()

    if provider == DEFAULT_PORTFOLIO_PROVIDER:
        return get_portfolio_context_stub(ticker)

    # Позже здесь можно будет подключить файл портфеля, базу данных
    # или API брокера. Пока делаем безопасный резервный ответ.
    return get_portfolio_context_from_source(ticker, provider)


def get_portfolio_provider() -> str:
    """Читает источник портфельных данных из переменных окружения."""

    provider = os.getenv("PORTFOLIO_PROVIDER", DEFAULT_PORTFOLIO_PROVIDER)
    normalized_provider = provider.strip().lower()
    return normalized_provider or DEFAULT_PORTFOLIO_PROVIDER


def get_portfolio_context_stub(ticker: str) -> dict:
    """Возвращает фейковый портфельный контекст."""

    return {
        "ticker": ticker,
        "note": (
            "В текущем MVP данные портфеля не подключены, поэтому важно "
            "самостоятельно проверить, не будет ли позиция слишком большой "
            "относительно остальных активов."
        ),
        "source": "stub",
        "is_stub": True,
    }


def get_portfolio_context_from_source(ticker: str, provider: str) -> dict:
    """Заготовка для будущего анализа влияния бумаги на портфель."""

    # Позже здесь можно добавить расчет доли позиции, концентрации и риска.
    fallback_data = get_portfolio_context_stub(ticker)
    fallback_data["source"] = f"stub_fallback_for_{provider}"
    return fallback_data
