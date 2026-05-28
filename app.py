# -*- coding: utf-8 -*-
"""Aさん専用 株価チェックボード (Streamlit)

閲覧専用。自動発注なし。証券会社ログイン情報を保存しない。
yfinance取得のため、価格は遅延/準リアルタイム。

運用前提:
    Streamlit Community Cloud の private app として配信し、アクセス制御は
    Streamlit Cloud側のログイン (Streamlit/Google/GitHub) に委ねます。
    アプリ内でのパスワード入力は廃止しました。

ローカル起動:
    cd C:\\stocks\\app\\stock_board
    pip install -r requirements.txt
    streamlit run app.py

スマホでローカル確認:
    streamlit run app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

import datetime as dt
import io
import shutil
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

# JST タイムゾーン (Streamlit Cloud は UTC 環境のため日本時間で表示する)
# zoneinfo (Python 3.9+) を優先・OSにtzdataが無い場合は固定オフセットでfallback。
try:
    from zoneinfo import ZoneInfo  # type: ignore
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = dt.timezone(dt.timedelta(hours=9), "JST")

# Provider 層は別ファイル (差し替え容易にする)
from price_provider import (
    PriceData,
    YFinanceProvider,
    get_provider,
    lookup_symbol_name,
    yahoo_link,
    tradingview_link,
)


@st.cache_data(ttl=3600, show_spinner=False)
def lookup_symbol_name_cached(code: str, market: str) -> Optional[str]:
    return lookup_symbol_name(code, market)


# =============================================================================
# Constants / paths
# =============================================================================

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
WATCHLIST_CSV = DATA_DIR / "watchlist.csv"

# 表示用グループ (旧版の「日本株保有」「日本株Watch」「別枠」から統一)
GROUP_HOLD = "保有"
GROUP_WATCH = "Watch"
GROUP_EXCLUDED = "除外"
GROUP_OPTIONS = [GROUP_HOLD, GROUP_WATCH, GROUP_EXCLUDED]
MARKET_OPTIONS = ["JP", "US"]
CURRENCY_OPTIONS = ["JPY", "USD"]

# Positions読み込み優先順位:
#   1. data/positions.csv (Streamlit Community Cloud対応・最優先)
#   2. C:/stocks/data/current_positions_20260527_after_kddi_are_update.csv (ローカル既存・読み取り専用)
#   3. どちらもなければ watchlist のみで起動
POSITIONS_CSV_APP = DATA_DIR / "positions.csv"
POSITIONS_CSV_LOCAL_FALLBACK = Path(r"C:/stocks/data/current_positions_20260527_after_kddi_are_update.csv")

# 富士通6702は父保有分なのでAさんPFから除外
EXCLUDED_FROM_PF = {"6326", "285A", "6702"}


# =============================================================================
# Page config
# =============================================================================

st.set_page_config(
    page_title="Aさん株価ボード",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",  # スマホで邪魔にならないように
)


# =============================================================================
# Access control
# =============================================================================
#
# アプリ内パスワード認証は廃止しました。
# 外部公開は Streamlit Community Cloud の "private app" として配信し、
# アクセス制御は Cloud 側のログイン (Streamlit/Google/GitHub) に委ねます。
# 初回のみログインが必要・以降はスマホのログイン状態が残っていればブックマークで再開できます。


# =============================================================================
# Data loaders (読み取り専用)
# =============================================================================

@st.cache_data(show_spinner=False, ttl=86400)
def load_jpx_master() -> pd.DataFrame:
    """data/jpx_listed_companies.csv 読み込み (日本株 日本語名マスタ)。

    無い場合は空DataFrameを返してアプリは正常動作する。
    """
    path = DATA_DIR / "jpx_listed_companies.csv"
    if not path.exists():
        return pd.DataFrame(columns=["code", "name", "market", "sector", "note"])
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str)
            for col in ("code", "name", "market", "sector", "note"):
                if col not in df.columns:
                    df[col] = ""
            df["code"] = df["code"].fillna("").astype(str).str.strip()
            df["name"] = df["name"].fillna("").astype(str).str.strip()
            return df
        except Exception:
            continue
    return pd.DataFrame(columns=["code", "name", "market", "sector", "note"])


def resolve_symbol_name(code: str, market: str) -> Optional[str]:
    """日本株は日本語名を優先して銘柄名を解決する。

    優先順:
      1. watchlist.csv に既存コード → そのname
      2. data/jpx_listed_companies.csv (日本株のみ)
      3. yfinance lookup_symbol_name (英語名・米国株メイン)
      4. None → 手入力
    """
    code = str(code or "").strip()
    if not code:
        return None
    mu = (market or "").upper()
    if mu == "US":
        code = code.upper()

    # 1) watchlist 既存
    try:
        w = load_watchlist()
        m = w[w["code"] == code]
        if not m.empty:
            nm = str(m.iloc[0].get("name", "")).strip()
            if nm:
                return nm
    except Exception:
        pass

    # 2) JPXマスタ (日本株のみ・日本語名)
    if mu == "JP":
        try:
            jpx = load_jpx_master()
            m = jpx[jpx["code"] == code]
            if not m.empty:
                nm = str(m.iloc[0].get("name", "")).strip()
                if nm:
                    return nm
        except Exception:
            pass

    # 3) yfinance (英語名)
    try:
        return lookup_symbol_name_cached(code, mu)
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=600)
def load_watchlist() -> pd.DataFrame:
    """data/watchlist.csv を読み込む。エンコーディング揺れに耐える。"""
    paths = [WATCHLIST_CSV]
    for enc in ("utf-8-sig", "cp932"):
        for path in paths:
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str)
                # 必須列
                for col in ("group", "code", "name", "market", "currency", "is_active"):
                    if col not in df.columns:
                        df[col] = ""
                df["code"] = df["code"].fillna("").astype(str).str.strip()
                df["is_active"] = pd.to_numeric(df["is_active"], errors="coerce").fillna(1).astype(int)
                return df
            except FileNotFoundError:
                continue
            except Exception:
                continue
    return pd.DataFrame(columns=["group", "code", "name", "market", "currency", "is_active", "note"])


@st.cache_data(show_spinner=False, ttl=600)
def load_positions() -> pd.DataFrame:
    """ポジションCSVを読み取り専用で参照。存在しなくてもアプリは動く。

    読み込み優先順位 (Streamlit Community Cloud対応):
      1. data/positions.csv (Cloud用・アプリ同梱)
      2. C:/stocks/data/current_positions_...csv (ローカル既存・読み取りのみ)
      3. どちらもなければ空のDataFrameを返し、watchlist のみで起動
    """
    candidates = [POSITIONS_CSV_APP, POSITIONS_CSV_LOCAL_FALLBACK]
    for path in candidates:
        if not path.exists():
            continue
        for enc in ("utf-8-sig", "cp932", "utf-8"):
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str)
                # 列名揺れ対応 (avg_price / avg_cost / 平均取得単価 / 取得単価 のいずれも吸収)
                col_map = {}
                for c in df.columns:
                    cl = c.lower().strip()
                    if cl in ("code", "コード", "銘柄コード"):
                        col_map[c] = "code"
                    elif cl in ("name", "銘柄名", "name_jp"):
                        col_map[c] = "name"
                    elif cl in ("shares", "数量", "株数"):
                        col_map[c] = "shares"
                    elif cl in ("avg_price", "avg_cost", "平均取得単価", "取得単価"):
                        col_map[c] = "avg_cost"
                    elif cl in ("category", "区分", "カテゴリ"):
                        col_map[c] = "category"
                    elif cl in ("currency", "通貨"):
                        col_map[c] = "currency"
                df = df.rename(columns=col_map)
                # 必須列だけ持たせる
                for col in ("code", "name", "shares", "avg_cost", "category", "currency"):
                    if col not in df.columns:
                        df[col] = ""
                df["code"] = df["code"].astype(str).str.strip()
                df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0).astype(float)
                df["avg_cost"] = pd.to_numeric(df["avg_cost"], errors="coerce")
                # 富士通6702・クボタ6326・キオクシア285A は除外 (positions.csv に含まれていても弾く)
                df = df[~df["code"].isin(EXCLUDED_FROM_PF)]
                # 父保有分の特別行も除外 (旧形式CSVの category=FATHER_PF / code=6702_father)
                df = df[~df["code"].str.contains("father", case=False, na=False)]
                if "category" in df.columns:
                    df = df[df["category"] != "FATHER_PF"]
                return df.reset_index(drop=True)
            except Exception:
                continue
    return pd.DataFrame(columns=["code", "name", "shares", "avg_cost", "category", "currency"])


# =============================================================================
# Price fetching
# =============================================================================

@st.cache_data(show_spinner=False, ttl=120)
def fetch_one(code: str, market: str, period: str, provider_name: str) -> PriceData:
    provider = get_provider(provider_name)
    return provider.fetch(code=code, market=market, period=period)


def fetch_all(watch_df: pd.DataFrame, period: str, provider_name: str) -> dict[str, PriceData]:
    out: dict[str, PriceData] = {}
    for _, row in watch_df.iterrows():
        code = row["code"]
        if not code:
            continue
        out[code] = fetch_one(code, row.get("market", "JP"), period, provider_name)
    return out


# =============================================================================
# Format helpers
# =============================================================================

def fmt_price(v: Optional[float], currency: str = "JPY") -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except Exception:
        return "-"
    if currency == "USD":
        return f"${v:,.2f}"
    if v >= 1000:
        return f"¥{v:,.0f}"
    return f"¥{v:,.2f}"


def fmt_change(price: PriceData) -> tuple[str, str]:
    """前日比表示 + マーク (青上昇/赤下降)。色記号は ▲/▼ 形式。"""
    if not price.ok or price.change is None or price.change_pct is None:
        return ("-", "")
    sign = "+" if price.change >= 0 else ""
    # プラス=青(▲)/マイナス=赤(▼)/ゼロ=灰(▪)
    if price.change > 0.0001:
        color = "🔵"
    elif price.change < -0.0001:
        color = "🔴"
    else:
        color = "⚪"
    return (f"{sign}{price.change:,.2f} ({sign}{price.change_pct:.2f}%)", color)


def fmt_volume(v: Optional[float]) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{int(v):,}"


def fmt_yen(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"¥{v:,.0f}"


# =============================================================================
# Chart helpers (Plotly)
# =============================================================================

def mini_chart(price: PriceData, height: int = 120) -> None:
    if not price.ok or price.history is None or price.history.empty:
        st.caption("チャート: データなし")
        return
    try:
        import plotly.graph_objects as go

        hist = price.history.tail(60)  # 直近60営業日のみ表示
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"],
            mode="lines", line=dict(width=1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(
            height=height,
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis=dict(showgrid=False, showticklabels=False),
            yaxis=dict(showgrid=False, showticklabels=True, side="right"),
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception:
        st.caption("チャート: 描画失敗")


# 足種選択肢: ラベル → (interval, period, period_label)
INTERVAL_OPTIONS: dict[str, tuple[str, str, str]] = {
    "1時間足": ("60m", "10d", "10日"),
    "日足": ("1d", "3mo", "3ヶ月"),
    "週足": ("1wk", "2y", "2年"),
}


@st.cache_data(show_spinner=False, ttl=180)
def fetch_history_cached(code: str, market: str, period: str, interval: str, provider_name: str) -> PriceData:
    provider = get_provider(provider_name)
    return provider.fetch_history(code=code, market=market, period=period, interval=interval)


def render_interval_chart(code: str, market: str, name: str, currency: str,
                          interval_label: str = "1時間足",
                          key_prefix: str = "chart",
                          height: int = 460) -> None:
    """1時間足/日足/週足 切替付きローソク足チャート (Home選択時・右カラム)。"""
    if interval_label not in INTERVAL_OPTIONS:
        interval_label = "日足"
    # 足種選択 UI
    interval_label = st.radio(
        "足種",
        list(INTERVAL_OPTIONS.keys()),
        index=list(INTERVAL_OPTIONS.keys()).index(interval_label),
        horizontal=True,
        key=f"{key_prefix}_interval",
    )
    interval, period, period_label = INTERVAL_OPTIONS[interval_label]

    price = fetch_history_cached(code, market, period, interval, "yfinance")

    # タイトル
    st.markdown(f"##### {name} {code} / {interval_label} / {period_label}")

    if not price.ok or price.history is None or price.history.empty:
        if interval == "60m":
            st.warning("1時間足データ取得不可。日足に切り替えてください。")
        else:
            err = price.error or "no data"
            st.error(f"チャート取得失敗 ({err})")
        return

    try:
        import plotly.graph_objects as go

        hist = price.history
        # OHLC が揃っていればローソク足・欠ければ終値折れ線にfallback
        ohlc_cols = ["Open", "High", "Low", "Close"]
        has_ohlc = (
            all(c in hist.columns for c in ohlc_cols)
            and not any(hist[c].dropna().empty for c in ohlc_cols)
        )

        fig = go.Figure()
        if has_ohlc:
            # ローソク足 (上昇=青 / 下降=赤 でアプリ配色に統一)
            fig.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["Open"], high=hist["High"],
                low=hist["Low"], close=hist["Close"],
                increasing_line_color="#2563eb",
                decreasing_line_color="#dc2626",
                increasing_fillcolor="#2563eb",
                decreasing_fillcolor="#dc2626",
                name="価格",
            ))
            fig.update_layout(xaxis_rangeslider_visible=False)
        else:
            # OHLC欠損 → 終値折れ線
            fig.add_trace(go.Scatter(
                x=hist.index, y=hist["Close"],
                mode="lines", line=dict(width=1.6),
                name="終値",
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:,.2f}<extra></extra>",
            ))

        fig.update_layout(
            height=height,
            margin=dict(l=12, r=12, t=12, b=28),
            xaxis=dict(showgrid=True, gridcolor="#eef1f5"),
            yaxis=dict(showgrid=True, gridcolor="#eef1f5", side="right"),
            showlegend=False,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        if not has_ohlc:
            st.caption("OHLCデータなしのため折れ線表示")

        # 現在値表示
        chg, color = fmt_change(price)
        st.caption(f"終値: {fmt_price(price.current_price, currency)}  {color} {chg}")
    except Exception as exc:
        st.error(f"チャート描画失敗: {exc.__class__.__name__}")


def full_chart(price: PriceData, height: int = 400) -> None:
    if not price.ok or price.history is None or price.history.empty:
        st.info("チャートデータが取得できませんでした")
        return
    try:
        import plotly.graph_objects as go

        hist = price.history
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=hist.index,
            open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"],
            name="価格",
        ))
        fig.update_layout(
            height=height,
            margin=dict(l=20, r=20, t=20, b=20),
            xaxis_rangeslider_visible=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.error(f"チャート描画失敗: {exc.__class__.__name__}")


# =============================================================================
# Compact table UI (Home用)
# =============================================================================
#
# 設計方針:
#   旧版は HTML+CSS 文字列で行を組み立てていたが、環境によってサニタイズされ
#   そのまま文字列表示される事故があった。安定性最優先で st.dataframe ベース
#   に作り直す。色分けは pandas Styler の applymap で軽く付ける (Streamlit
#   標準機能で安定動作)。Stylerが何らかの理由で失敗した場合も plain dataframe
#   にフォールバックする。


# プラス=青 / マイナス=赤 / ゼロ・未取得=グレー で統一
_COLOR_UP = "color: #2563eb"     # blue-600
_COLOR_DOWN = "color: #dc2626"   # red-600
_COLOR_FLAT = "color: #6b7280"   # gray-500


def _pct_color_style(v: object) -> str:
    """Styler.applymap/map 用: 数値テキスト (+x / -x / +x.xx% / ¥+343,200 等) に色を当てる。

    通貨記号・カンマ・空白を除去してから判定するため、評価損益の通貨フォーマットでも動作する。
    """
    if not isinstance(v, str):
        return ""
    s = v.strip()
    if s in ("-", "未取得", "取得失敗", "未入力", ""):
        return ""
    # 通貨記号・カンマ・円記号・空白を除去
    cleaned = (
        s.replace("¥", "")
        .replace("$", "")
        .replace(",", "")
        .replace("円", "")
        .replace(" ", "")
    )
    # ゼロ系チェック (符号付きゼロも含む)
    if cleaned in ("", "0", "+0", "-0", "0.00", "+0.00", "-0.00", "0.00%", "+0.00%", "-0.00%"):
        return _COLOR_FLAT
    # 符号で即判定
    if cleaned.startswith("+"):
        return _COLOR_UP
    if cleaned.startswith("-"):
        return _COLOR_DOWN
    # 符号なし数値の場合は float に変換して判定
    try:
        val = float(cleaned.rstrip("%"))
        if val > 0:
            return _COLOR_UP
        if val < 0:
            return _COLOR_DOWN
        return _COLOR_FLAT
    except Exception:
        return ""


def _build_home_rows(sub: pd.DataFrame, prices: dict[str, PriceData]) -> pd.DataFrame:
    """Home用の4列DataFrameを作る。
    列: 銘柄 / コード / 現在価格 / 前日騰落率
    """
    rows = []
    for _, row in sub.iterrows():
        code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip()
        currency = str(row.get("currency", "JPY")).strip() or "JPY"
        price = prices.get(code, PriceData(symbol=code, error="未取得"))

        if not price.ok or price.current_price is None:
            price_text = "取得失敗"
            pct_text = "-"
        else:
            price_text = fmt_price(price.current_price, currency)
            if price.change_pct is None:
                pct_text = "-"
            else:
                sign = "+" if price.change_pct >= 0 else ""
                pct_text = f"{sign}{price.change_pct:.2f}%"

        rows.append({
            "銘柄": name,
            "コード": code,
            "現在価格": price_text,
            "前日騰落率": pct_text,
        })
    return pd.DataFrame(rows, columns=["銘柄", "コード", "現在価格", "前日騰落率"])


def _home_header_text(row: pd.Series, price: PriceData) -> str:
    """expander見出し用の1行テキスト。

    Streamlitのexpanderヘッダーはplain text扱いで色CSSが効かないため、
    色の代わりに絵文字マーカーで上昇/下降を表す。
      プラス: 🔵 / マイナス: 🔴 / ゼロ: ⚪
    """
    code = str(row.get("code", "")).strip()
    name = str(row.get("name", "")).strip()
    currency = str(row.get("currency", "JPY")).strip() or "JPY"

    if not price.ok or price.current_price is None:
        return f"{name}  {code}  |  取得失敗"

    price_text = fmt_price(price.current_price, currency)
    if price.change_pct is None:
        return f"{name}  {code}  |  {price_text}  |  ⚪ -"

    sign = "+" if price.change_pct >= 0 else ""
    chg_text = f"{sign}{price.change_pct:.2f}%"
    if price.change_pct > 0.0001:
        marker = "🔵"
    elif price.change_pct < -0.0001:
        marker = "🔴"
    else:
        marker = "⚪"
    return f"{name}  {code}  |  {price_text}  |  {marker} {chg_text}"


def render_home_expander(row: pd.Series, price: PriceData) -> None:
    """1銘柄 = 1 expander。開いたときだけチャートを取得・表示する。"""
    code = str(row.get("code", "")).strip()
    name = str(row.get("name", "")).strip()
    market = str(row.get("market", "JP")).strip().upper() or "JP"
    currency = str(row.get("currency", "JPY")).strip().upper() or "JPY"

    header = _home_header_text(row, price)
    with st.expander(header, expanded=False):
        # 内部上部: 色付き Markdown で現在値・前日騰落率 (span1つのみ・サニタイズ低リスク)
        if price.ok and price.current_price is not None:
            cur_text = fmt_price(price.current_price, currency)
            if price.change_pct is None:
                st.markdown(
                    f"現在値 **{cur_text}**　前日騰落率 "
                    f"<span style='color:#6b7280; font-weight:600;'>-</span>",
                    unsafe_allow_html=True,
                )
            else:
                sign = "+" if price.change_pct >= 0 else ""
                if price.change_pct > 0.0001:
                    color = "#2563eb"
                elif price.change_pct < -0.0001:
                    color = "#dc2626"
                else:
                    color = "#6b7280"
                st.markdown(
                    f"現在値 **{cur_text}**　前日騰落率 "
                    f"<span style='color:{color}; font-weight:700;'>{sign}{price.change_pct:.2f}%</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("価格情報の取得に失敗しました")

        # 足種切替チャート (expanderを開いたときだけ呼ばれる)
        render_interval_chart(
            code=code,
            market=market,
            name=name,
            currency=currency,
            interval_label="1時間足",
            key_prefix=f"home_{code}",
            height=320,
        )
        link_cols = st.columns(2)
        link_cols[0].markdown(f"[📊 Yahoo]({yahoo_link(code, market)})")
        link_cols[1].markdown(f"[📈 TradingView]({tradingview_link(code, market)})")


def inject_home_css() -> None:
    """Home専用 CSS を注入する。

    重要:
    - グローバルCSS (div[data-testid="stHorizontalBlock"] や .stButton 全体) は当てない
    - block-container は **上部padding(padding-top)のみ** 控えめに詰める
      (レイアウト崩壊の原因になる left/right/bottom や display は触らない)
    - その他は .home-tile-grid / .home-tile / .home-tile-* スコープのみ
    - これにより Portfolio / Settings タブのレイアウトは崩れない
    """
    st.markdown(
        """
        <style>
        /* ===== ヘッダー上部の余白を少しだけ詰める (上部が切れない範囲) ===== */
        /* padding-top のみ調整・他のpadding/display/gridには一切触れない */
        @media (min-width: 641px) {
            /* PC: Streamlit標準(約6rem)は広すぎるので 2.2rem に */
            .stApp .block-container { padding-top: 2.2rem !important; }
        }
        @media (max-width: 640px) {
            /* スマホ: さらに詰める */
            .stApp .block-container { padding-top: 1.0rem !important; }
        }

        /* ===== Home タイルグリッド (このクラス配下にしか影響しない) ===== */
        .home-tile-grid {
            display: grid;
            gap: 8px;
            margin: 4px 0 12px 0;
        }
        /* PC: auto-fit で 140-180px のタイルを4〜6列敷き詰め */
        @media (min-width: 641px) {
            .home-tile-grid {
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 8px;
            }
        }
        /* スマホ: 3列固定 (361-640px) */
        @media (min-width: 361px) and (max-width: 640px) {
            .home-tile-grid {
                grid-template-columns: repeat(3, 1fr);
                gap: 4px;
            }
        }
        /* 小型スマホ: 2列 */
        @media (max-width: 360px) {
            .home-tile-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 3px;
            }
        }
        .home-tile {
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 76px;
            padding: 8px 10px;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            background: #ffffff;
            text-decoration: none !important;
            color: inherit !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            transition: box-shadow 0.15s, border-color 0.15s;
            overflow: hidden;
        }
        .home-tile:hover {
            border-color: #1f77b4;
            box-shadow: 0 2px 6px rgba(31,119,180,0.18);
        }
        .home-tile.selected {
            border-color: #1f77b4;
            background: #eff6ff;
            box-shadow: 0 2px 6px rgba(31,119,180,0.25);
        }
        .home-tile.selected .home-tile-name {
            font-weight: 700;
            color: #1f77b4;
        }
        .home-tile-name {
            font-size: 0.85rem;
            font-weight: 600;
            color: #1c1e21;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .home-tile-price {
            font-size: 1.0rem;
            font-weight: 700;
            color: #1c1e21;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .home-tile-pct {
            font-size: 0.85rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .home-tile-pct.up   { color: #2563eb; }  /* 青 */
        .home-tile-pct.down { color: #dc2626; }  /* 赤 */
        .home-tile-pct.flat { color: #6b7280; }  /* グレー */
        .home-tile-pct.err  { color: #9ca3af; font-weight: 500; font-size: 0.75rem; }
        .home-section-title {
            margin: 6px 0 4px 0;
            font-size: 1.0rem;
            font-weight: 700;
            color: #1c1e21;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _short_display_name(name: str, max_len: int = 8) -> str:
    """タイル用に銘柄名を短縮 (PCタイルが狭いとき用)。"""
    s = (name or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _tile_card_html(code: str, name: str, price: PriceData, currency: str,
                    selected_code: Optional[str]) -> str:
    """1銘柄分のHTMLタイルを生成する (a要素・query paramでクリック検知)。

    HTMLエスケープしたうえで .home-tile スコープのCSSのみに依存させる。
    """
    import html as _html

    code_safe = _html.escape(str(code))
    name_short = _short_display_name(name, max_len=8)
    name_safe = _html.escape(name_short)

    if not price.ok or price.current_price is None:
        price_text = "取得失敗"
        pct_html = '<div class="home-tile-pct err">—</div>'
    else:
        price_text = fmt_price(price.current_price, currency)
        if price.change_pct is None:
            pct_html = '<div class="home-tile-pct flat">—</div>'
        else:
            sign = "+" if price.change_pct >= 0 else ""
            if price.change_pct > 0.0001:
                cls = "up"
            elif price.change_pct < -0.0001:
                cls = "down"
            else:
                cls = "flat"
            pct_html = (
                f'<div class="home-tile-pct {cls}">'
                f'{_html.escape(sign)}{price.change_pct:.2f}%</div>'
            )
    price_safe = _html.escape(price_text)

    selected_cls = " selected" if (selected_code and selected_code == code) else ""
    # 同じ銘柄を再クリックで選択解除 (?select=)
    target = "" if (selected_code and selected_code == code) else code_safe
    href = f"?select={target}"

    return (
        f'<a class="home-tile{selected_cls}" href="{href}" target="_self" '
        f'title="{name_safe} ({code_safe})">'
        f'<div class="home-tile-name">{name_safe}</div>'
        f'<div class="home-tile-price">{price_safe}</div>'
        f'{pct_html}'
        f'</a>'
    )


def render_home_section(title: str, sub: pd.DataFrame, prices: dict[str, PriceData],
                        selected_code: Optional[str] = None) -> None:
    """Home用セクション: タイトル + HTMLタイルグリッド (.home-tile-grid スコープ)。

    - タイル数・列数は CSS の auto-fit / @media で自動調整
    - グローバルCSSは一切当てない (Portfolio/Settings に影響しない)
    - タイルクリック → ?select={code} クエリパラメータで選択検知
    """
    st.markdown(
        f'<div class="home-section-title">{title} ({len(sub)})</div>',
        unsafe_allow_html=True,
    )
    if sub.empty:
        st.caption("(対象なし)")
        return

    tiles_html = []
    for _, row in sub.iterrows():
        code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip() or code
        currency = str(row.get("currency", "JPY")).strip().upper() or "JPY"
        price = prices.get(code, PriceData(symbol=code, error="未取得"))
        tiles_html.append(_tile_card_html(code, name, price, currency, selected_code))

    html = '<div class="home-tile-grid">' + "".join(tiles_html) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# Card UI (Watch/Separateなど・詳細表示用)
# =============================================================================

def render_card(row: pd.Series, price: PriceData, position_row: Optional[pd.Series] = None) -> None:
    code = row["code"]
    name = row.get("name", "")
    market = row.get("market", "JP")
    currency = row.get("currency", "JPY")

    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(f"**{code}** {name}")
            st.markdown(f"### {fmt_price(price.current_price, currency)}")
        with c2:
            change_text, color = fmt_change(price)
            st.markdown(f"{color} {change_text}")
            st.caption(f"出来高: {fmt_volume(price.volume)}")

        if position_row is not None and float(position_row.get("shares", 0) or 0) > 0:
            shares = float(position_row["shares"])
            avg_cost = position_row.get("avg_cost")
            try:
                avg_cost = float(avg_cost) if pd.notna(avg_cost) else None
            except Exception:
                avg_cost = None

            value = price.current_price * shares if price.ok else None
            pnl = None
            pnl_pct = None
            if avg_cost is not None and price.ok:
                pnl = (price.current_price - avg_cost) * shares
                if avg_cost > 0:
                    pnl_pct = (price.current_price / avg_cost - 1) * 100

            pos_cols = st.columns(3)
            pos_cols[0].metric("保有株数", f"{int(shares):,}")
            pos_cols[1].metric("評価額", fmt_yen(value))
            if pnl is not None:
                pos_cols[2].metric(
                    "評価損益",
                    fmt_yen(pnl),
                    f"{pnl_pct:+.2f}%" if pnl_pct is not None else None,
                )

        mini_chart(price)

        with st.expander("詳細・外部リンク"):
            st.write(f"前日終値: {fmt_price(price.prev_close, currency)}")
            if price.last_update:
                st.caption(f"yfinance最終更新: {price.last_update.strftime('%Y-%m-%d')}")
            if price.error:
                st.error(f"取得失敗: {price.error}")
            link_cols = st.columns(2)
            link_cols[0].markdown(f"[📊 Yahoo]({yahoo_link(code, market)})")
            link_cols[1].markdown(f"[📈 TradingView]({tradingview_link(code, market)})")


# =============================================================================
# Pages
# =============================================================================

def _render_home_chart(sel_code: str, watch_df: pd.DataFrame,
                       prices: dict[str, PriceData]) -> None:
    """開いている銘柄のチャートを枠付きコンテナで描画する。

    - 各セクションのタイル一覧直下から呼ばれる (Home最下部固定はしない)
    - 現在値はkabu/yfinanceどちらでも同じ見た目で表示
    - チャート履歴は yfinance (kabuはsnapshotのみ)
    - 「✕ 閉じる」リンク + 同じタイル再クリックの両方で閉じられる
    """
    sel_row_df = watch_df[watch_df["code"].astype(str) == str(sel_code)]
    if sel_row_df.empty:
        return
    sel_row = sel_row_df.iloc[0]
    sel_code = str(sel_row.get("code", "")).strip()
    sel_name = str(sel_row.get("name", "")).strip() or sel_code
    sel_market = str(sel_row.get("market", "JP")).strip().upper() or "JP"
    sel_currency = str(sel_row.get("currency", "JPY")).strip().upper() or "JPY"
    sel_price = prices.get(sel_code, PriceData(symbol=sel_code, error="未取得"))

    with st.container(border=True):
        top_l, top_r = st.columns([6, 1])
        with top_l:
            if sel_price.ok and sel_price.current_price is not None:
                cur_text = fmt_price(sel_price.current_price, sel_currency)
                if sel_price.change_pct is None:
                    st.markdown(
                        f"**{sel_name}** ({sel_code})　現在値 **{cur_text}**　"
                        f"<span style='color:#6b7280; font-weight:600;'>—</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    sign = "+" if sel_price.change_pct >= 0 else ""
                    if sel_price.change_pct > 0.0001:
                        color = "#2563eb"
                    elif sel_price.change_pct < -0.0001:
                        color = "#dc2626"
                    else:
                        color = "#6b7280"
                    st.markdown(
                        f"**{sel_name}** ({sel_code})　現在値 **{cur_text}**　"
                        f"<span style='color:{color}; font-weight:700;'>"
                        f"{sign}{sel_price.change_pct:.2f}%</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption(f"{sel_name} ({sel_code}) — 価格情報の取得に失敗しました")
        with top_r:
            # 同じタイル再クリックでも閉じるが、明示的な閉じるリンクも用意
            st.markdown(
                '<a href="?select=" target="_self" '
                'style="text-decoration:none; color:#6b7280;">✕ 閉じる</a>',
                unsafe_allow_html=True,
            )

        render_interval_chart(
            code=sel_code,
            market=sel_market,
            name=sel_name,
            currency=sel_currency,
            interval_label="1時間足",
            key_prefix=f"home_sel_{sel_code}",
            height=460,
        )
        link_cols = st.columns(2)
        link_cols[0].markdown(f"[📊 Yahoo]({yahoo_link(sel_code, sel_market)})")
        link_cols[1].markdown(f"[📈 TradingView]({tradingview_link(sel_code, sel_market)})")


HOME_SORT_OPTIONS = [
    "登録順",
    "騰落率 高い順",
    "騰落率 低い順",
    "価格 高い順",
    "価格 低い順",
    "銘柄名順",
]


def _sort_home_sub(sub: pd.DataFrame, prices: dict[str, PriceData],
                   sort_mode: str) -> pd.DataFrame:
    """Home用に1グループ (保有/Watch) 内で並び替える。

    - 登録順: watchlist.csv の順 (そのまま返す)
    - 騰落率/価格: prices から値を引いてソート (取得失敗は常に最後)
    - 銘柄名順: name 昇順 (取得失敗は最後)
    - Portfolio の並び替えとは独立 (Homeタイルにのみ適用)
    """
    if sort_mode == "登録順" or sub.empty or sort_mode not in HOME_SORT_OPTIONS:
        return sub

    def _info(row) -> tuple[bool, Optional[float], Optional[float], str]:
        code = str(row.get("code", "")).strip()
        p = prices.get(code)
        ok = bool(p and p.ok and p.current_price is not None)
        cp = p.change_pct if (p and p.ok and p.change_pct is not None) else None
        price = p.current_price if (p and p.ok and p.current_price is not None) else None
        name = str(row.get("name", "")).strip()
        return ok, cp, price, name

    items = list(sub.iterrows())  # [(idx, Series), ...] — sorted()は安定なので登録順は保たれる

    if sort_mode == "騰落率 高い順":
        def key(it):
            ok, cp, _price, _name = _info(it[1])
            valid = ok and cp is not None
            return (0 if valid else 1, -(cp if cp is not None else 0.0))
    elif sort_mode == "騰落率 低い順":
        def key(it):
            ok, cp, _price, _name = _info(it[1])
            valid = ok and cp is not None
            return (0 if valid else 1, (cp if cp is not None else 0.0))
    elif sort_mode == "価格 高い順":
        def key(it):
            ok, _cp, price, _name = _info(it[1])
            valid = ok and price is not None
            return (0 if valid else 1, -(price if price is not None else 0.0))
    elif sort_mode == "価格 低い順":
        def key(it):
            ok, _cp, price, _name = _info(it[1])
            valid = ok and price is not None
            return (0 if valid else 1, (price if price is not None else 0.0))
    elif sort_mode == "銘柄名順":
        def key(it):
            ok, _cp, _price, name = _info(it[1])
            return (0 if ok else 1, name)
    else:
        return sub

    items_sorted = sorted(items, key=key)
    sorted_rows = [it[1] for it in items_sorted]
    return pd.DataFrame(sorted_rows).reset_index(drop=True)


def page_home(watch_df: pd.DataFrame, prices: dict[str, PriceData]) -> None:
    """Home: 未選択時は全幅タイル / 銘柄選択時のみPC左タイル・右チャートの2カラム。

    - 各タイル: 銘柄名 / 現在価格 / 前日騰落率 (青/赤/グレー)
    - 1687 ETF は yfinance fallback → manual_prices.csv で価格表示
    - タイルクリックで開閉 (同じ銘柄再クリックで閉じる)・現在値kabu優先/履歴yfinance
    - Home上部に並び替えselectbox (Portfolioとは別物・タイルのみに適用)
    - スマホでは選択時2カラムが縦積みになり、タイルの下にチャートが出る
    """
    # クエリパラメータから選択中銘柄を取得 (HTMLタイルの <a href="?select="> がクリック信号)
    try:
        selected_code = st.query_params.get("select")
        if isinstance(selected_code, list):
            selected_code = selected_code[0] if selected_code else None
        if selected_code == "":
            selected_code = None
    except Exception:
        selected_code = None

    # 開閉状態を session_state にも保持 (明示)。
    # 同じ銘柄の再クリックは _tile_card_html 側で href="?select=" になり閉じる。
    st.session_state["open_chart_code"] = selected_code

    valid_selection = (
        selected_code is not None
        and str(selected_code) in watch_df["code"].astype(str).values
    )

    # Home並び替え (Portfolioとは別物・小さめselectbox)
    sort_col, _spacer = st.columns([1.2, 2.8])
    with sort_col:
        sort_mode = st.selectbox(
            "並び替え", HOME_SORT_OPTIONS, index=0, key="home_sort_mode",
        )

    def _render_tiles() -> None:
        for group_name in (GROUP_HOLD, GROUP_WATCH):
            sub = watch_df[(watch_df["group"] == group_name) & (watch_df["is_active"] == 1)]
            if sub.empty:
                continue
            sub = _sort_home_sub(sub, prices, sort_mode)
            label = "保有銘柄" if group_name == GROUP_HOLD else "Watch銘柄"
            render_home_section(label, sub, prices, selected_code=selected_code)

    if valid_selection:
        # 選択時のみ2カラム (PC: 左タイル / 右チャート・スマホ: 縦積みでタイル下にチャート)
        left_col, right_col = st.columns([0.58, 0.42], gap="medium")
        with left_col:
            _render_tiles()
        with right_col:
            # 押された後にページ上部へ戻っても、右カラム上部にチャートが見える
            _render_home_chart(str(selected_code), watch_df, prices)
    else:
        # 未選択時: 全幅でタイルを敷き詰める (右カラム・説明文は出さない)
        _render_tiles()


def page_portfolio(positions_df: pd.DataFrame, prices: dict[str, PriceData]) -> None:
    st.markdown("### 💼 Portfolio")

    if positions_df.empty:
        st.info("ポジションCSVが読み込めませんでした。watchlist のみで起動中です。")
        return

    # ----- 1) 内部行を構築 (数値+表示用文字列を併記) -----
    rows = []
    total_cost = 0.0
    has_any_avg_cost = False
    for _, p in positions_df.iterrows():
        code = str(p["code"]).strip()
        if not code or code in EXCLUDED_FROM_PF:
            continue
        shares = float(p.get("shares", 0) or 0)
        if shares <= 0:
            continue
        avg_cost = p.get("avg_cost")
        try:
            avg_cost = float(avg_cost) if pd.notna(avg_cost) else None
        except Exception:
            avg_cost = None

        price = prices.get(code)
        cur = price.current_price if price and price.ok else None
        chg = price.change if price and price.ok else None
        chg_pct = price.change_pct if price and price.ok else None

        # 数値計算
        value_num = cur * shares if cur is not None else None
        pnl_num = (cur - avg_cost) * shares if (cur is not None and avg_cost is not None) else None
        pnl_pct_num = (cur / avg_cost - 1) * 100 if (cur is not None and avg_cost is not None and avg_cost > 0) else None

        if avg_cost is not None and shares:
            total_cost += avg_cost * shares
            has_any_avg_cost = True

        rows.append({
            "コード": code,
            "銘柄名": p.get("name", ""),
            "株数": int(shares),
            "平均取得単価": avg_cost,  # 数値 or None
            "現在値": cur,              # 数値 or None
            "評価額_num": value_num,
            "評価損益_num": pnl_num,
            "評価損益率_num": pnl_pct_num,
            "前日比_num": chg,
            "前日比率_num": chg_pct,
        })

    if not rows:
        st.info("有効な保有銘柄がありません")
        return

    # ----- 2) 並び替え selectbox + 内部数値列で sort -----
    # 並び替え定義: ラベル → (sort_key列, ascending, is_numeric)
    SORT_OPTIONS: dict[str, tuple[str, bool, bool]] = {
        "評価損益 大きい順": ("評価損益_num", False, True),
        "評価損益 小さい順": ("評価損益_num", True, True),
        "評価額 大きい順": ("評価額_num", False, True),
        "評価額 小さい順": ("評価額_num", True, True),
        "評価損益率 高い順": ("評価損益率_num", False, True),
        "評価損益率 低い順": ("評価損益率_num", True, True),
        "前日比率 高い順": ("前日比率_num", False, True),
        "前日比率 低い順": ("前日比率_num", True, True),
        "コード順": ("コード", True, False),
        "銘柄名順": ("銘柄名", True, False),
    }
    sort_label = st.selectbox(
        "並び替え",
        list(SORT_OPTIONS.keys()),
        index=0,  # 初期値: 評価損益 大きい順
        key="portfolio_sort_select",
        help="列見出しクリックではなく、この並び替え欄を使ってください (表ヘッダーソートは表示文字列順になり誤動作する場合があります)",
    )
    sort_col, ascending, is_numeric = SORT_OPTIONS[sort_label]

    df_internal = pd.DataFrame(rows)
    # NaN の扱い: 降順なら最下位 (-inf相当)、昇順なら最下位 (+inf相当) ・文字列なら空文字
    if is_numeric:
        fill_val = float("-inf") if not ascending else float("inf")
        df_internal["_sort_key"] = df_internal[sort_col].fillna(fill_val)
    else:
        df_internal["_sort_key"] = df_internal[sort_col].fillna("").astype(str)
    df_internal = df_internal.sort_values("_sort_key", ascending=ascending).drop(columns=["_sort_key"]).reset_index(drop=True)

    # ----- 3) ソート後に表示用文字列列を生成 -----
    def fmt_money(v: Optional[float]) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "未入力"
        sign = "+" if v >= 0 else ""
        return f"¥{sign}{v:,.0f}"

    def fmt_money_abs(v: Optional[float]) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "-"
        return f"¥{v:,.0f}"

    def fmt_num1(v: Optional[float]) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "-"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:,.1f}"

    def fmt_pct(v: Optional[float]) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "未入力"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    def fmt_pct_simple(v: Optional[float]) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "-"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    df_internal["平均取得単価_disp"] = df_internal["平均取得単価"].apply(
        lambda v: f"{v:,.1f}" if (v is not None and not (isinstance(v, float) and pd.isna(v))) else "未入力"
    )
    df_internal["現在値_disp"] = df_internal["現在値"].apply(
        lambda v: f"{v:,.1f}" if (v is not None and not (isinstance(v, float) and pd.isna(v))) else "-"
    )
    df_internal["評価額"] = df_internal["評価額_num"].apply(fmt_money_abs)
    df_internal["評価損益"] = df_internal["評価損益_num"].apply(fmt_money)
    df_internal["評価損益率"] = df_internal["評価損益率_num"].apply(fmt_pct)
    df_internal["前日比"] = df_internal["前日比_num"].apply(fmt_num1)
    df_internal["前日比率"] = df_internal["前日比率_num"].apply(fmt_pct_simple)

    # 表示列だけ抽出 (_num 系は表示しない)
    display_cols = [
        "コード", "銘柄名", "株数",
        "平均取得単価_disp", "現在値_disp",
        "評価額", "評価損益", "評価損益率", "前日比", "前日比率",
    ]
    df_display = df_internal[display_cols].rename(columns={
        "平均取得単価_disp": "平均取得単価",
        "現在値_disp": "現在値",
    })

    # ----- 4) 表 (損益・前日比系列に色付け) -----
    pnl_cols = [c for c in ("評価損益", "評価損益率", "前日比", "前日比率") if c in df_display.columns]
    styled_df = df_display
    ok_styled = False
    try:
        st_map = getattr(df_display.style, "map", None)
        if callable(st_map):
            styled_df = st_map(_pct_color_style, subset=pnl_cols)
            ok_styled = True
        else:
            styled_df = df_display.style.applymap(_pct_color_style, subset=pnl_cols)  # type: ignore[attr-defined]
            ok_styled = True
    except Exception:
        styled_df = df_display
        ok_styled = False

    table_height = min(600, 35 * (len(df_display) + 1) + 8)
    # keyを変えて古い列ヘッダーソート状態をリセット (上部の並び替えselectboxを正とする)
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=table_height,
        key="portfolio_table_v3",
    )
    if not ok_styled:
        st.warning("色付けに失敗しました (プレーン表示)")

    # ----- 5) 合計メトリクスを表の下に配置 -----
    total_value = float(df_internal["評価額_num"].sum(skipna=True))
    pnl_total = float(df_internal["評価損益_num"].sum(skipna=True)) if has_any_avg_cost else None
    pnl_pct_total: Optional[float] = None
    if has_any_avg_cost and total_cost > 0 and pnl_total is not None:
        pnl_pct_total = pnl_total / total_cost * 100

    metric_cols = st.columns(3)
    metric_cols[0].metric("日本株PF評価額合計", fmt_yen(total_value))
    if pnl_total is not None:
        metric_cols[1].metric(
            "評価損益合計",
            fmt_yen(pnl_total),
            f"{pnl_pct_total:+.2f}%" if pnl_pct_total is not None else None,
        )
        metric_cols[2].metric(
            "評価損益率",
            f"{pnl_pct_total:+.2f}%" if pnl_pct_total is not None else "-",
        )
    else:
        metric_cols[1].metric("評価損益合計", "未入力")
        metric_cols[2].metric("評価損益率", "未入力")
    # ※ 表の下には合計メトリクスのみ・注意書きは置かない (READMEとSettingsに記載済)


def _save_csv_with_backup(df: pd.DataFrame, path: Path) -> Optional[Path]:
    """CSV保存前に自動バックアップを作成して、UTF-8 (BOM) で保存する。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path: Optional[Path] = None
    if path.exists():
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{path.stem}_{ts}.csv"
        try:
            shutil.copy2(path, backup_path)
        except Exception:
            backup_path = None
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return backup_path


def _normalize_watchlist(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """watchlist編集後のバリデーション。問題があればメッセージを返す。"""
    msgs: list[str] = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["group", "code", "name", "market", "currency", "is_active", "note"]), ["空のテーブルです"]
    df = df.copy()
    for col in ("group", "code", "name", "market", "currency", "is_active", "note"):
        if col not in df.columns:
            df[col] = ""

    # 必須列正規化
    df["code"] = df["code"].fillna("").astype(str).str.strip()
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    df["group"] = df["group"].fillna("").astype(str).str.strip()
    df["market"] = df["market"].fillna("JP").astype(str).str.strip().str.upper()
    df["currency"] = df["currency"].fillna("JPY").astype(str).str.strip().str.upper()

    # is_active: 1/0/True/False を 1/0 に正規化
    def _to_flag(v) -> int:
        if pd.isna(v):
            return 1
        if isinstance(v, bool):
            return 1 if v else 0
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y"):
            return 1
        if s in ("0", "false", "no", "n", ""):
            return 0
        try:
            return 1 if int(float(s)) != 0 else 0
        except Exception:
            return 1
    df["is_active"] = df["is_active"].apply(_to_flag)

    # code/name 空欄行は削除
    before = len(df)
    df = df[(df["code"] != "") & (df["name"] != "")]
    dropped = before - len(df)
    if dropped:
        msgs.append(f"code/name が空欄の {dropped} 行を除外しました")

    # 不正な group は除外
    bad_group = ~df["group"].isin(GROUP_OPTIONS)
    if bad_group.any():
        msgs.append(f"group が無効な {bad_group.sum()} 行は保有として保存します")
        df.loc[bad_group, "group"] = GROUP_HOLD

    # 不正な market / currency を補正
    df.loc[~df["market"].isin(MARKET_OPTIONS), "market"] = "JP"
    df.loc[~df["currency"].isin(CURRENCY_OPTIONS), "currency"] = "JPY"

    # 重複コード警告 (削除はせず、最後の行を残す)
    if df["code"].duplicated().any():
        dup_codes = df[df["code"].duplicated(keep=False)]["code"].unique().tolist()
        msgs.append(f"重複コード: {', '.join(dup_codes)} (最後の行を採用)")
        df = df.drop_duplicates(subset=["code"], keep="last")

    df = df[["group", "code", "name", "market", "currency", "is_active", "note"]].reset_index(drop=True)
    return df, msgs


def _normalize_positions(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """positions編集後のバリデーション。"""
    msgs: list[str] = []
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "name", "shares", "avg_price", "currency", "note"]), ["空のテーブルです"]
    df = df.copy()
    for col in ("code", "name", "shares", "avg_price", "currency", "note"):
        if col not in df.columns:
            df[col] = ""

    df["code"] = df["code"].fillna("").astype(str).str.strip()
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    df["currency"] = df["currency"].fillna("JPY").astype(str).str.strip().str.upper()
    df["note"] = df["note"].fillna("").astype(str)

    # shares: 数値化できないものは 0
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    # avg_price: 数値化できないものは空欄
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce")

    before = len(df)
    df = df[(df["code"] != "") & (df["name"] != "")]
    dropped = before - len(df)
    if dropped:
        msgs.append(f"code/name が空欄の {dropped} 行を除外しました")

    # 除外銘柄 (6326/285A/6702) は positions に入れない
    excluded_rows = df["code"].isin(EXCLUDED_FROM_PF)
    if excluded_rows.any():
        msgs.append(f"除外銘柄 {df.loc[excluded_rows, 'code'].tolist()} を除外しました (Aさん日本株PF対象外)")
        df = df[~excluded_rows]

    df.loc[~df["currency"].isin(CURRENCY_OPTIONS), "currency"] = "JPY"

    if df["code"].duplicated().any():
        dup_codes = df[df["code"].duplicated(keep=False)]["code"].unique().tolist()
        msgs.append(f"重複コード: {', '.join(dup_codes)} (最後の行を採用)")
        df = df.drop_duplicates(subset=["code"], keep="last")

    df = df[["code", "name", "shares", "avg_price", "currency", "note"]].reset_index(drop=True)
    return df, msgs


# ----- かんたん追加/削除/一覧 用のユーティリティ -----

def _read_watchlist_raw() -> pd.DataFrame:
    """watchlist.csv を生で読む (キャッシュなし)。"""
    try:
        df = pd.read_csv(WATCHLIST_CSV, encoding="utf-8-sig", dtype=str)
    except Exception:
        df = pd.DataFrame(columns=["group", "code", "name", "market", "currency", "is_active", "note"])
    for col in ("group", "code", "name", "market", "currency", "is_active", "note"):
        if col not in df.columns:
            df[col] = ""
    df["is_active"] = pd.to_numeric(df["is_active"], errors="coerce").fillna(1).astype(int)
    df["code"] = df["code"].fillna("").astype(str).str.strip()
    return df


def _read_positions_raw() -> pd.DataFrame:
    path = DATA_DIR / "positions.csv"
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    except Exception:
        df = pd.DataFrame(columns=["code", "name", "shares", "avg_price", "currency", "note"])
    for col in ("code", "name", "shares", "avg_price", "currency", "note"):
        if col not in df.columns:
            df[col] = ""
    df["code"] = df["code"].fillna("").astype(str).str.strip()
    return df


def _upsert_watchlist(group: str, code: str, name: str, market: str, currency: str,
                     is_active: bool, note: str) -> tuple[pd.DataFrame, bool]:
    """既存コードがあれば更新、なければ追加。(df, was_update) を返す。"""
    df = _read_watchlist_raw()
    code = str(code).strip()
    if market == "US":
        code = code.upper()
    mask = df["code"] == code
    was_update = bool(mask.any())
    row = {
        "group": group,
        "code": code,
        "name": name.strip(),
        "market": market,
        "currency": currency,
        "is_active": 1 if is_active else 0,
        "note": note.strip(),
    }
    if was_update:
        for k, v in row.items():
            df.loc[mask, k] = v
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df, was_update


def _upsert_position(code: str, name: str, shares: float,
                    avg_price: Optional[float], currency: str, note: str) -> tuple[pd.DataFrame, bool]:
    df = _read_positions_raw()
    code = str(code).strip()
    mask = df["code"] == code
    was_update = bool(mask.any())
    row = {
        "code": code,
        "name": name.strip(),
        "shares": shares,
        "avg_price": "" if avg_price is None else avg_price,
        "currency": currency,
        "note": note.strip(),
    }
    if was_update:
        for k, v in row.items():
            df.loc[mask, k] = v
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df, was_update


def _delete_position_row(code: str) -> pd.DataFrame:
    df = _read_positions_raw()
    return df[df["code"] != str(code).strip()].reset_index(drop=True)


def _delete_watchlist_row(code: str) -> pd.DataFrame:
    df = _read_watchlist_raw()
    return df[df["code"] != str(code).strip()].reset_index(drop=True)


def _set_watchlist_group(code: str, new_group: str) -> pd.DataFrame:
    df = _read_watchlist_raw()
    mask = df["code"] == str(code).strip()
    if mask.any():
        df.loc[mask, "group"] = new_group
    return df


def _set_watchlist_is_active(code: str, active: bool) -> pd.DataFrame:
    df = _read_watchlist_raw()
    mask = df["code"] == str(code).strip()
    if mask.any():
        df.loc[mask, "is_active"] = 1 if active else 0
    return df


def _clear_caches() -> None:
    """銘柄CSV更新後、価格と読み込みのキャッシュをクリアして再描画に備える。"""
    try:
        load_watchlist.clear()
    except Exception:
        pass
    try:
        load_positions.clear()
    except Exception:
        pass
    try:
        fetch_one.clear()
    except Exception:
        pass
    try:
        fetch_history_cached.clear()
    except Exception:
        pass


# ----- かんたん追加フォーム -----

def _easy_add_form() -> None:
    st.markdown("##### ➕ 銘柄を追加")
    st.caption(
        "通常はこのフォームで追加します。コード入力後に「🔎 銘柄名を取得」を押すと yfinance から銘柄名を補完できます。"
    )

    # session_state 初期化
    st.session_state.setdefault("add_name", "")
    st.session_state.setdefault("add_code", "")

    # --- フォーム外: 区分・市場・コード・銘柄名取得ボタン ---
    c1, c2, c3 = st.columns(3)
    group_label = c1.selectbox("区分", [GROUP_HOLD, GROUP_WATCH, GROUP_EXCLUDED], index=1, key="add_group")
    market_label = c2.selectbox("市場", ["日本株", "米国株"], index=0, key="add_market_label")
    is_active = c3.checkbox("is_active (表示する)", value=True, key="add_is_active")

    market = "JP" if market_label == "日本株" else "US"
    currency = "JPY" if market == "JP" else "USD"

    c4, c5 = st.columns([2, 1])
    code = c4.text_input("銘柄コード", placeholder="例: 7203 / AAPL", key="add_code")
    with c5:
        st.write("")  # 高さ揃え
        if st.button("🔎 銘柄名を取得", use_container_width=True, key="lookup_name_btn"):
            code_for_lookup = (code or "").strip()
            if market == "US":
                code_for_lookup = code_for_lookup.upper()
            if not code_for_lookup:
                st.warning("先に銘柄コードを入力してください")
            else:
                with st.spinner("銘柄名を検索中... (watchlist → JPXマスタ → yfinance)"):
                    fetched = resolve_symbol_name(code_for_lookup, market)
                if fetched:
                    st.session_state["add_name"] = fetched
                    src = "JPXマスタ (日本語)" if market == "JP" else "yfinance"
                    st.success(f"銘柄名を取得しました: {fetched}  (source優先: watchlist → {src})")
                    st.rerun()
                else:
                    st.warning("銘柄名を取得できませんでした。手入力してください")

    name = st.text_input(
        "銘柄名",
        placeholder="例: トヨタ自動車 / Apple",
        key="add_name",
        help="「🔎 銘柄名を取得」で補完できます。日本株でも英語名で返る場合あり (手で修正可)",
    )

    note = st.text_input("メモ (任意)", placeholder="任意メモ", key="add_note")

    # 保有時の追加項目 (フォーム外でも保持される)
    shares: Optional[float] = None
    avg_price: Optional[float] = None
    if group_label == GROUP_HOLD:
        st.markdown("**保有情報** (保有の場合のみ入力)")
        pc1, pc2 = st.columns(2)
        shares = pc1.number_input("保有株数", min_value=0, step=100, value=0, key="add_shares")
        avg_price_str = pc2.text_input("平均取得単価 (空欄OK)", placeholder="例: 2652", key="add_avg_price")
        try:
            avg_price = float(avg_price_str) if avg_price_str.strip() else None
        except Exception:
            avg_price = None

    st.caption(
        "**入力例** — 日本株Watch: `7203 / トヨタ自動車` / 米国株Watch: `AAPL / Apple` / "
        "保有: `9433 / KDDI / 200株 / 2652円`"
    )
    submitted = st.button("➕ 銘柄を追加", type="primary", use_container_width=True, key="add_submit_btn")

    if not submitted:
        return

    # バリデーション
    code_clean = (code or "").strip()
    if market == "US":
        code_clean = code_clean.upper()
    if not code_clean or not (name or "").strip():
        st.error("銘柄コードと銘柄名は必須です")
        return

    # 1) watchlist.csv へ upsert
    w_df, w_was_update = _upsert_watchlist(
        group=group_label, code=code_clean, name=name, market=market,
        currency=currency, is_active=is_active, note=note,
    )
    w_norm, _ = _normalize_watchlist(w_df)
    _save_csv_with_backup(w_norm, WATCHLIST_CSV)

    # 2) 保有のときだけ positions.csv へも upsert
    pos_action = ""
    if group_label == GROUP_HOLD:
        p_df, p_was_update = _upsert_position(
            code=code_clean, name=name, shares=float(shares or 0),
            avg_price=avg_price, currency=currency, note=note,
        )
        p_norm, _ = _normalize_positions(p_df)
        _save_csv_with_backup(p_norm, DATA_DIR / "positions.csv")
        pos_action = " + positions.csvにも追加" if not p_was_update else " + positions.csv更新"

    _clear_caches()
    verb = "更新しました" if w_was_update else "追加しました"
    st.success(f"✅ {group_label}銘柄 {code_clean} {name} を{verb}{pos_action}")
    st.info(
        "ローカル起動時は即反映されます。Streamlit Community Cloud では一時保存になる場合があるため、"
        "永続化には Settings 下部の「⬇️ ダウンロード」でCSVを取得して GitHub private repo に push してください。"
    )
    st.rerun()


# ----- かんたん削除/非表示フォーム -----

def _easy_delete_form() -> None:
    st.markdown("##### 🗑 銘柄を削除・非表示")
    st.caption(
        "「非表示」「除外へ移動」は履歴を残します。「完全削除」は確認チェックが必要です。"
    )

    df_w = _read_watchlist_raw()
    if df_w.empty:
        st.info("登録銘柄がありません")
        return

    options = [
        (f"{r['code']} {r['name']} ({r['group']})", str(r["code"]))
        for _, r in df_w.iterrows()
    ]
    labels = [o[0] for o in options]
    label_to_code = dict(options)

    with st.form("easy_delete_form", clear_on_submit=False):
        target_label = st.selectbox("対象銘柄", labels)
        operation = st.radio(
            "操作",
            ["非表示にする (is_active=0)", "Watchへ移動", "保有へ移動", "除外へ移動", "完全削除"],
            index=0,
        )
        confirm = False
        if operation == "完全削除":
            confirm = st.checkbox("完全削除することを確認しました (チェックがないと実行されません)")
        run = st.form_submit_button("🚀 実行", type="primary", use_container_width=True)

    if not run:
        return

    code = label_to_code[target_label]

    if operation == "完全削除":
        if not confirm:
            st.warning("確認チェックが入っていないため実行しませんでした")
            return
        new_w = _delete_watchlist_row(code)
        w_norm, _ = _normalize_watchlist(new_w)
        _save_csv_with_backup(w_norm, WATCHLIST_CSV)
        new_p = _delete_position_row(code)
        p_norm, _ = _normalize_positions(new_p)
        _save_csv_with_backup(p_norm, DATA_DIR / "positions.csv")
        msg = f"✅ {code} を watchlist と positions から完全削除しました"
    elif operation == "非表示にする (is_active=0)":
        new_w = _set_watchlist_is_active(code, False)
        w_norm, _ = _normalize_watchlist(new_w)
        _save_csv_with_backup(w_norm, WATCHLIST_CSV)
        msg = f"✅ {code} を非表示にしました (is_active=0)"
    elif operation == "Watchへ移動":
        new_w = _set_watchlist_group(code, GROUP_WATCH)
        w_norm, _ = _normalize_watchlist(new_w)
        _save_csv_with_backup(w_norm, WATCHLIST_CSV)
        # positions.csv から削除するか確認 (シンプルに削除)
        new_p = _delete_position_row(code)
        p_norm, _ = _normalize_positions(new_p)
        _save_csv_with_backup(p_norm, DATA_DIR / "positions.csv")
        msg = f"✅ {code} を Watch へ移動し、positions.csv からも削除しました"
    elif operation == "保有へ移動":
        new_w = _set_watchlist_group(code, GROUP_HOLD)
        w_norm, _ = _normalize_watchlist(new_w)
        _save_csv_with_backup(w_norm, WATCHLIST_CSV)
        # positions.csv になければ追加 (株数0・取得単価空欄)
        p_df = _read_positions_raw()
        if code not in p_df["code"].values:
            row = df_w[df_w["code"] == code].iloc[0]
            p_df, _ = _upsert_position(
                code=code, name=str(row["name"]), shares=0.0,
                avg_price=None, currency=str(row.get("currency", "JPY")), note="",
            )
            p_norm, _ = _normalize_positions(p_df)
            _save_csv_with_backup(p_norm, DATA_DIR / "positions.csv")
            msg = f"✅ {code} を保有へ移動し、positions.csv に追加 (株数0で初期化) しました"
        else:
            msg = f"✅ {code} を保有へ移動しました (positions.csv は既存)"
    elif operation == "除外へ移動":
        new_w = _set_watchlist_group(code, GROUP_EXCLUDED)
        w_norm, _ = _normalize_watchlist(new_w)
        _save_csv_with_backup(w_norm, WATCHLIST_CSV)
        new_p = _delete_position_row(code)
        p_norm, _ = _normalize_positions(new_p)
        _save_csv_with_backup(p_norm, DATA_DIR / "positions.csv")
        msg = f"✅ {code} を除外へ移動し、positions.csv からも削除しました"
    else:
        msg = "(不明な操作)"

    _clear_caches()
    st.success(msg)
    st.info(
        "ローカル起動時は即反映されます。Streamlit Community Cloud では一時保存になる場合があるため、"
        "永続化には CSV ダウンロード → GitHub private repo の更新が必要です。"
    )
    st.rerun()


# ----- 現在の登録銘柄一覧 (表示専用) -----

def _registered_list_view() -> None:
    st.markdown("##### 📋 現在の登録銘柄一覧 (表示専用)")
    df_w = _read_watchlist_raw()
    if df_w.empty:
        st.caption("(登録なし)")
        return

    df_show = df_w[["group", "code", "name", "market", "currency", "is_active", "note"]].copy()

    for group_name in (GROUP_HOLD, GROUP_WATCH, GROUP_EXCLUDED):
        sub = df_show[df_show["group"] == group_name]
        with st.expander(f"{group_name}  ({len(sub)})", expanded=(group_name == GROUP_HOLD)):
            if sub.empty:
                st.caption("(なし)")
            else:
                st.dataframe(sub.reset_index(drop=True), use_container_width=True, hide_index=True)


def _watchlist_editor_section() -> None:
    st.markdown("##### 銘柄マスタ編集 (watchlist.csv)")
    # 元データを読み直し (キャッシュを介さない)
    try:
        cur = pd.read_csv(WATCHLIST_CSV, encoding="utf-8-sig", dtype=str)
    except Exception:
        cur = pd.DataFrame(columns=["group", "code", "name", "market", "currency", "is_active", "note"])
    # is_active を bool 風に編集しやすくする
    cur["is_active"] = pd.to_numeric(cur["is_active"], errors="coerce").fillna(1).astype(int).astype(bool)

    st.caption(f"現在の行数: **{len(cur)}** 行 (保存前にここで確認できます)")

    # テンプレート行追加のガイド (実際の行追加は data_editor の「＋」を使う)
    tcols = st.columns(2)
    if tcols[0].button("📋 Watch銘柄テンプレート", key="tmpl_watch"):
        st.session_state["_tmpl_msg"] = (
            "▼ 下の表で「＋」を押し、以下の値を入れてください:\n\n"
            "- group = `Watch`\n"
            "- code = 4桁(日本株) or ティッカー(米国株)\n"
            "- name = 表示名\n"
            "- market = `JP` or `US`\n"
            "- currency = `JPY` or `USD`\n"
            "- is_active = ✅ チェック\n"
            "- note = 任意メモ"
        )
    if tcols[1].button("📋 保有銘柄テンプレート", key="tmpl_hold"):
        st.session_state["_tmpl_msg"] = (
            "▼ 保有銘柄は **watchlist.csv** と **positions.csv** の両方に追加してください:\n\n"
            "**watchlist.csv 側**:\n"
            "- group = `保有`\n"
            "- code / name / market / currency を入力\n"
            "- is_active = ✅ チェック\n\n"
            "**positions.csv 側** (下のセクション):\n"
            "- 同じ code を追加し、shares (株数) と avg_price (取得単価) を入力"
        )
    if "_tmpl_msg" in st.session_state:
        st.info(st.session_state["_tmpl_msg"])

    column_config = {
        "group": st.column_config.SelectboxColumn("group", options=GROUP_OPTIONS, required=True),
        "code": st.column_config.TextColumn("code", required=True),
        "name": st.column_config.TextColumn("name", required=True),
        "market": st.column_config.SelectboxColumn("market", options=MARKET_OPTIONS, required=True),
        "currency": st.column_config.SelectboxColumn("currency", options=CURRENCY_OPTIONS, required=True),
        "is_active": st.column_config.CheckboxColumn("is_active", default=True),
        "note": st.column_config.TextColumn("note"),
    }
    edited = st.data_editor(
        cur,
        column_config=column_config,
        num_rows="dynamic",
        use_container_width=True,
        key="watchlist_editor",
    )

    cols = st.columns([1, 1, 2])
    save_clicked = cols[0].button("💾 watchlist.csv を保存", type="primary", key="save_watchlist")
    normalized, _ = _normalize_watchlist(edited.copy())
    cols[1].download_button(
        "⬇️ ダウンロード",
        data=normalized.to_csv(index=False).encode("utf-8-sig"),
        file_name="watchlist.csv",
        mime="text/csv",
        key="dl_watchlist",
    )

    if save_clicked:
        norm, msgs = _normalize_watchlist(edited.copy())
        backup = _save_csv_with_backup(norm, WATCHLIST_CSV)
        load_watchlist.clear()
        if msgs:
            for m in msgs:
                st.warning(m)
        st.success(
            f"✅ watchlist.csv を保存しました ({len(norm)} 行)"
            + (f" / バックアップ: {backup.name}" if backup else "")
        )
        st.info(
            "ローカル起動時は保存内容が即反映されます。"
            "Streamlit Community Cloud では一時保存になることがあるため、"
            "永続化には「⬇️ ダウンロード」したCSVを GitHub private repo に push してください。"
        )
        st.rerun()


def _positions_editor_section() -> None:
    st.markdown("##### 保有ポジション編集 (positions.csv)")
    pos_path = DATA_DIR / "positions.csv"
    try:
        cur = pd.read_csv(pos_path, encoding="utf-8-sig", dtype=str)
    except Exception:
        cur = pd.DataFrame(columns=["code", "name", "shares", "avg_price", "currency", "note"])
    for col in ("code", "name", "shares", "avg_price", "currency", "note"):
        if col not in cur.columns:
            cur[col] = ""

    st.caption(f"現在の行数: **{len(cur)}** 行 (保存前にここで確認できます)")

    column_config = {
        "code": st.column_config.TextColumn("code", required=True),
        "name": st.column_config.TextColumn("name", required=True),
        "shares": st.column_config.NumberColumn("shares", min_value=0, step=100),
        "avg_price": st.column_config.NumberColumn("avg_price (空欄OK)", step=1),
        "currency": st.column_config.SelectboxColumn("currency", options=CURRENCY_OPTIONS, required=True),
        "note": st.column_config.TextColumn("note"),
    }
    edited = st.data_editor(
        cur,
        column_config=column_config,
        num_rows="dynamic",
        use_container_width=True,
        key="positions_editor",
    )

    cols = st.columns([1, 1, 2])
    save_clicked = cols[0].button("💾 positions.csv を保存", type="primary", key="save_positions")
    normalized, _ = _normalize_positions(edited.copy())
    cols[1].download_button(
        "⬇️ ダウンロード",
        data=normalized.to_csv(index=False).encode("utf-8-sig"),
        file_name="positions.csv",
        mime="text/csv",
        key="dl_positions",
    )

    if save_clicked:
        norm, msgs = _normalize_positions(edited.copy())
        backup = _save_csv_with_backup(norm, pos_path)
        load_positions.clear()
        if msgs:
            for m in msgs:
                st.warning(m)
        st.success(
            f"✅ positions.csv を保存しました ({len(norm)} 行)"
            + (f" / バックアップ: {backup.name}" if backup else "")
        )
        st.info(
            "ローカル起動時は保存内容が即反映されます。"
            "Streamlit Community Cloud では一時保存になることがあるため、"
            "永続化には「⬇️ ダウンロード」したCSVを GitHub private repo に push してください。"
        )
        st.rerun()


def page_settings() -> None:
    st.markdown("### ⚙️ Settings")

    st.markdown("#### 📡 価格データ取得元 (Provider)")
    # 既定はauto。kabu利用可ならauto/kabu_stationでkabu優先、Cloudではyfinanceへ自動fallback。
    provider_options = ["auto", "kabu_station", "yfinance"]
    current = st.session_state.get("provider_name", "auto")
    if current not in provider_options:
        current = "auto"
    chosen = st.selectbox(
        "Provider",
        provider_options,
        index=provider_options.index(current),
        key="provider_name_select",
        help="ローカルPCでkabuステーション起動中なら kabu_station / auto がおすすめ。Cloudではyfinance固定推奨。",
    )
    if chosen != st.session_state.get("provider_name"):
        st.session_state["provider_name"] = chosen
        # キャッシュをクリアして新providerで再取得させる
        try:
            fetch_one.clear()
            fetch_history_cached.clear()
        except Exception:
            pass
        st.rerun()
    st.caption(
        "- **auto** (推奨): kabuステーション → yfinance → manual の順で取得\n"
        "- **kabu_station**: ローカルPCでkabuステーション起動中のみ使用可能 (米国株は自動でyfinanceへ)\n"
        "- **yfinance**: Cloudでも使えるが遅延・証券会社画面と差異あり\n"
        "- Cloud/スマホからは kabuステーションへ直接接続できないため、自動的にyfinanceへfallback\n"
        "- 本アプリは閲覧専用です。**注文API (/sendorder, /cancelorder 等) は呼びません**"
    )

    st.markdown("---")
    st.markdown("#### 表示グループ")
    cols = st.columns(2)
    cols[0].checkbox("保有銘柄", value=True, key="show_holdings", disabled=True)
    cols[1].checkbox("Watch銘柄", value=True, key="show_watch", disabled=True)
    st.caption("(別枠カテゴリは廃止し、保有またはWatchに統合しました)")

    st.markdown("---")
    st.markdown("#### 🗂 銘柄管理")
    st.caption(
        "通常はこのフォームで銘柄の追加・削除を行ってください。保存時に `data/backups/` へ自動バックアップが作成されます。"
    )

    with st.expander("⚠️ Streamlit Cloud 利用時の注意 (必ず確認)", expanded=False):
        st.markdown(
            "- **ローカル起動**: 保存ボタンで CSV が即永続更新されます\n"
            "- **Streamlit Community Cloud**: 保存は **一時保存** になる場合があります (再デプロイで初期状態に戻ることがあります)\n"
            "- 確実に残したい場合は **CSVをダウンロード → GitHub private repository に commit & push** してください\n"
            "- `data/positions.csv` には株数・取得単価が含まれるため **public repository には絶対に置かない** こと"
        )

    # 1) かんたん追加フォーム
    _easy_add_form()

    st.markdown("")
    # 2) かんたん削除/非表示フォーム
    _easy_delete_form()

    st.markdown("")
    # 3) 現在の登録銘柄一覧 (表示専用)
    _registered_list_view()

    st.markdown("")
    # 4) 詳細CSV編集 (上級者向け・折りたたみ)
    with st.expander("🛠 詳細CSV編集 (上級者向け)", expanded=False):
        st.caption(
            "通常は上のフォームを使ってください。CSVを直接編集したい場合だけここを開いてください。"
            " 保存時にバックアップが作成されます。"
        )
        _watchlist_editor_section()
        st.markdown("")
        _positions_editor_section()

    st.markdown("#### データ取得元")
    st.radio(
        "Provider",
        ["yfinance (現在)", "Rakuten RSS (将来)", "Tachibana API (将来)"],
        index=0,
        disabled=True,
    )
    st.caption("初期版は yfinance のみ。Provider クラスを差し替えれば将来移行できる構造です。")

    st.markdown("#### 更新間隔")
    st.caption("Home画面上部の自動更新セレクトで切り替えられます (なし/60秒/180秒/300秒)。")

    st.markdown("#### アクセス制御")
    st.markdown(
        "- アプリ内パスワード認証は廃止しました\n"
        "- 外部公開は **Streamlit Community Cloud の private app** として配信してください\n"
        "- アクセス制御は Cloud 側のログイン (Streamlit/Google/GitHub) に委ねます\n"
        "- GitHub repository は **private 必須** (株数・取得単価情報が含まれるため)\n"
        "- 初回のみCloudログインが必要・以降はスマホのログイン状態でブックマーク再開可能"
    )

    st.markdown("#### yfinance版の限界")
    st.markdown(
        "- 完全リアルタイムではない (遅延/準リアルタイム)\n"
        "- 日本株は数分単位で遅れる可能性\n"
        "- 板情報・約定情報・証券口座情報は取れない\n"
        "- ファンダメンタル情報は本アプリでは使わない (価格・出来高のみ)\n"
        "- 価格誤差はあり得る"
    )


# =============================================================================
# Auto-refresh helper (シンプル実装)
# =============================================================================

def schedule_autorefresh(interval_sec: int) -> None:
    """st.experimental_rerun ベースの簡易自動更新。0なら無効。"""
    if interval_sec <= 0:
        return
    # Streamlit >= 1.18 推奨: st_autorefresh が便利だが追加依存を避けるため簡易JSで対応。
    components_html = f"""
    <script>
      setTimeout(function() {{ window.parent.location.reload(); }}, {interval_sec * 1000});
    </script>
    """
    try:
        import streamlit.components.v1 as components  # type: ignore
        components.html(components_html, height=0)
    except Exception:
        pass


# =============================================================================
# Main
# =============================================================================

def _save_kabu_latest_csv(prices: dict[str, PriceData],
                          watch_df: pd.DataFrame,
                          fetched_at: dt.datetime) -> None:
    """kabu_station から取得できた銘柄を data/kabu_prices_latest.csv に保存。

    - .gitignore対象 (ローカル中間ファイル・GitHubには上げない)
    - 1銘柄も kabu source が無ければ何もしない (旧ファイルはそのまま)
    - 失敗してもアプリ全体を落とさない
    """
    try:
        out_path = DATA_DIR / "kabu_prices_latest.csv"
        # watch_df から name 引き当て用辞書
        name_by_code: dict[str, str] = {}
        for _, r in watch_df.iterrows():
            c = str(r.get("code", "")).strip()
            n = str(r.get("name", "")).strip()
            if c:
                name_by_code[c] = n

        rows: list[dict] = []
        updated_iso = fetched_at.isoformat(timespec="seconds")
        for code, p in prices.items():
            if not p.ok or p.source != "kabu_station":
                continue
            name = name_by_code.get(str(code), "")
            price_time = ""
            if p.last_update is not None:
                try:
                    price_time = p.last_update.isoformat(timespec="seconds")
                except Exception:
                    price_time = ""
            rows.append({
                "code": str(code),
                "name": name,
                "price": "" if p.current_price is None else f"{p.current_price}",
                "previous_close": "" if p.prev_close is None else f"{p.prev_close}",
                "change": "" if p.change is None else f"{p.change:.2f}",
                "change_pct": "" if p.change_pct is None else f"{p.change_pct:.4f}",
                "volume": "" if p.volume is None else f"{p.volume}",
                "price_time": price_time,
                "source": "kabu_station",
                "updated_at": updated_iso,
            })
        if not rows:
            return
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["code", "name", "price", "previous_close", "change", "change_pct",
                "volume", "price_time", "source", "updated_at"]
        df = pd.DataFrame(rows, columns=cols)
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    except Exception:
        # 保存失敗でアプリを止めない
        pass


def main() -> None:
    # Home専用CSSを注入 (.home-tile-grid / .home-tile スコープのみ・グローバルCSSは当てない)
    inject_home_css()

    # ヘッダー (タイトルはh4で少しだけコンパクトに・更新ボタン/自動更新は通常サイズ)
    header_cols = st.columns([5, 2, 2])
    with header_cols[0]:
        st.markdown("#### 📈 Aさん株価ボード")
    with header_cols[1]:
        if st.button("🔄 手動更新", type="primary", use_container_width=True):
            # 価格キャッシュのみクリア。session_state (home_sort_mode 等) と
            # URLクエリ (?select=) は触らないので、Home並び替え・選択中チャートは維持される。
            fetch_one.clear()
            fetch_history_cached.clear()
            st.rerun()
    with header_cols[2]:
        interval = st.selectbox("自動更新", ["なし", "60秒", "180秒", "300秒"], index=0)

    interval_map = {"なし": 0, "60秒": 60, "180秒": 180, "300秒": 300}
    schedule_autorefresh(interval_map[interval])

    # データロード
    watch_df = load_watchlist()
    positions_df = load_positions()

    if watch_df.empty:
        st.error("watchlist.csv が読み込めません。data/watchlist.csv を確認してください。")
        st.stop()

    # アクティブな表示対象だけ価格取得 (除外グループは取得しない)
    visible = watch_df[(watch_df["is_active"] == 1) & (watch_df["group"] != GROUP_EXCLUDED)]

    # Provider 選択 (Settings タブで切替・初期値 auto)
    provider_name = st.session_state.get("provider_name", "auto")

    with st.spinner("価格データ取得中..."):
        prices = fetch_all(visible, period="6mo", provider_name=provider_name)
    # JSTで取得時刻を記録 (Streamlit CloudはUTC環境のため明示変換が必要)
    fetched_at = dt.datetime.now(JST)

    # ----- 価格データ鮮度表示 (ヘッダー直下に1か所だけ・タブを問わず共通) -----
    # 銘柄タイルやPortfolio表内には source / data_time を入れない。
    # 実際に使われた source を集計して表記を決める。
    n_kabu = sum(1 for p in prices.values() if p.ok and p.source == "kabu_station")
    yfinance_sources = ("yfinance", "yfinance_5d", "fast_info", "info")
    n_yf = sum(1 for p in prices.values() if p.ok and p.source in yfinance_sources)
    n_manual = sum(1 for p in prices.values() if p.ok and p.source == "manual")

    if n_kabu > 0 and n_yf == 0 and n_manual == 0:
        freshness_label = "📡 kabuステーション価格"
        freshness_note = "ローカルPC取得 (注文APIは呼びません)"
    elif n_kabu == 0:
        freshness_label = "📡 yfinance参考価格"
        freshness_note = "証券会社画面と差異あり (最終判断は証券会社の正式画面で)"
    else:
        freshness_label = f"📡 価格データ: kabu優先 / yfinance fallback"
        freshness_note = f"kabu {n_kabu} 銘柄 / yfinance {n_yf} 銘柄"
        if n_manual:
            freshness_note += f" / manual {n_manual} 銘柄"
    st.caption(
        f"{freshness_label} ｜ 最終取得 {fetched_at.strftime('%H:%M')} ｜ {freshness_note}"
    )

    # kabu取得分だけ data/kabu_prices_latest.csv に保存 (.gitignore 対象・ローカル中間ファイル)
    _save_kabu_latest_csv(prices, watch_df, fetched_at)

    # 取得失敗があってもHome画面トップに大きな警告は出さない (各タイル内に「取得失敗」と小さく表示する)。

    # タブ (Chartsタブ廃止・チャートはHomeのexpander内で確認)
    tabs = st.tabs(["🏠 Home", "💼 Portfolio", "⚙️ Settings"])
    with tabs[0]:
        page_home(watch_df, prices)
    with tabs[1]:
        page_portfolio(positions_df, prices)
    with tabs[2]:
        page_settings()

    # フッター注意
    st.markdown("---")
    st.caption(
        "🛡️ 本アプリは閲覧専用です。自動発注機能はありません。証券会社ログイン情報も保存しません。"
        " 株価データは yfinance による遅延/準リアルタイム取得です。"
    )


if __name__ == "__main__":
    main()
