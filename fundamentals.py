"""Fundamentals module — fetches key financial metrics from Smart-Lab."""

from __future__ import annotations

import re
import urllib.request
import urllib.error


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

TIMEOUT = 15


def _fetch_url(url: str) -> str:
    """Fetches a URL and returns the HTML as text."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _clean(text: str) -> str:
    """Removes HTML tags and extra whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _find_value(html: str, pattern: str) -> str | None:
    """Finds a value in HTML using a regex pattern."""
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match:
        return _clean(match.group(1)).strip()
    return None


def get_fundamentals(ticker: str) -> dict:
    """
    Returns key fundamental metrics for a ticker from Smart-Lab.

    Returns a dict with keys:
    - pe, pb, ps, ev_ebitda: valuation multiples (str or None)
    - roe, net_margin: profitability (str or None)
    - div_yield: dividend yield % (str or None)
    - div_per_share: dividend per share rub (str or None)
    - div_date: next dividend date (str or None)
    - revenue_growth: revenue growth yoy (str or None)
    - debt_equity: debt/equity ratio (str or None)
    - available: bool
    - summary: short human-readable summary
    """
    result: dict = {
        "pe": None,
        "pb": None,
        "ps": None,
        "ev_ebitda": None,
        "roe": None,
        "net_margin": None,
        "div_yield": None,
        "div_per_share": None,
        "div_date": None,
        "revenue_growth": None,
        "debt_equity": None,
        "available": False,
        "summary": "Фундаментальные данные недоступны.",
    }

    ticker_upper = ticker.strip().upper()

    # Страница с мультипликаторами МСФО
    url_msfo = f"https://smart-lab.ru/q/{ticker_upper}/f/y/"
    html_msfo = _fetch_url(url_msfo)

    # Страница с дивидендами
    url_div = f"https://smart-lab.ru/q/{ticker_upper}/dividend/"
    html_div = _fetch_url(url_div)

    if not html_msfo and not html_div:
        return result

    result["available"] = True

    # P/E
    pe = _find_value(
        html_msfo,
        r"P/E[^<]*</[^>]+>\s*<[^>]+>\s*([\d.,–\-]+)"
    )
    if pe:
        result["pe"] = pe

    # P/BV
    pb = _find_value(
        html_msfo,
        r"P/BV[^<]*</[^>]+>\s*<[^>]+>\s*([\d.,–\-]+)"
    )
    if pb:
        result["pb"] = pb

    # P/S
    ps = _find_value(
        html_msfo,
        r"P/S[^<]*</[^>]+>\s*<[^>]+>\s*([\d.,–\-]+)"
    )
    if ps:
        result["ps"] = ps

    # EV/EBITDA
    ev = _find_value(
        html_msfo,
        r"EV/EBITDA[^<]*</[^>]+>\s*<[^>]+>\s*([\d.,–\-]+)"
    )
    if ev:
        result["ev_ebitda"] = ev

    # ROE
    roe = _find_value(
        html_msfo,
        r"ROE[^<]*</[^>]+>\s*<[^>]+>\s*([\d.,–\-]+\s*%?)"
    )
    if roe:
        result["roe"] = roe

    # Дивидендная доходность
    div_yield = _find_value(
        html_div,
        r"дивидендная доходность[^<]*?составляет\s*([\d.,]+\s*%)"
    )
    if not div_yield:
        div_yield = _find_value(
            html_div,
            r"([\d.,]+)%\s*[;\s]*дивидендная доходность"
        )
    if div_yield:
        result["div_yield"] = div_yield

    # Дивиденд на акцию — последний
    div_per_share = _find_value(
        html_div,
        r"выплатил[а]?\s+дивиденды\s+в\s+размере\s+([\d.,]+)\s+рубл"
    )
    if div_per_share:
        result["div_per_share"] = div_per_share + " руб."

    # Строим читаемое резюме
    parts = []

    if result["pe"]:
        parts.append(f"P/E: {result['pe']}")
    if result["pb"]:
        parts.append(f"P/BV: {result['pb']}")
    if result["ps"]:
        parts.append(f"P/S: {result['ps']}")
    if result["ev_ebitda"]:
        parts.append(f"EV/EBITDA: {result['ev_ebitda']}")
    if result["roe"]:
        parts.append(f"ROE: {result['roe']}")
    if result["div_yield"]:
        parts.append(f"Дивдоходность: {result['div_yield']}")
    if result["div_per_share"]:
        parts.append(f"Дивиденд: {result['div_per_share']}")

    if parts:
        result["summary"] = "Мультипликаторы: " + ", ".join(parts)
    else:
        result["summary"] = "Smart-Lab не вернул мультипликаторы для этой бумаги."

    return result


def format_fundamentals_for_prompt(ticker: str) -> str:
    """Returns a formatted string with fundamentals for LLM prompt."""
    data = get_fundamentals(ticker)

    if not data["available"]:
        return ""

    lines = ["Фундаментальные данные (Smart-Lab):"]

    if data["pe"]:
        lines.append(f"P/E = {data['pe']}")
    if data["pb"]:
        lines.append(f"P/BV = {data['pb']}")
    if data["ps"]:
        lines.append(f"P/S = {data['ps']}")
    if data["ev_ebitda"]:
        lines.append(f"EV/EBITDA = {data['ev_ebitda']}")
    if data["roe"]:
        lines.append(f"ROE = {data['roe']}")
    if data["div_yield"]:
        lines.append(f"Дивидендная доходность = {data['div_yield']}")
    if data["div_per_share"]:
        lines.append(f"Последний дивиденд = {data['div_per_share']}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)
