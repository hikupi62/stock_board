# -*- coding: utf-8 -*-
"""Price provider abstraction for stock board.

Initial implementation: YFinanceProvider only.
Future: RakutenRSSProvider, TachibanaProvider can be added by subclassing PriceProvider.

CRITICAL: This module is read-only towards external services.
- No order placement
- No credentials stored
- yfinance is used for price/volume/chart data only (NOT for fundamentals)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class PriceData:
    """Container for price/volume snapshot of a single ticker."""

    symbol: str
    current_price: Optional[float] = None
    prev_close: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[float] = None
    last_update: Optional[dt.datetime] = None
    error: Optional[str] = None
    history: Optional[pd.DataFrame] = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None and self.current_price is not None


class PriceProvider:
    """Abstract base for price providers."""

    name: str = "abstract"

    def yf_symbol(self, code: str, market: str) -> str:
        """Convert internal code/market to provider-specific symbol."""
        raise NotImplementedError

    def fetch(self, code: str, market: str, period: str = "6mo") -> PriceData:
        raise NotImplementedError


class YFinanceProvider(PriceProvider):
    """yfinance-based provider. Delayed/quasi-realtime."""

    name = "yfinance"

    def yf_symbol(self, code: str, market: str) -> str:
        market = (market or "").upper()
        code = str(code).strip()
        if market == "JP":
            # 日本株: code + ".T"
            return f"{code}.T"
        # 米国株: そのまま
        return code

    def fetch(self, code: str, market: str, period: str = "6mo") -> PriceData:
        """現在値・前日比・出来高・日足ヒストリを取得 (Home/Portfolio用)。"""
        return self.fetch_history(code, market, period=period, interval="1d")

    def fetch_history(
        self,
        code: str,
        market: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> PriceData:
        """チャート用ヒストリ取得。interval を指定可能。

        interval 例: "60m" (1時間足), "1d" (日足), "1wk" (週足)
        period 例: "60d" / "3mo" / "6mo" / "1y" / "2y" / "5y"

        - 1時間足は yfinance の制約で取得期間に上限がある (おおむね最大 ~730日)。
        - 日本株では1時間足が欠損する場合がある。
        - 取得失敗時は error 付きの PriceData を返す。
        """
        symbol = self.yf_symbol(code, market)
        try:
            # Lazy import to avoid breaking the rest of the app if yfinance is missing.
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval=interval, auto_adjust=False)
            if hist is None or hist.empty:
                return PriceData(symbol=symbol, error="no data")

            # 取引時間中・休場・取得不可で最新行 Close が NaN になり得るため除去
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                return PriceData(symbol=symbol, error="no close data")

            current_price = float(hist["Close"].iloc[-1])
            prev_close: Optional[float] = None
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])

            change = None
            change_pct = None
            if prev_close not in (None, 0):
                change = current_price - prev_close
                change_pct = (current_price / prev_close - 1) * 100

            volume = None
            try:
                volume = float(hist["Volume"].iloc[-1])
            except Exception:
                volume = None

            last_update = hist.index[-1].to_pydatetime() if len(hist) else None

            return PriceData(
                symbol=symbol,
                current_price=current_price,
                prev_close=prev_close,
                change=change,
                change_pct=change_pct,
                volume=volume,
                last_update=last_update,
                history=hist,
            )
        except Exception as exc:  # noqa: BLE001 - keep app alive
            return PriceData(symbol=symbol, error=f"fetch error: {exc.__class__.__name__}")


# Convenience factory ----------------------------------------------------------

def get_provider(name: str = "yfinance") -> PriceProvider:
    """Return a provider instance by name.

    Currently only "yfinance" is implemented. Future names:
    - "rakuten_rss" -> RakutenRSSProvider
    - "tachibana"   -> TachibanaProvider
    """
    name = (name or "yfinance").lower()
    if name == "yfinance":
        return YFinanceProvider()
    # Fallback to yfinance with a notice
    return YFinanceProvider()


# Symbol name lookup -----------------------------------------------------------
#
# ※ ここで yfinance を呼ぶのは「銘柄名 (longName/shortName/displayName) 補完」用のみ。
#    ファンダメンタル情報 (PER/EPS/売上等) の取得には使わない。

def lookup_symbol_name(code: str, market: str) -> Optional[str]:
    """yfinance から銘柄名のみを取得して返す。取得不可なら None。

    優先度: longName -> shortName -> displayName -> None
    """
    code = str(code or "").strip()
    if not code:
        return None
    market_u = (market or "").upper()
    symbol = f"{code}.T" if market_u == "JP" else code
    try:
        import yfinance as yf  # type: ignore

        ticker = yf.Ticker(symbol)
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            try:
                info = ticker.get_info() or {}  # 新APIフォールバック
            except Exception:
                info = {}
        for key in ("longName", "shortName", "displayName"):
            v = info.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None
    except Exception:
        return None


# External links ---------------------------------------------------------------

def yahoo_link(code: str, market: str) -> str:
    market = (market or "").upper()
    code = str(code).strip()
    if market == "JP":
        return f"https://finance.yahoo.co.jp/quote/{code}.T"
    return f"https://finance.yahoo.com/quote/{code}"


def tradingview_link(code: str, market: str) -> str:
    market = (market or "").upper()
    code = str(code).strip()
    if market == "JP":
        return f"https://www.tradingview.com/symbols/TSE-{code}/"
    return f"https://www.tradingview.com/symbols/NASDAQ-{code}/"
