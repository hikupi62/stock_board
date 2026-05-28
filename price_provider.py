# -*- coding: utf-8 -*-
"""Price provider abstraction for stock board.

Providers:
- YFinanceProvider (default, Cloud-safe・遅延)
- KabuStationProvider (ローカルPC・kabuステーション API 経由・JP株のみ)
- AutoProvider (kabu優先→yfinance fallback)

CRITICAL — read-only / no orders / no credentials:
- No order placement (/sendorder /cancelorder /orders /positions /wallet 一切呼ばない)
- No credentials stored on disk (kabu Token はメモリのみ)
- yfinance is used for price/volume/chart data only (NOT for fundamentals)
- kabu_station の base_url は localhost / 127.0.0.1 のみ
- 使うkabuエンドポイントは /token と /board のみ (whitelist)
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


# =============================================================================
# kabuステーション Provider (ローカルPC・JP株のみ・/token と /board のみ)
# =============================================================================
#
# 安全制約 (絶対):
# - 注文系API (/sendorder /cancelorder /orders /positions /wallet) は呼ばない
# - 使うエンドポイントは /token と /board のみ (whitelistで物理ガード)
# - base_url は localhost / 127.0.0.1 のみ
# - APIパスワードはコード/ファイル/メモリログに残さない
# - Token はメモリのみ (ファイル保存禁止)
# - 米国株は対象外 → caller (AutoProvider) で yfinance fallback

_KABU_CONFIG_PATH = Path(__file__).resolve().parent / "kabu_config.json"
_KABU_SAFE_ENDPOINTS = ("/token", "/board")


def _load_kabu_config() -> Optional[dict]:
    """kabu_config.json または環境変数 KABU_API_PASSWORD から設定を読む。

    どちらも無ければ None を返し、KabuStationProvider は unavailable 扱い。
    base_url は localhost / 127.0.0.1 以外を弾く (外部送信防止)。
    """
    import json as _json
    import os as _os

    cfg = {
        "api_password": None,
        "base_url": "http://localhost:18080/kabusapi",
        "exchange": 1,
        "request_timeout_sec": 10,
        "retry_count": 3,
        "retry_sleep_sec": 0.5,
    }
    if _KABU_CONFIG_PATH.exists():
        try:
            with _KABU_CONFIG_PATH.open("r", encoding="utf-8") as f:
                file_cfg = _json.load(f)
            for k in cfg.keys():
                if k in file_cfg and file_cfg[k] not in (None, ""):
                    cfg[k] = file_cfg[k]
        except Exception:
            pass

    if not cfg["api_password"]:
        env_pw = _os.environ.get("KABU_API_PASSWORD")
        if env_pw:
            cfg["api_password"] = env_pw

    if not cfg["api_password"] or cfg["api_password"] == "ここにkabuステーションAPIパスワード":
        return None

    base = str(cfg["base_url"] or "").strip()
    if not (base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        # 外部URLは絶対に許可しない
        return None
    return cfg


class KabuStationProvider(PriceProvider):
    """kabuステーション API 経由のローカル価格Provider。

    - 取得: GET /board/{symbol}@{exchange} のみ (snapshot)
    - 認証: POST /token (1回・トークンはメモリのみ)
    - 米国株 (market != "JP") は即 unavailable を返し、callerでyfinance fallbackさせる
    - チャート用 history は返さない (履歴は yfinance に任せる)
    """

    name = "kabu_station"

    def __init__(self) -> None:
        self._cfg = _load_kabu_config()
        self._token: Optional[str] = None
        self._token_err: Optional[str] = None

    @property
    def available(self) -> bool:
        """kabu_config.json 等が読めて localhost URL ならTrue。"""
        return self._cfg is not None

    def yf_symbol(self, code: str, market: str) -> str:
        # 抽象クラス互換のためのダミー (kabuはcodeをそのまま使う)
        code = str(code).strip()
        return code

    def fetch(self, code: str, market: str, period: str = "6mo") -> PriceData:
        return self.fetch_history(code, market, period=period, interval="1d")

    def _safe_check(self, url: str) -> None:
        """whitelist外URLは物理的に拒否 (RuntimeError)。"""
        if not any(seg in url for seg in _KABU_SAFE_ENDPOINTS):
            raise RuntimeError(f"kabu provider: refusing unsafe endpoint: {url}")

    def _http_post(self, url: str, body: dict, timeout: int) -> tuple[int, dict]:
        self._safe_check(url)
        import json as _json
        from urllib import error as _urlerr
        from urllib import request as _urlreq
        data = _json.dumps(body).encode("utf-8")
        req = _urlreq.Request(url, data=data,
                               headers={"Content-Type": "application/json"},
                               method="POST")
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8")
                return resp.status, _json.loads(payload) if payload else {}
        except _urlerr.HTTPError as e:
            try:
                p = e.read().decode("utf-8")
                return e.code, _json.loads(p) if p else {"error": str(e)}
            except Exception:
                return e.code, {"error": str(e)}

    def _http_get(self, url: str, token: str, timeout: int) -> tuple[int, dict]:
        self._safe_check(url)
        import json as _json
        from urllib import error as _urlerr
        from urllib import request as _urlreq
        req = _urlreq.Request(
            url,
            headers={"X-API-KEY": token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with _urlreq.urlopen(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8")
                return resp.status, _json.loads(payload) if payload else {}
        except _urlerr.HTTPError as e:
            try:
                p = e.read().decode("utf-8")
                return e.code, _json.loads(p) if p else {"error": str(e)}
            except Exception:
                return e.code, {"error": str(e)}

    def _get_token(self) -> Optional[str]:
        """Tokenをメモリキャッシュから返す。なければ /token で取得。"""
        if self._token:
            return self._token
        if not self._cfg:
            return None
        url = str(self._cfg["base_url"]).rstrip("/") + "/token"
        try:
            status, body = self._http_post(
                url,
                {"APIPassword": self._cfg["api_password"]},
                timeout=int(self._cfg["request_timeout_sec"]),
            )
        except Exception as e:
            self._token_err = f"token error: {e.__class__.__name__}"
            return None
        if status == 200 and isinstance(body, dict) and body.get("Token"):
            self._token = str(body["Token"])
            return self._token
        self._token_err = f"token HTTP {status}"
        return None

    def _invalidate_token(self) -> None:
        self._token = None

    def fetch_history(self, code: str, market: str, period: str = "6mo",
                      interval: str = "1d") -> PriceData:
        """kabuステーションは snapshot 専用。historyは返さない (callerが yfinance に回す想定)。"""
        import socket as _socket
        import time as _time
        from urllib import error as _urlerr

        code = str(code).strip()
        market_u = (market or "").upper()

        # 米国株はkabu対象外 (caller側でyfinance fallbackさせる)
        if market_u != "JP":
            return PriceData(
                symbol=code,
                error="kabu_station: JP only",
                source="kabu_station_skip",
            )

        if not self._cfg:
            return PriceData(
                symbol=code,
                error="kabu_station: not configured (use yfinance)",
                source="kabu_station_unavail",
            )

        token = self._get_token()
        if not token:
            return PriceData(
                symbol=code,
                error=f"kabu_station: {self._token_err or 'token unavailable'}",
                source="kabu_station_unavail",
            )

        exchange = int(self._cfg.get("exchange", 1))
        url = f"{str(self._cfg['base_url']).rstrip('/')}/board/{code}@{exchange}"
        timeout = int(self._cfg["request_timeout_sec"])
        retry_count = max(1, int(self._cfg["retry_count"]))
        retry_sleep = float(self._cfg["retry_sleep_sec"])

        last_err = "unknown"
        for attempt in range(1, retry_count + 1):
            try:
                status, body = self._http_get(url, token, timeout=timeout)
            except (_socket.timeout, TimeoutError) as e:
                last_err = f"timeout: {e.__class__.__name__}"
                if attempt < retry_count:
                    _time.sleep(retry_sleep)
                    continue
                return PriceData(symbol=code, error=last_err, source="kabu_station_fail")
            except _urlerr.URLError as e:
                reason = str(getattr(e, "reason", e))
                last_err = f"urlerror: {reason}"
                if "timed out" in reason.lower() and attempt < retry_count:
                    _time.sleep(retry_sleep)
                    continue
                # kabuステーション未起動 → unavail (callerでyfinanceへ)
                return PriceData(
                    symbol=code, error=last_err, source="kabu_station_unavail",
                )
            except Exception as e:
                last_err = f"{e.__class__.__name__}: {e}"
                return PriceData(symbol=code, error=last_err, source="kabu_station_fail")

            if status == 200 and isinstance(body, dict):
                return self._board_to_price(body, code)
            if status in (401, 403):
                # Token失効の可能性 → 1回だけ再取得
                if attempt == 1:
                    self._invalidate_token()
                    new_t = self._get_token()
                    if new_t:
                        token = new_t
                        continue
                return PriceData(
                    symbol=code, error=f"HTTP {status}", source="kabu_station_fail",
                )
            if status == 404:
                return PriceData(
                    symbol=code, error="HTTP 404", source="kabu_station_fail",
                )
            if (status == 429 or 500 <= status < 600) and attempt < retry_count:
                _time.sleep(retry_sleep)
                last_err = f"HTTP {status}"
                continue
            return PriceData(
                symbol=code, error=f"HTTP {status}", source="kabu_station_fail",
            )

        return PriceData(symbol=code, error=last_err, source="kabu_station_fail")

    @staticmethod
    def _board_to_price(body: dict, code: str) -> PriceData:
        try:
            from zoneinfo import ZoneInfo
            _JST = ZoneInfo("Asia/Tokyo")
        except Exception:
            _JST = dt.timezone(dt.timedelta(hours=9), "JST")

        price = body.get("CurrentPrice")
        prev = body.get("PreviousClose")
        vol = body.get("TradingVolume")
        ptime = body.get("CurrentPriceTime")

        # data_time をJSTのdatetimeに正規化
        last_update: Optional[dt.datetime] = None
        if ptime:
            try:
                t = dt.datetime.fromisoformat(str(ptime))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=_JST)
                last_update = t.astimezone(_JST)
            except Exception:
                last_update = None

        if price is None:
            return PriceData(symbol=code, error="no price", source="kabu_station_fail")
        try:
            cur = float(price)
        except Exception:
            return PriceData(symbol=code, error="invalid price", source="kabu_station_fail")

        prev_f: Optional[float] = None
        try:
            prev_f = float(prev) if prev is not None else None
        except Exception:
            prev_f = None
        chg = (cur - prev_f) if prev_f not in (None, 0) else None
        chg_pct = ((cur / prev_f) - 1) * 100 if prev_f not in (None, 0) else None

        vol_f: Optional[float] = None
        try:
            vol_f = float(vol) if vol is not None else None
        except Exception:
            vol_f = None

        return PriceData(
            symbol=code,
            current_price=cur,
            prev_close=prev_f,
            change=chg,
            change_pct=chg_pct,
            volume=vol_f,
            last_update=last_update,
            source="kabu_station",
        )


# =============================================================================
# Auto Provider (kabu優先 + yfinance fallback)
# =============================================================================

class AutoProvider(PriceProvider):
    """auto: snapshotはkabu→yfinance、chartは常にyfinance (kabuに履歴なし)。

    Cloud/スマホ環境では kabu_config.json が無いため kabu.available=False となり、
    透過的に yfinance のみが使われる。
    """

    name = "auto"

    def __init__(self) -> None:
        self.kabu = KabuStationProvider()
        self.yf = YFinanceProvider()

    @property
    def kabu_available(self) -> bool:
        return self.kabu.available

    def yf_symbol(self, code: str, market: str) -> str:
        return self.yf.yf_symbol(code, market)

    def fetch(self, code: str, market: str, period: str = "6mo") -> PriceData:
        # snapshot用パス: JP株かつkabu利用可なら kabu優先
        market_u = (market or "").upper()
        if market_u == "JP" and self.kabu.available:
            r = self.kabu.fetch(code, market, period=period)
            if r.ok:
                return r
        return self.yf.fetch(code, market, period=period)

    def fetch_history(self, code: str, market: str, period: str = "6mo",
                      interval: str = "1d") -> PriceData:
        """charts需要 (60m/1d/1wk等のhistory) は常にyfinance。

        kabuステーションはsnapshotのみで履歴を返さないため、チャート描画はyfinance必須。
        snapshot用途 (period='6mo' & interval='1d') でも fetch() を経由しない直接呼び出しは
        yfinanceに任せる方が安全。
        """
        # snapshot相当の呼び出しなら kabu試行
        market_u = (market or "").upper()
        if (interval == "1d" and period == "6mo"
                and market_u == "JP" and self.kabu.available):
            r = self.kabu.fetch_history(code, market, period=period, interval=interval)
            if r.ok:
                return r
        return self.yf.fetch_history(code, market, period=period, interval=interval)


# Convenience factory ----------------------------------------------------------

def get_provider(name: str = "auto") -> PriceProvider:
    """Return a provider instance by name.

    - "yfinance"     -> 純粋にyfinanceのみ (Cloud-safe)
    - "kabu_station" -> kabu優先 + yfinance fallback (チャート崩壊防止のためAutoProvider相当)
    - "auto"         -> kabu優先 + yfinance fallback (デフォルト)
    """
    name = (name or "auto").lower()
    if name == "yfinance":
        return YFinanceProvider()
    if name in ("kabu_station", "auto"):
        return AutoProvider()
    # 未知の名前はautoで安全側に
    return AutoProvider()


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
