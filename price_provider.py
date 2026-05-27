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
from pathlib import Path
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
    source: str = "yfinance"  # "yfinance" / "yfinance_5d" / "fast_info" / "info" / "manual"

    @property
    def ok(self) -> bool:
        return self.error is None and self.current_price is not None


# manual_prices.csv の場所 (price_provider.py と同ディレクトリ配下の data/)
_MANUAL_PRICES_CSV = Path(__file__).resolve().parent / "data" / "manual_prices.csv"


def _load_manual_prices() -> dict[str, dict[str, Optional[float]]]:
    """data/manual_prices.csv を読み、code -> {price, previous_close} の辞書を返す。

    ファイルが無い・壊れていても例外を投げない (空dictを返す)。
    1687 のような低流動性ETF向けに、yfinance全fallback失敗時の最終手段として使う。
    """
    if not _MANUAL_PRICES_CSV.exists():
        return {}
    out: dict[str, dict[str, Optional[float]]] = {}
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            df = pd.read_csv(_MANUAL_PRICES_CSV, encoding=enc, dtype=str)
            for _, r in df.iterrows():
                code = str(r.get("code", "")).strip()
                if not code:
                    continue
                try:
                    price_raw = r.get("price")
                    price = float(price_raw) if price_raw not in (None, "", "nan") else None
                except Exception:
                    price = None
                try:
                    prev_raw = r.get("previous_close")
                    prev = float(prev_raw) if prev_raw not in (None, "", "nan") else None
                except Exception:
                    prev = None
                if price is not None:
                    out[code] = {"price": price, "previous_close": prev}
            return out
        except Exception:
            continue
    return {}


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
        """チャート用ヒストリ取得。interval を指定可能。fallback多段。

        interval 例: "60m" (1時間足), "1d" (日足), "1wk" (週足)
        period 例: "60d" / "3mo" / "6mo" / "1y" / "2y" / "5y"

        取得優先順:
          1. yfinance.history(period, interval) — 通常パス
          2. yfinance.history(period="5d", interval="1d") の最新Close (低流動性fallback)
          3. ticker.fast_info の last_price / regular_market_price / previous_close
          4. ticker.info の regularMarketPrice / previousClose
          5. data/manual_prices.csv の手動値 (最終手段・1687 ETF想定)
          6. すべて失敗なら error 付き PriceData

        ※ 1〜4はyfinance API、5は手動CSV。例外でアプリ全体を落とさない。
        """
        symbol = self.yf_symbol(code, market)

        # ----- 1) 通常パス: history(period, interval) -----
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(symbol)
            hist = None
            try:
                hist = ticker.history(period=period, interval=interval, auto_adjust=False)
            except Exception:
                hist = None

            if hist is not None and not hist.empty:
                hist = hist.dropna(subset=["Close"])
                if not hist.empty:
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
                        source="yfinance",
                    )

            # ----- 2) 5日日足fallback (低流動性ETF・interval違い向け) -----
            try:
                hist5 = ticker.history(period="5d", interval="1d", auto_adjust=False)
                if hist5 is not None and not hist5.empty:
                    hist5 = hist5.dropna(subset=["Close"])
                    if not hist5.empty:
                        cur = float(hist5["Close"].iloc[-1])
                        prev = float(hist5["Close"].iloc[-2]) if len(hist5) >= 2 else None
                        chg = (cur - prev) if prev not in (None, 0) else None
                        chg_pct = ((cur / prev) - 1) * 100 if prev not in (None, 0) else None
                        return PriceData(
                            symbol=symbol,
                            current_price=cur,
                            prev_close=prev,
                            change=chg,
                            change_pct=chg_pct,
                            history=hist5,
                            source="yfinance_5d",
                        )
            except Exception:
                pass

            # ----- 3) fast_info -----
            try:
                fi = ticker.fast_info

                def _g(o, k):
                    try:
                        v = o.get(k)
                    except Exception:
                        v = getattr(o, k, None)
                    return v

                cur = _g(fi, "last_price") or _g(fi, "regular_market_price")
                prev = _g(fi, "previous_close")
                if cur is not None:
                    cur = float(cur)
                    prev_f = float(prev) if prev is not None else None
                    chg = (cur - prev_f) if prev_f not in (None, 0) else None
                    chg_pct = ((cur / prev_f) - 1) * 100 if prev_f not in (None, 0) else None
                    return PriceData(
                        symbol=symbol, current_price=cur, prev_close=prev_f,
                        change=chg, change_pct=chg_pct, source="fast_info",
                    )
            except Exception:
                pass

            # ----- 4) info -----
            try:
                info = {}
                try:
                    info = ticker.info or {}
                except Exception:
                    try:
                        info = ticker.get_info() or {}
                    except Exception:
                        info = {}
                cur = info.get("regularMarketPrice") or info.get("currentPrice")
                prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
                if cur is not None:
                    cur = float(cur)
                    prev_f = float(prev) if prev is not None else None
                    chg = (cur - prev_f) if prev_f not in (None, 0) else None
                    chg_pct = ((cur / prev_f) - 1) * 100 if prev_f not in (None, 0) else None
                    return PriceData(
                        symbol=symbol, current_price=cur, prev_close=prev_f,
                        change=chg, change_pct=chg_pct, source="info",
                    )
            except Exception:
                pass

        except Exception:
            # yfinance自体のimport/Tickerで失敗 → manualへフォールスルー
            pass

        # ----- 5) data/manual_prices.csv (最終手段) -----
        try:
            manual = _load_manual_prices()
            # code (例: "1687") と symbol (例: "1687.T") の両方で探す
            m = manual.get(code) or manual.get(symbol)
            if m and m.get("price") is not None:
                cur = float(m["price"])
                prev = m.get("previous_close")
                prev_f = float(prev) if prev is not None else None
                chg = (cur - prev_f) if prev_f not in (None, 0) else None
                chg_pct = ((cur / prev_f) - 1) * 100 if prev_f not in (None, 0) else None
                return PriceData(
                    symbol=symbol, current_price=cur, prev_close=prev_f,
                    change=chg, change_pct=chg_pct, source="manual",
                )
        except Exception:
            pass

        # ----- 6) すべて失敗 -----
        return PriceData(symbol=symbol, error="fetch failed (all fallbacks exhausted)")


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
