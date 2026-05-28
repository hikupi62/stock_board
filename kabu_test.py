# -*- coding: utf-8 -*-
"""kabuステーションAPI 接続テストスクリプト (standalone・読み取り専用)

目的:
    yfinance価格と乖離があるため、auカブコム証券「kabuステーションAPI」から
    現在値を取得できるかだけを確認する。

絶対方針:
    - 自動発注機能は追加しない (注文API /sendorder /cancelorder /orders は呼ばない)
    - 証券会社ログイン情報を保存しない (パスワードはconfig or 環境変数経由のみ)
    - APIパスワードをコードに直書きしない (kabu_config.json は .gitignore 済)
    - 既存 app.py / price_provider.py / CSV は変更しない
    - 株式注文・先物注文・OCO・逆指値・残高照会も呼ばない (価格取得のみ)

使用するAPIエンドポイント (価格取得のみ):
    POST /token              ← トークン発行
    GET  /board/{symbol}@{exchange}  ← 時価情報取得

実行:
    cd C:\\stocks\\app\\stock_board
    py kabu_test.py
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import error as urlerr
from urllib import request as urlreq

# Windows コンソール (cp932) でも絵文字 ✅❌ がクラッシュしないよう UTF-8 を強制。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "kabu_config.json"
EXAMPLE_PATH = SCRIPT_DIR / "kabu_config.example.json"
OUTPUT_CSV = SCRIPT_DIR / "data" / "kabu_prices_test.csv"
FAILED_CSV = SCRIPT_DIR / "data" / "kabu_prices_failed.csv"

# kabuステーション「現物」用のエンドポイント (注文系は一切使わない)
SAFE_PRICE_ENDPOINTS = ("/token", "/board")

# デフォルト設定 (config 未指定時に使う値)
DEFAULT_TIMEOUT_SEC = 10
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_SLEEP_SEC = 0.5


def _print_step(label: str) -> None:
    print(f"\n=== {label} ===")


def _load_config() -> dict:
    """設定読込: kabu_config.json → 環境変数 KABU_API_PASSWORD の順。

    どちらも無ければエラー終了。APIパスワードは絶対にprintしない。
    """
    cfg: dict = {
        "api_password": None,
        "base_url": "http://localhost:18080/kabusapi",
        "exchange": 1,
        "symbols": ["9433", "8020", "2780"],
        "request_timeout_sec": DEFAULT_TIMEOUT_SEC,
        "retry_count": DEFAULT_RETRY_COUNT,
        "retry_sleep_sec": DEFAULT_RETRY_SLEEP_SEC,
    }

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            for k in ("api_password", "base_url", "exchange", "symbols",
                      "request_timeout_sec", "retry_count", "retry_sleep_sec"):
                if k in file_cfg and file_cfg[k] not in (None, ""):
                    cfg[k] = file_cfg[k]
            print(f"[config] {CONFIG_PATH.name} を読み込みました")
        except Exception as e:
            print(f"[config] {CONFIG_PATH.name} の読み込みに失敗: {e}")

    env_pw = os.environ.get("KABU_API_PASSWORD")
    if env_pw and not cfg["api_password"]:
        cfg["api_password"] = env_pw
        print("[config] 環境変数 KABU_API_PASSWORD を読み込みました")

    # プレースホルダのままだったら扱わない
    if cfg["api_password"] in (None, "", "ここにkabuステーションAPIパスワード"):
        print()
        print("❌ APIパスワードが設定されていません。")
        print(f"   - {EXAMPLE_PATH.name} を {CONFIG_PATH.name} にコピーし")
        print("     api_password を設定する、または")
        print("   - 環境変数 KABU_API_PASSWORD を設定してください。")
        print(f"   ※ {CONFIG_PATH.name} は .gitignore 済 (GitHubにはアップされません)")
        sys.exit(2)

    # base_urlは安全のためhttp://localhost に限定する
    base = str(cfg["base_url"] or "").strip()
    if not (base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        print(f"❌ base_url は localhost に限定されています (実値: {base})")
        sys.exit(2)
    return cfg


def _http_post(url: str, body: dict, headers: Optional[dict] = None,
               timeout: int = DEFAULT_TIMEOUT_SEC) -> tuple[int, dict]:
    """POST JSON (read-only用途のtoken発行のみ・注文系には絶対使わない)。"""
    if not any(seg in url for seg in SAFE_PRICE_ENDPOINTS):
        raise RuntimeError(f"refusing to POST to unsafe endpoint: {url}")
    data = json.dumps(body).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urlreq.Request(url, data=data, headers=h, method="POST")
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, json.loads(payload) if payload else {}
    except urlerr.HTTPError as e:
        try:
            payload = e.read().decode("utf-8")
            return e.code, json.loads(payload) if payload else {"error": str(e)}
        except Exception:
            return e.code, {"error": str(e)}


def _http_get(url: str, headers: Optional[dict] = None,
              timeout: int = DEFAULT_TIMEOUT_SEC) -> tuple[int, dict]:
    """GET JSON (価格board取得のみ)."""
    if not any(seg in url for seg in SAFE_PRICE_ENDPOINTS):
        raise RuntimeError(f"refusing to GET unsafe endpoint: {url}")
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urlreq.Request(url, headers=h, method="GET")
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, json.loads(payload) if payload else {}
    except urlerr.HTTPError as e:
        try:
            payload = e.read().decode("utf-8")
            return e.code, json.loads(payload) if payload else {"error": str(e)}
        except Exception:
            return e.code, {"error": str(e)}


def _mask_token(tok: str) -> str:
    """Tokenの一部だけ表示する (全体は出さない)。"""
    if not tok:
        return "(空)"
    if len(tok) <= 12:
        return tok[:3] + "..." + tok[-1:]
    return tok[:6] + "..." + tok[-3:]


def get_token(base_url: str, api_password: str,
              timeout: int = DEFAULT_TIMEOUT_SEC) -> Optional[str]:
    """POST /token でトークンを発行。失敗時 None。"""
    url = base_url.rstrip("/") + "/token"
    try:
        status, body = _http_post(url, {"APIPassword": api_password}, timeout=timeout)
    except urlerr.URLError as e:
        reason = getattr(e, "reason", e)
        print(f"❌ kabuステーションAPIに接続できません ({reason})")
        print("   - kabuステーション本体を起動し、ログイン済みであることを確認してください")
        print("   - 「ツール」→「API設定」で **API利用をON** にしてください")
        print(f"   - ポート 18080 で待ち受けているか確認してください (base_url: {base_url})")
        return None
    except Exception as e:
        print(f"❌ token取得で予期せぬエラー: {e.__class__.__name__}: {e}")
        return None

    if status == 200 and isinstance(body, dict) and body.get("Token"):
        token = str(body["Token"])
        print(f"✅ Token取得成功: {_mask_token(token)}")
        return token
    elif status in (401, 403):
        print(f"❌ APIパスワードが違う可能性 (HTTP {status})")
        msg = body.get("Message") if isinstance(body, dict) else None
        if msg:
            print(f"   サーバ応答: {msg}")
        return None
    else:
        print(f"❌ token取得失敗 (HTTP {status}): {body}")
        return None


def _is_transient_error(exc: BaseException) -> bool:
    """timeoutや一時的な通信エラー (= 再試行する価値あり) かを判定。"""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, urlerr.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return True
        if "timed out" in str(reason).lower():
            return True
        if "temporarily" in str(reason).lower():
            return True
    if isinstance(exc, ConnectionResetError):
        return True
    return False


def get_board(base_url: str, token: str, symbol: str, exchange: int,
              timeout: int = DEFAULT_TIMEOUT_SEC,
              retry_count: int = DEFAULT_RETRY_COUNT,
              retry_sleep_sec: float = DEFAULT_RETRY_SLEEP_SEC,
              ) -> tuple[Optional[dict], Optional[str]]:
    """GET /board/{symbol}@{exchange} で時価情報を取得 (retry付き)。

    戻り値: (board_dict, error_message)
      - 成功時: (dict, None)
      - 失敗時: (None, "エラーメッセージ")  ← スクリプトは止めない

    再試行する条件:
      - socket.timeout / TimeoutError / 'timed out' を含む URLError
      - ConnectionResetError
      - HTTP 429 / 5xx (一時的サーバ側エラー)
    再試行しない条件:
      - HTTP 404 (銘柄が存在しない)
      - HTTP 401/403 (認証問題)
      - その他 4xx
    """
    url = f"{base_url.rstrip('/')}/board/{symbol}@{exchange}"
    last_err = "unknown"
    attempts = max(1, int(retry_count))

    for attempt in range(1, attempts + 1):
        try:
            status, body = _http_get(url, headers={"X-API-KEY": token}, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - 1銘柄失敗で全体を止めないため
            if _is_transient_error(e) and attempt < attempts:
                print(f"  ⏱  {symbol} timeout/通信エラー (attempt {attempt}/{attempts}) "
                      f"— {retry_sleep_sec}秒待って再試行")
                time.sleep(retry_sleep_sec)
                last_err = f"{e.__class__.__name__}: {e}"
                continue
            last_err = f"{e.__class__.__name__}: {e}"
            return None, f"{last_err} (after {attempt} attempts)"

        # HTTPレスポンス到達
        if status == 200 and isinstance(body, dict):
            return body, None
        if status == 404:
            return None, "HTTP 404 (銘柄が見つかりません)"
        if status in (401, 403):
            return None, f"HTTP {status} (認証エラー)"
        # 429/5xx は一時的・再試行
        if (status == 429 or 500 <= status < 600) and attempt < attempts:
            print(f"  ⚠  {symbol} HTTP {status} (attempt {attempt}/{attempts}) "
                  f"— {retry_sleep_sec}秒待って再試行")
            time.sleep(retry_sleep_sec)
            last_err = f"HTTP {status}: {body}"
            continue
        # その他HTTPエラーは再試行せず即失敗
        return None, f"HTTP {status}: {body}"

    return None, f"failed after {attempts} retries ({last_err})"


def print_board_summary(symbol: str, b: dict) -> None:
    """取得結果を分かりやすく表示。"""
    def _get(k):
        v = b.get(k)
        return v if v is not None else "-"

    print(f"  Symbol           : {_get('Symbol')}")
    print(f"  SymbolName       : {_get('SymbolName')}")
    print(f"  CurrentPrice     : {_get('CurrentPrice')}")
    print(f"  CurrentPriceTime : {_get('CurrentPriceTime')}")
    print(f"  PreviousClose    : {_get('PreviousClose')}")
    print(f"  TradingVolume    : {_get('TradingVolume')}")
    print(f"  ExchangeName     : {_get('ExchangeName')}")


def board_to_row(b: dict, fallback_code: str) -> dict:
    """boardレスポンスをCSV1行に整える。"""
    code = str(b.get("Symbol") or fallback_code)
    name = b.get("SymbolName") or ""
    price = b.get("CurrentPrice")
    prev = b.get("PreviousClose")
    volume = b.get("TradingVolume")
    ptime = b.get("CurrentPriceTime") or ""

    change = None
    change_pct = None
    try:
        if price is not None and prev not in (None, 0):
            change = float(price) - float(prev)
            change_pct = (float(price) / float(prev) - 1) * 100
    except Exception:
        change = None
        change_pct = None

    return {
        "code": code,
        "name": name,
        "price": price if price is not None else "",
        "previous_close": prev if prev is not None else "",
        "change": "" if change is None else f"{change:.2f}",
        "change_pct": "" if change_pct is None else f"{change_pct:.4f}",
        "volume": volume if volume is not None else "",
        "price_time": ptime,
        "source": "kabu_station",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["code", "name", "price", "previous_close", "change", "change_pct",
            "volume", "price_time", "source", "updated_at"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"💾 成功CSV: {out_path} ({len(rows)} 行)")


def write_failed_csv(failed: list[dict], out_path: Path) -> None:
    """失敗銘柄のCSV出力 (列: code,error,updated_at)。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["code", "error", "updated_at"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in failed:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"💾 失敗CSV: {out_path} ({len(failed)} 行)")


