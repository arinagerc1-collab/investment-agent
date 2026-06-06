"""CLI entrypoint for the investment-agent MVP."""

from agent import analyze_ticker


def main() -> None:
    """Запускает простой консольный сценарий анализа акции."""
    print("Investment Agent MVP")
    print("Введите тикер акции, чтобы получить базовый анализ.\n")

    # Берем тикер из ввода пользователя и приводим его к верхнему регистру.
    ticker = input("Тикер: ").strip().upper()

    if not ticker:
        print("Тикер не введен. Попробуйте еще раз и укажите, например, SBER.")
        return

    # Передаем тикер в модуль агента, который собирает итоговый текст ответа.
    result = analyze_ticker(ticker)

    print("\nАнализ бумаги")
    print("=" * 40)
    if result["error"]:
        print(f"РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹РїРѕР»РЅРёС‚СЊ Р°РЅР°Р»РёР·: {result['error']}")
        return

    print(result["analysis_text"])


if __name__ == "__main__":
    # Точка входа в программу при запуске файла через `python main.py`.
    main()
