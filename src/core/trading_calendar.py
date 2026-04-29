# -*- coding: utf-8 -*-
# ============================================
# 交易日历模块 (Issue #373)
# ============================================

import logging
from datetime import date, datetime
from typing import Optional, Set
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_XCALS_AVAILABLE = False
try:
    import exchange_calendars as xcals
    _XCALS_AVAILABLE = True
except ImportError:
    logger.warning(
        "exchange-calendars not installed; trading day check disabled. "
        "Run: pip install exchange-calendars"
    )

MARKET_EXCHANGE = {"cn": "XSHG", "hk": "XHKG", "us": "XNYS"}
MARKET_TIMEZONE = {
    "cn": "Asia/Shanghai",
    "hk": "Asia/Hong_Kong",
    "us": "America/New_York",
}


def get_market_for_stock(code: str) -> Optional[str]:
    if not code or not isinstance(code, str):
        return None
    code = (code or "").strip().upper()
    from data_provider import is_us_stock_code, is_us_index_code, is_hk_stock_code
    if is_us_stock_code(code) or is_us_index_code(code):
        return "us"
    if is_hk_stock_code(code):
        return "hk"
    if code.isdigit() and len(code) == 6:
        return "cn"
    return None


def is_market_open(market: str, check_date: date) -> bool:
    if not _XCALS_AVAILABLE:
        return True
    ex = MARKET_EXCHANGE.get(market)
    if not ex:
        return True
    try:
        cal = xcals.get_calendar(ex)
        session = datetime(check_date.year, check_date.month, check_date.day)
        return cal.is_session(session)
    except Exception as e:
        logger.warning("is_market_open fail-open: %s", e)
        return True


def get_market_now(
    market: Optional[str], current_time: Optional[datetime] = None
) -> datetime:
    tz_name = MARKET_TIMEZONE.get(market or "")
    if current_time is None:
        if tz_name:
            return datetime.now(ZoneInfo(tz_name))
        return datetime.now()
    if not tz_name:
        return current_time
    tz = ZoneInfo(tz_name)
    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=tz)
    return current_time.astimezone(tz)


def get_effective_trading_date(
    market: Optional[str], current_time: Optional[datetime] = None
) -> date:
    market_now = get_market_now(market, current_time=current_time)
    fallback_date = market_now.date()
    if not _XCALS_AVAILABLE:
        return fallback_date
    ex = MARKET_EXCHANGE.get(market or "")
    tz_name = MARKET_TIMEZONE.get(market or "")
    if not ex or not tz_name:
        return fallback_date
    try:
        cal = xcals.get_calendar(ex)
        local_date = market_now.date()
        if not cal.is_session(local_date):
            return cal.date_to_session(local_date, direction="previous").date()
        session = cal.date_to_session(local_date, direction="previous")
        session_close = cal.session_close(session)
        if hasattr(session_close, "tz_convert"):
            close_local = session_close.tz_convert(tz_name).to_pydatetime()
        elif session_close.tzinfo is not None:
            close_local = session_close.astimezone(ZoneInfo(tz_name))
        else:
            close_local = session_close.replace(tzinfo=ZoneInfo(tz_name))
        if market_now >= close_local:
            return session.date()
        return cal.previous_session(session).date()
    except Exception as e:
        logger.warning("get_effective_trading_date fail-open: %s", e)
        return fallback_date


def get_open_markets_today() -> Set[str]:
    if not _XCALS_AVAILABLE:
        return {"cn", "hk", "us"}
    result: Set[str] = set()
    for mkt, tz_name in MARKET_TIMEZONE.items():
        try:
            tz = ZoneInfo(tz_name)
            today = datetime.now(tz).date()
            if is_market_open(mkt, today):
                result.add(mkt)
        except Exception as e:
            logger.warning("get_open_markets_today fail-open for %s: %s", mkt, e)
            result.add(mkt)
    return result


def compute_effective_region(
    config_region: str, open_markets: Set[str]
) -> Optional[str]:
    if config_region not in ("cn", "us", "hk", "both"):
        config_region = "cn"
    if config_region in ("cn", "us", "hk"):
        return config_region if config_region in open_markets else ""
    # both: return 'both' if >=2 markets open, else single open market
    parts = [m for m in ("cn", "us", "hk") if m in open_markets]
    if not parts:
        return ""
    return "both" if len(parts) >= 2 else parts[0]