def main() -> int:
    print("=" * 60)
    print(" kabuステーションAPI 接続テスト (価格取得のみ)")
    print(" ※ 注文系API (/sendorder, /cancelorder) は呼びません")
    print("=" * 60)

    _print_step("1. 設定読込")
    cfg = _load_config()
    base_url = str(cfg["base_url"]).rstrip("/")
    exchange = int(cfg["exchange"])
    symbols = [str(s) for s in cfg["symbols"] if str(s).strip()]
    try:
        timeout_sec = int(cfg.get("request_timeout_sec", DEFAULT_TIMEOUT_SEC))
    except Exception:
        timeout_sec = DEFAULT_TIMEOUT_SEC
    try:
        retry_count = int(cfg.get("retry_count", DEFAULT_RETRY_COUNT))
    except Exception:
        retry_count = DEFAULT_RETRY_COUNT
    try:
        retry_sleep = float(cfg.get("retry_sleep_sec", DEFAULT_RETRY_SLEEP_SEC))
    except Exception:
        retry_sleep = DEFAULT_RETRY_SLEEP_SEC

    print(f"  base_url:            {base_url}")
    print(f"  exchange:            {exchange}")
    print(f"  symbols:             {symbols}")
    print(f"  request_timeout_sec: {timeout_sec}")
    print(f"  retry_count:         {retry_count}")
    print(f"  retry_sleep_sec:     {retry_sleep}")

    _print_step("2. トークン取得 (POST /token)")
    token = get_token(base_url, str(cfg["api_password"]), timeout=timeout_sec)
    if not token:
        return 1

    _print_step("3. 価格取得 (GET /board/{symbol}@{exchange}) — retry付き")
    success_rows: list[dict] = []
    success_summary: list[tuple[str, str, object]] = []  # (code, name, price)
    failed: list[dict] = []
    for sym in symbols:
        print(f"\n--- {sym} ---")
        b, err = get_board(
            base_url, token, sym, exchange,
            timeout=timeout_sec, retry_count=retry_count, retry_sleep_sec=retry_sleep,
        )
        if b is None:
            print(f"  ❌ {sym} 取得失敗: {err}")
            failed.append({
                "code": sym,
                "error": err or "unknown",
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            })
            continue
        print_board_summary(sym, b)
        row = board_to_row(b, sym)
        success_rows.append(row)
        success_summary.append((row["code"], row["name"], row["price"]))

    _print_step("4. 結果サマリ")
    print(f"  ✅ 成功: {len(success_rows)} 銘柄")
    for code, name, price in success_summary:
        print(f"     - {code} {name} {price}")
    if failed:
        print(f"  ❌ 失敗: {len(failed)} 銘柄")
        for f in failed:
            print(f"     - {f['code']}  {f['error']}")
    else:
        print("  ❌ 失敗: 0 銘柄")

    _print_step("5. CSV保存")
    if success_rows:
        write_csv(success_rows, OUTPUT_CSV)
    else:
        print(f"⚠ 成功銘柄ゼロのため {OUTPUT_CSV.name} は出力しません")
    if failed:
        write_failed_csv(failed, FAILED_CSV)
    else:
        # 失敗ゼロなら既存failed CSVは削除して状態を一致させる (任意)
        if FAILED_CSV.exists():
            try:
                FAILED_CSV.unlink()
                print(f"🧹 失敗ゼロのため旧 {FAILED_CSV.name} を削除しました")
            except Exception:
                pass

    if not success_rows and failed:
        print("\n❌ すべての銘柄が失敗しました")
        return 1

    print("\n✅ 接続テスト完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
