"""Smart screener — filters all tickers by momentum before LLM analysis."""

from __future__ import annotations

import urllib.request
import urllib.error
import json


ALL_TICKERS = [
    # Банки
    "SBER", "VTBR", "TCSG", "BSPB",
    # Нефть и газ
    "LKOH", "GAZP", "ROSN", "NVTK", "TATN", "SNGS",
    # Металлы
    "GMKN", "NLMK", "MAGN", "CHMF", "ALRS",
    # Технологии
    "YNDX", "OZON", "VKCO",
    # Другие
    "MTSS", "AFLT", "PIKK", "FEES",
]

MOEX_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares"
    "/securities.json?iss.meta=off&iss.only=marketdata"
    "&marketdata.columns=SECID,LAST,CHANGE,LASTTOPREVPRICE"
)

TIMEOUT = 20


def _fetch_moex_snapshot() -> dict[str, dict]:
    """Fetches current price and daily change for all tickers from MOEX."""
    result: dict[str, dict] = {}

    try:
        req = urllib.request.Request(
            MOEX_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))

        columns = data["marketdata"]["columns"]
        rows = data["marketdata"]["data"]

        idx_secid = columns.index("SECID")
        idx_last = columns.index("LAST")
        idx_change = columns.index("CHANGE")
        idx_pct = columns.index("LASTTOPREVPRICE")

        for row in rows:
            secid = row[idx_secid]
            if secid not in ALL_TICKERS:
                continue

            last = row[idx_last]
            change = row[idx_change]
            pct = row[idx_pct]

            result[secid] = {
                "price": last,
                "change": change,
                "change_pct": pct,
            }

    except Exception as e:
        print("Ошибка получения данных MOEX: " + str(e))

    return result


def _score_ticker(ticker: str, data: dict) -> float:
    """
    Scores a ticker for today's idea selection.
    Higher = more interesting signal.
    Uses daily change % as primary signal.
    Positive momentum preferred but strong negative also flagged.
    """
    pct = data.get("change_pct")
    if pct is None:
        return 0.0

    try:
        pct_float = float(pct)
    except (TypeError, ValueError):
        return 0.0

    # Сильный рост — высокий балл
    if pct_float > 0:
        return pct_float * 1.5

    # Сильное падение тоже интересно (возможный отскок)
    if pct_float < -2.0:
        return abs(pct_float) * 0.8

    return abs(pct_float) * 0.3


def get_top_tickers(limit: int = 5) -> list[dict]:
    """
    Returns top N tickers by momentum signal with price data.
    Falls back to default list if MOEX is unavailable.
    """
    snapshot = _fetch_moex_snapshot()

    if not snapshot:
        # Fallback — возвращаем дефолтный список без цен
        return [
            {"ticker": t, "price": None, "change_pct": None, "score": 0}
            for t in ALL_TICKERS[:limit]
        ]

    scored = []
    for ticker in ALL_TICKERS:
        if ticker not in snapshot:
            continue

        data = snapshot[ticker]
        score = _score_ticker(ticker, data)

        scored.append({
            "ticker": ticker,
            "price": data.get("price"),
            "change_pct": data.get("change_pct"),
            "score": score,
        })

    # Сортируем по баллу
    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:limit]


def format_screener_summary(top: list[dict]) -> str:
    """Builds a short text summary of screener results."""
    if not top:
        return "Скринер не вернул данные."

    lines = ["📡 Скринер отобрал топ-" + str(len(top)) + " бумаг:"]
    for item in top:
        ticker = item["ticker"]
        price = item["price"]
        pct = item["change_pct"]

        price_str = (str(round(float(price), 2)) + " руб.") if price else "—"
        pct_str = ""
        if pct is not None:
            try:
                pct_str = (" (" + ("+" if float(pct) >= 0 else "") + str(round(float(pct), 1)) + "%)")
            except Exception:
                pass

        lines.append("• " + ticker + ": " + price_str + pct_str)

    return "\n".join(lines)
