"""Market data access layer for MOEX stock quotes and security details."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_MARKET_DATA_PROVIDER = "moex"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_MOEX_ISS_BASE_URL = "https://iss.moex.com/iss"


class MoexIssError(Exception):
    """Ошибка при работе с официальным API Московской биржи."""


def get_stock_snapshot(ticker: str) -> dict:
    """Публичная точка входа для получения данных по акции.

    По умолчанию проект пытается получить реальные данные из MOEX ISS API.
    Если нужен старый локальный режим для отладки, можно вручную указать
    `MARKET_DATA_PROVIDER=stub`.
    """

    normalized_ticker = ticker.strip().upper()
    provider = get_market_data_provider()

    if not normalized_ticker:
        return _build_error_snapshot(
            ticker="",
            message="Тикер не указан. Введите тикер российской акции MOEX, например SBER.",
            provider=provider,
        )

    if provider == "stub":
        return get_stock_snapshot_stub(normalized_ticker)

    if provider != "moex":
        return _build_error_snapshot(
            ticker=normalized_ticker,
            message=(
                f"Провайдер рыночных данных '{provider}' не поддерживается. "
                "Сейчас доступны только MOEX ISS API и локальный stub."
            ),
            provider=provider,
        )

    return get_stock_snapshot_from_moex(normalized_ticker)


def get_market_data_provider() -> str:
    """Читает название провайдера из переменных окружения."""

    provider = os.getenv("MARKET_DATA_PROVIDER", DEFAULT_MARKET_DATA_PROVIDER)
    normalized_provider = provider.strip().lower()
    return normalized_provider or DEFAULT_MARKET_DATA_PROVIDER


def get_stock_snapshot_stub(ticker: str) -> dict:
    """Возвращает старые фейковые данные для локальной отладки."""

    return {
        "ticker": ticker,
        "found": True,
        "price": 250.0,
        "price_source": "stub",
        "currency": "RUB",
        "sector": "Финансовый сектор",
        "short_name": "Тестовая бумага",
        "full_name": "Тестовая бумага для локальной отладки",
        "description": "Фейковая карточка бумаги из локальной заглушки.",
        "listing_level": None,
        "board_id": "TQBR",
        "board_title": "Тестовый режим торгов",
        "trading_status": None,
        "previous_close": None,
        "price_dynamics": [],
        "source": "stub",
        "provider": "stub",
        "is_stub": True,
        "message": None,
        "notes": ["Используются локальные тестовые данные, а не MOEX ISS API."],
    }


def get_stock_snapshot_from_moex(ticker: str) -> dict:
    """Получает реальные данные по акции через официальный MOEX ISS API.

    Поддерживаются только акции рынка shares Московской биржи. Если тикер
    не найден или относится к другому рынку, функция честно сообщает об этом.
    """

    try:
        quotes_payload = _fetch_json(_build_moex_quotes_url(ticker))
    except MoexIssError as error:
        return _build_error_snapshot(
            ticker=ticker,
            message=(
                f"Не удалось получить данные по {ticker} из MOEX ISS API. "
                f"Причина: {error}"
            ),
            provider="moex",
        )

    security_row = _get_first_row(quotes_payload.get("securities", {}))
    marketdata_row = _get_first_row(quotes_payload.get("marketdata", {}))

    if not security_row:
        return _build_error_snapshot(
            ticker=ticker,
            message=(
                f"По тикеру {ticker} не найдена акция на рынке MOEX shares. "
                "Проверьте тикер: сейчас поддерживаются только акции MOEX, "
                "например SBER, GAZP, LKOH."
            ),
            provider="moex",
        )

    notes: list[str] = []
    description_map: dict[str, Any] = {}
    board_row: dict[str, Any] = {}

    try:
        description_payload = _fetch_json(_build_moex_description_url(ticker))
        description_map = _description_table_to_dict(description_payload.get("description", {}))
        board_row = _get_first_row(description_payload.get("boards", {}))
    except MoexIssError as error:
        notes.append(
            "MOEX ISS API не вернул расширенное описание бумаги. "
            f"Причина: {error}"
        )

    price_value, price_field = _select_best_price(marketdata_row, security_row)
    sector_value = _extract_sector(security_row, description_map)
    price_dynamics = _get_price_dynamics_from_moex(ticker, price_value)

    if sector_value is None:
        notes.append("MOEX ISS API не вернул сектор для этой бумаги.")

    if price_value is None:
        notes.append(
            "MOEX ISS API нашел бумагу, но не вернул актуальную цену. "
            "Это бывает, если торги недоступны или в ответе нет ценового поля."
        )

    return {
        "ticker": ticker,
        "found": True,
        "price": price_value,
        "price_source": price_field,
        "currency": _normalize_currency(
            _first_not_empty(
                board_row.get("currencyid"),
                security_row.get("CURRENCYID"),
                security_row.get("FACEUNIT"),
            )
        ),
        "sector": sector_value,
        "short_name": _first_not_empty(description_map.get("SHORTNAME"), security_row.get("SHORTNAME")),
        "full_name": _first_not_empty(description_map.get("NAME"), security_row.get("SECNAME")),
        "issue_name": description_map.get("ISSUENAME"),
        "type_name": description_map.get("TYPENAME"),
        "description": _build_security_description(description_map),
        "listing_level": _first_not_empty(description_map.get("LISTLEVEL"), security_row.get("LISTLEVEL")),
        "board_id": _first_not_empty(board_row.get("boardid"), security_row.get("BOARDID")),
        "board_title": _first_not_empty(board_row.get("title"), security_row.get("BOARDNAME")),
        "trading_status": marketdata_row.get("TRADINGSTATUS"),
        "previous_close": _first_numeric(
            marketdata_row.get("LCLOSEPRICE"),
            security_row.get("PREVLEGALCLOSEPRICE"),
            security_row.get("PREVPRICE"),
        ),
        "price_dynamics": price_dynamics,
        "isin": _first_not_empty(description_map.get("ISIN"), security_row.get("ISIN")),
        "source": "moex",
        "provider": "moex",
        "is_stub": False,
        "message": None,
        "notes": notes,
    }


def _build_moex_quotes_url(ticker: str) -> str:
    """Собирает URL для котировок акции на основном режиме MOEX."""

    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "marketprice_board": "1",
        "primary_board": "1",
    }
    return _build_moex_url(f"engines/stock/markets/shares/securities/{ticker}.json", params)


def _build_moex_description_url(ticker: str) -> str:
    """Собирает URL для карточки бумаги и основной торговой доски."""

    params = {
        "iss.meta": "off",
        "iss.only": "description,boards",
        "primary_board": "1",
    }
    return _build_moex_url(f"securities/{ticker}.json", params)


def _build_moex_candles_url(
    ticker: str,
    interval: int,
    date_from: datetime,
    date_till: datetime,
) -> str:
    """Собирает URL для свечей MOEX по основному режиму торгов."""

    params = {
        "iss.meta": "off",
        "iss.only": "candles",
        "from": date_from.strftime("%Y-%m-%d"),
        "till": date_till.strftime("%Y-%m-%d"),
        "interval": str(interval),
    }
    return _build_moex_url(f"engines/stock/markets/shares/securities/{ticker}/candles.json", params)


def _build_moex_url(path: str, params: dict[str, str]) -> str:
    """Собирает полный URL к MOEX ISS API."""

    base_url = os.getenv("MOEX_ISS_BASE_URL", DEFAULT_MOEX_ISS_BASE_URL).rstrip("/")
    query_string = urlencode(params)
    return f"{base_url}/{path}?{query_string}"


def _get_price_dynamics_from_moex(ticker: str, current_price: float | None) -> list[dict[str, Any]]:
    """Собирает динамику цены на доступных горизонтах без ошибок для основного анализа."""

    if current_price is None:
        return []

    daily_candles = _load_moex_candles(ticker, interval=24, days_back=21)
    intraday_candles = _load_moex_candles(ticker, interval=1, days_back=5)
    items: list[dict[str, Any]] = []
    used_reference_points: set[str] = set()

    if daily_candles:
        latest_daily_candle = daily_candles[-1]
        anchor_date = latest_daily_candle["begin"].date()

        _append_price_dynamics_item(
            items,
            label="1д",
            current_price=current_price,
            reference_candle=_find_candle_at_or_before_date(
                daily_candles,
                anchor_date - timedelta(days=1),
            ),
            used_reference_points=used_reference_points,
        )
        _append_price_dynamics_item(
            items,
            label="1н",
            current_price=current_price,
            reference_candle=_find_candle_at_or_before_date(
                daily_candles,
                anchor_date - timedelta(days=7),
            ),
            used_reference_points=used_reference_points,
        )

    if intraday_candles:
        latest_intraday_candle = intraday_candles[-1]
        anchor_time = latest_intraday_candle["end"]

        _append_price_dynamics_item(
            items,
            label="15м",
            current_price=current_price,
            reference_candle=_find_candle_at_or_before_time(
                intraday_candles,
                anchor_time - timedelta(minutes=15),
            ),
            used_reference_points=used_reference_points,
        )
        _append_price_dynamics_item(
            items,
            label="1ч",
            current_price=current_price,
            reference_candle=_find_candle_at_or_before_time(
                intraday_candles,
                anchor_time - timedelta(hours=1),
            ),
            used_reference_points=used_reference_points,
        )
        _append_price_dynamics_item(
            items,
            label="1м",
            current_price=current_price,
            reference_candle=_find_candle_at_or_before_time(
                intraday_candles,
                anchor_time - timedelta(minutes=1),
            ),
            used_reference_points=used_reference_points,
        )

    return items


def _load_moex_candles(ticker: str, interval: int, days_back: int) -> list[dict[str, Any]]:
    """Загружает свечи MOEX и тихо возвращает пустой список, если данные недоступны."""

    today = datetime.now()
    date_from = today - timedelta(days=days_back)

    try:
        payload = _fetch_json(_build_moex_candles_url(ticker, interval, date_from, today))
    except MoexIssError:
        return []

    return _normalize_candles(payload.get("candles", {}))


def _normalize_candles(table: dict) -> list[dict[str, Any]]:
    """Преобразует свечи MOEX к удобному списку словарей."""

    items: list[dict[str, Any]] = []

    for row in _rows_to_dicts(table):
        begin_value = _parse_moex_datetime(row.get("begin"))
        end_value = _parse_moex_datetime(row.get("end"))
        close_value = _to_float(row.get("close"))

        if begin_value is None or end_value is None or close_value is None:
            continue

        items.append(
            {
                "begin": begin_value,
                "end": end_value,
                "close": close_value,
            }
        )

    return items


def _parse_moex_datetime(value: Any) -> datetime | None:
    """Безопасно разбирает дату и время из свечи MOEX."""

    if value is None:
        return None

    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _find_candle_at_or_before_date(
    candles: list[dict[str, Any]],
    target_date: date,
) -> dict[str, Any] | None:
    """Находит последнюю свечу не позже нужной календарной даты."""

    for candle in reversed(candles):
        if candle["begin"].date() <= target_date:
            return candle

    return None


def _find_candle_at_or_before_time(
    candles: list[dict[str, Any]],
    target_time: datetime,
) -> dict[str, Any] | None:
    """Находит последнюю свечу не позже нужного времени."""

    for candle in reversed(candles):
        if candle["end"] <= target_time:
            return candle

    return None


def _append_price_dynamics_item(
    items: list[dict[str, Any]],
    label: str,
    current_price: float,
    reference_candle: dict[str, Any] | None,
    used_reference_points: set[str],
) -> None:
    """Добавляет рассчитанную динамику в итоговый список, если есть база сравнения."""

    if reference_candle is None:
        return

    reference_price = _to_float(reference_candle.get("close"))
    if reference_price in (None, 0):
        return

    reference_at = reference_candle.get("end")
    if not isinstance(reference_at, datetime):
        return

    reference_key = reference_at.isoformat(sep=" ")
    if reference_key in used_reference_points:
        return

    change_abs = current_price - reference_price
    change_pct = change_abs / reference_price * 100
    used_reference_points.add(reference_key)

    items.append(
        {
            "label": label,
            "reference_price": reference_price,
            "reference_at": reference_key,
            "change_abs": change_abs,
            "change_pct": change_pct,
        }
    )


def _fetch_json(url: str) -> dict:
    """Выполняет GET-запрос и возвращает JSON в виде словаря."""

    timeout_seconds = _get_request_timeout_seconds()
    request = Request(
        url=url,
        headers={
            "User-Agent": "investment-agent/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise MoexIssError(f"HTTP {error.code} от сервера MOEX") from error
    except URLError as error:
        raise MoexIssError("сервер MOEX недоступен или нет подключения к интернету") from error
    except TimeoutError as error:
        raise MoexIssError("запрос к MOEX превысил время ожидания") from error
    except OSError as error:
        raise MoexIssError("не удалось установить соединение с MOEX") from error

    if not body.strip():
        raise MoexIssError("сервер MOEX вернул пустой ответ")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise MoexIssError("сервер MOEX вернул некорректный JSON") from error

    if not isinstance(payload, dict):
        raise MoexIssError("сервер MOEX вернул неожиданный формат данных")

    return payload


def _get_request_timeout_seconds() -> int:
    """Читает таймаут запроса из переменных окружения."""

    raw_timeout = os.getenv("REQUEST_TIMEOUT_SECONDS", str(DEFAULT_REQUEST_TIMEOUT_SECONDS))

    try:
        timeout_seconds = int(raw_timeout)
    except ValueError:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS

    return max(1, timeout_seconds)


def _get_first_row(table: dict) -> dict[str, Any]:
    """Преобразует первую строку табличного ответа MOEX в словарь."""

    rows = _rows_to_dicts(table)
    return rows[0] if rows else {}


def _rows_to_dicts(table: dict) -> list[dict[str, Any]]:
    """Преобразует таблицу MOEX вида columns + data в список словарей."""

    columns = table.get("columns", [])
    rows = table.get("data", [])

    if not columns or not rows:
        return []

    return [dict(zip(columns, row)) for row in rows]


def _description_table_to_dict(table: dict) -> dict[str, Any]:
    """Преобразует описание бумаги MOEX в удобный словарь name -> value."""

    items = _rows_to_dicts(table)
    return {item["name"]: item.get("value") for item in items if item.get("name")}


def _select_best_price(marketdata_row: dict, security_row: dict) -> tuple[float | None, str | None]:
    """Выбирает лучшее доступное ценовое поле из ответа MOEX.

    Биржа может вернуть несколько вариантов цены. Мы берем первое доступное
    значение в порядке убывания полезности для пользователя.
    """

    candidates = [
        ("LAST", marketdata_row.get("LAST")),
        ("MARKETPRICE2", marketdata_row.get("MARKETPRICE2")),
        ("MARKETPRICE", marketdata_row.get("MARKETPRICE")),
        ("LCURRENTPRICE", marketdata_row.get("LCURRENTPRICE")),
        ("LCLOSEPRICE", marketdata_row.get("LCLOSEPRICE")),
        ("PREVLEGALCLOSEPRICE", security_row.get("PREVLEGALCLOSEPRICE")),
        ("PREVPRICE", security_row.get("PREVPRICE")),
    ]

    for field_name, raw_value in candidates:
        numeric_value = _to_float(raw_value)
        if numeric_value is not None:
            return numeric_value, field_name

    return None, None


def _extract_sector(security_row: dict, description_map: dict[str, Any]) -> str | None:
    """Возвращает сектор, только если MOEX реально его прислал."""

    sector_value = _first_not_empty(description_map.get("SECTOR"), security_row.get("SECTORID"))

    if sector_value is None:
        return None

    return str(sector_value)


def _build_security_description(description_map: dict[str, Any]) -> str | None:
    """Собирает короткое описание бумаги из полей MOEX."""

    type_name = _first_not_empty(description_map.get("TYPENAME"))
    issue_name = _first_not_empty(description_map.get("ISSUENAME"))

    if type_name and issue_name and type_name != issue_name:
        return f"{type_name}. {issue_name}."

    if type_name:
        return f"{type_name}."

    if issue_name:
        return f"{issue_name}."

    return None


def _normalize_currency(currency_code: Any) -> str | None:
    """Нормализует валютный код из MOEX к привычному виду."""

    if currency_code is None:
        return None

    normalized = str(currency_code).strip().upper()
    replacements = {
        "SUR": "RUB",
        "RUR": "RUB",
    }
    return replacements.get(normalized, normalized)


def _first_not_empty(*values: Any) -> Any:
    """Возвращает первое непустое значение."""

    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value

    return None


def _first_numeric(*values: Any) -> float | None:
    """Возвращает первое значение, которое удалось преобразовать в число."""

    for value in values:
        numeric_value = _to_float(value)
        if numeric_value is not None:
            return numeric_value

    return None


def _to_float(value: Any) -> float | None:
    """Безопасно преобразует входное значение в float."""

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_error_snapshot(ticker: str, message: str, provider: str) -> dict:
    """Возвращает единый формат ошибки для остального проекта."""

    return {
        "ticker": ticker,
        "found": False,
        "price": None,
        "price_source": None,
        "currency": None,
        "sector": None,
        "short_name": None,
        "full_name": None,
        "issue_name": None,
        "type_name": None,
        "description": None,
        "listing_level": None,
        "board_id": None,
        "board_title": None,
        "trading_status": None,
        "previous_close": None,
        "price_dynamics": [],
        "isin": None,
        "source": provider,
        "provider": provider,
        "is_stub": provider == "stub",
        "message": message,
        "notes": [],
    }
