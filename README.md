# Aさん専用 株価チェックボード (Streamlit)

外出先スマホで現在価格・前日比・評価額・簡易チャートを確認するための **閲覧専用** Webアプリです。

## 🛡️ 重要な仕様 (セキュリティ)

- **自動発注機能なし** (絶対に入れない)
- **証券会社ログイン情報は保存しない**
- **既存I.5/I.4/M.1/E.2/I.1原本・v3/v4・settings は変更しない**
- **既存レポート・既存CSV は読み取り専用**
- **yfinance は価格・出来高・チャート用の価格データ取得のみ** に使用 (ファンダ補完なし)
- **アプリ内パスワード認証は廃止** — Streamlit Community Cloud の **private app** として配信し、Cloud側のログイン (Streamlit/Google/GitHub) でアクセス制御
- GitHub repository は **private 必須** (株数・取得単価情報が含まれるため)

## 📂 ファイル構成

```
C:\stocks\app\stock_board\
├── app.py                          # Streamlit メインアプリ
├── price_provider.py               # Provider 抽象化 (yfinance初期実装)
├── data/
│   ├── watchlist.csv               # 表示対象銘柄リスト
│   ├── positions.csv               # 保有株数・取得単価 (Cloud対応・優先読み込み)
│   ├── jpx_listed_companies.csv    # 日本語銘柄名マスタ
│   └── manual_prices.csv           # 取得失敗時の手動価格 (1687 ETF等の最終fallback)
├── requirements.txt
├── README.md
├── .gitignore
└── .streamlit/
    └── config.toml
```

## 🚀 ローカル起動

```powershell
cd C:\stocks\app\stock_board
pip install -r requirements.txt
streamlit run app.py
```

ブラウザが自動で開きます (デフォルトは http://localhost:8501)。

### スマホでローカル確認

PC と同じWi-Fi内のスマホからアクセスする方法：

```powershell
cd C:\stocks\app\stock_board
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

別ターミナルで PC の IP を確認：

```powershell
ipconfig
```

「IPv4 アドレス」の値 (例: `192.168.1.20`) をメモし、スマホブラウザで以下を開く：

```
http://192.168.1.20:8501
```

> Windows ファイアウォールで初回アクセス時にブロック解除を求められたら許可してください。

## ☁️ 外出先から見る方法 (Streamlit Community Cloud private app)

### 運用方針
- **private repository (GitHub)** + **private app (Streamlit Cloud)** で運用する前提
- アクセス制御は **Streamlit Cloud 側のログイン**に委ねる (Streamlit/Google/GitHubアカウント)
- アプリ内でのパスワード入力は **なし**
- 初回のみスマホでCloudログインが必要 → 2回目以降はログイン状態が残っていればブックマークから開ける想定

### 手順
1. このフォルダを **private** GitHub リポジトリにプッシュ
   - `data/positions.csv` には株数・取得単価が含まれるため **絶対に public repository には置かない**
2. https://share.streamlit.io にログイン (GitHub連携)
3. 「New app」→ private リポジトリ・ブランチ・`app.py` を指定
4. **Advanced settings** → 「Share publicly」を **OFF** (= private app に設定)
5. 「Manage app」→ Sharing 設定で、閲覧許可するメールアドレス (=Aさんが使うアカウント) を追加
6. デプロイ完了 → アプリ URL をスマホブラウザでブックマーク
7. 初回アクセス時のみ Streamlit Cloud のログインが要求される → 許可済みアカウントでログイン
8. 以降はスマホのログイン状態が残っている限り、ブックマークから直接開ける

### スマホ運用のコツ
- iOS Safari / Android Chrome ともに「ホーム画面に追加」でPWA風に常駐させると便利
- ログインCookieが切れた場合は再度Streamlit Cloudのログイン画面が出ます

## 👀 Watch銘柄を追加する方法

`data\watchlist.csv` を編集します。

```csv
group,code,name,market,currency,is_active,note
日本株Watch,9999,新規Watch銘柄,JP,JPY,1,自由メモ
```

- `group`: 日本株保有 / 日本株Watch / 別枠 / 除外
- `code`: 日本株は4桁コード、米国株はティッカー (例: MSTR)
- `market`: JP / US
- `currency`: JPY / USD
- `is_active`: 1 で表示、0 で非表示

CSV を保存 → アプリの「🔄 手動更新」ボタンを押すと反映されます。

## 💼 保有株数を更新する方法

### Streamlit Community Cloud でもポートフォリオ表示したい場合 (推奨)
`C:\stocks\app\stock_board\data\positions.csv` を編集します。Cloudにデプロイすると、このファイルが優先されます。

**列構成 (`data\positions.csv`)**:
```csv
code,name,shares,avg_price,currency,note
8020,兼松,2300,,JPY,任意のメモ
9433,KDDI,200,2652,JPY,平均取得単価あり
```

| 列 | 必須 | 説明 |
|---|---|---|
| `code` | ✅ | 4桁日本株コード or 米国ティッカー |
| `name` | ✅ | 表示名 |
| `shares` | ✅ | 保有株数 (数字・空欄なら0扱い) |
| `avg_price` | 任意 | 平均取得単価 (空欄OK) |
| `currency` | 任意 | JPY / USD |
| `note` | 任意 | 自由メモ |

### `avg_price` の扱い

- **`avg_price` を入力すると** Portfolio タブで **評価損益・評価損益率が自動計算** されます
- **`avg_price` が空欄の銘柄** は、Portfolioで「未入力」と表示され、損益計算はスキップされます (アプリは正常に動きます)
- 評価額 (株数×現在値) は `avg_price` の有無に関係なく計算されます
- `avg_price` は **証券会社画面 (損益サマリー等) から手入力** した平均取得単価です
- 既存の `current_positions_...csv` から取得単価が読める場合は、その値を `data/positions.csv` の `avg_price` に転記してください (既存CSVは読み取りのみで上書きしません)

## 🗂 銘柄を追加・削除する方法 (アプリ画面)

**Settings タブ → 「銘柄管理」セクション** に **フォーム形式** の UI があります。CSV直接編集は折りたたみ「詳細CSV編集 (上級者向け)」に格納されています。

### ➕ 銘柄を追加 (推奨)

1. Settings → 銘柄管理を開く
2. 「銘柄を追加」フォームに以下を入力:
   - **区分**: 保有 / Watch / 除外
   - **市場**: 日本株 / 米国株 (自動で `market` と `currency` が補完される)
   - **銘柄コード**: 4桁(日本株) または ティッカー(米国株)
   - **🔎 銘柄名を取得**: コード入力後にこのボタンを押すと銘柄名を自動補完できます
     - **補完優先順位**:
       1. `watchlist.csv` に同じコードが既存ならその `name`
       2. **`data/jpx_listed_companies.csv`** (日本株のみ・**日本語名**)
       3. yfinance `lookup_symbol_name` (英語名)
       4. 取得不可なら手入力
     - 日本株は JPX マスタにあれば日本語名で補完される
     - JPX マスタにない銘柄は yfinance 英語名にフォールバック
     - 取得できない場合は手入力してください
   - **銘柄名**: 表示名 (手入力 or 自動取得)
   - **メモ**: 任意
   - **is_active**: 表示する
3. **区分=保有** の場合のみ追加で:
   - **保有株数**
   - **平均取得単価** (空欄OK)
4. 「➕ 銘柄を追加」を押す

### 保有 と Watch の違い

| | watchlist.csv | positions.csv | 用途 |
|---|---|---|---|
| **Watch** | ✅ 追加される | ❌ 追加されない | 価格チェックのみ |
| **保有** | ✅ 追加される | ✅ 同じcodeで自動追加 | Portfolio タブで評価額・損益を計算 |
| **除外** | ✅ 追加される (非表示) | ❌ 追加されない | 履歴として残すだけ |

### 🗑 銘柄を削除・非表示

「銘柄を削除・非表示」フォームから対象銘柄と操作を選んで「🚀 実行」を押します。

| 操作 | 動作 |
|---|---|
| **非表示にする** | `is_active=0` に変更 (履歴は残る) |
| **Watchへ移動** | `group=Watch` に変更 + `positions.csv` から削除 |
| **保有へ移動** | `group=保有` に変更 + `positions.csv` になければ追加 (株数0で初期化) |
| **除外へ移動** | `group=除外` に変更 + `positions.csv` から削除 |
| **完全削除** | watchlist と positions の両方から完全に削除 (確認チェック必須) |

### 📋 現在の登録銘柄一覧

フォームの下に **保有 / Watch / 除外** の3グループ別で現在の登録状況が表示されます (編集不可・確認用)。

### 🛠 詳細CSV編集 (上級者向け)

折りたたみの中に `st.data_editor` による直接CSV編集UIが格納されています。通常は使う必要がありません。

### バリデーション (自動適用)
- `code` / `name` が空欄の行は保存対象から除外
- `is_active` は `1`/`0` または `true`/`false` を `1`/`0` に正規化
- `shares` は数値化不能なら `0`
- `avg_price` は空欄OK・数値化不能なら空欄
- `group` が無効値の場合は `保有` に補正
- 除外銘柄 (`6326` / `285A` / `6702`) は `positions.csv` に含めても自動除外
- 重複コードは最後の行を採用 (上書き)

### Streamlit Community Cloud 利用時の注意 ⚠️
- **ローカル起動** なら保存ボタンで CSV が永続更新されます
- **Streamlit Community Cloud では一時保存になる場合があります** (再デプロイで初期状態に戻ることがあります)
- 確実に残したい場合は、**「⬇️ ダウンロード」でCSVを取得 → GitHub の private repository に commit & push** してください
- `data/positions.csv` は **private repository 必須** (株数・取得単価が含まれるため public NG)

### ローカル限定の場合
`C:\stocks\data\current_positions_20260527_after_kddi_are_update.csv` (または同形式の新ファイル) を更新してください。Cloud上ではこのパスは見えないので、Cloudで表示するためには **上の `data\positions.csv` を使ってください**。

### 読み込み優先順位
1. **`data\positions.csv`** ← Cloud対応・最優先
2. **`C:\stocks\data\current_positions_20260527_after_kddi_are_update.csv`** ← ローカル既存 (Cloudでは存在しないのでスキップ)
3. どちらもなければ watchlist のみで起動 (Portfolio タブは空表示)

### セキュリティ注意

- **public リポジトリには絶対に置かない** — 株数・取得単価は個人情報です
- **private repository 必須** — Streamlit Community Cloud は private repo もデプロイ可能
- **より秘匿したい場合**: `data\positions.csv` の `shares`・`avg_price` を空欄にして、価格チェック専用で使えます
- 除外銘柄 (6702 富士通・6326 クボタ・285A キオクシア) は `positions.csv` に書いても本アプリでは自動的に弾かれます

> 富士通 6702 は父保有分のため、CSVに含まれていても本アプリでは自動的に除外されます。

## 🎨 画面構成 (3タブ)

| タブ | 内容 |
|---|---|
| 🏠 Home | **世界の株価風タイルグリッド**。保有銘柄 / Watch銘柄をそれぞれ小さなタイルで一覧。各タイル= 銘柄名 / 現在価格 / 騰落率 (青/赤/グレー)。タイルクリックで下部に **1時間足/日足/週足切替チャート** |
| 💼 Portfolio | 保有銘柄一覧 + **並び替えselectbox (10種)** + 表下に評価額/評価損益/評価損益率の3列メトリクス |
| ⚙️ Settings | **銘柄管理フォーム (追加・削除・移動)** + 詳細CSV編集 (折りたたみ) |

> **Chartsタブは廃止**。チャートは Home タイルをクリックして確認します。
> Separateタブ・Watchタブは廃止のまま (Watch銘柄は Home の「Watch銘柄」セクションに表示)。
> 「別枠」グループも廃止: 1687/1695 は **保有** / MSTR/WDC/STX は **Watch** に統合済。

### グループ構成

| group | 内容 |
|---|---|
| **保有** | 日本株保有銘柄 + 1687 WTアグリETF + 1695 WT小麦ETF |
| **Watch** | 日本株Watch銘柄 + MSTR / WDC / STX (米国株サテライト) |
| **除外** | 6326 クボタ (売却済) / 285A キオクシア / 6702 富士通 (父保有分) — 通常表示しない |

### Home画面の表示仕様 (世界の株価風タイル + Home専用スコープCSS)

**タイル構成**
- 各セクション (保有銘柄 / Watch銘柄) を **HTMLタイルグリッド** で表示 (`<div class="home-tile-grid">`)
- 各タイル = `<a class="home-tile">` (HTMLエスケープ済 + `unsafe_allow_html=True` で1回だけ描画)
- タイル内容: **銘柄名 / 現在価格 / 前日騰落率** (青/赤/グレー)
- PC: `auto-fit, minmax(150px, 1fr)` で画面幅に応じて 4〜6列敷き詰め
- スマホ (361-640px): 3列固定
- 小型スマホ (≤360px): 2列
- 各タイル: min-height 76px・padding 8px 10px・1px ボーダー + hover で青強調
- タイル外枠が縦文字に崩れないよう `white-space: nowrap` + `text-overflow: ellipsis`

**タイルクリック動作 (開閉トグル)**
- タイル = `<a href="?select={code}">` で、クリックすると URL query parameter `select` がセットされる
- `st.query_params.get("select")` を Python 側で検知 → **PCでは右カラム / スマホではタイル一覧の下** に該当銘柄のローソク足チャートを展開 (Home最下部固定ではない)
- チャート: 1時間足 / 日足 / 週足 切替 (初期=1時間足) + Yahoo / TradingView 外部リンク
- **同じタイルを再クリックで閉じる** (`?select=`)・別銘柄クリックで切替・「✕ 閉じる」リンクでも閉じる
- 開いているタイルは `.home-tile.selected` で青枠 + 薄い青背景 + 銘柄名太字
- チャート取得はクリックされたときだけ (キャッシュ180秒)・履歴は常に yfinance

**CSSスコープ (PC崩壊防止)**
- 当てるCSSは `.home-tile-grid` / `.home-tile` / `.home-tile-name` / `.home-tile-price` / `.home-tile-pct` / `.home-section-title` の **Home専用クラスのみ**
- グローバルな `div[data-testid="stHorizontalBlock"]` / `.stButton > button` / `.stApp .block-container` には **CSSを一切当てない**
- これにより Portfolio タブ・Settings タブのレイアウトは **Streamlit標準のまま** → 過去のPC崩壊事故を防ぐ
- ヘッダーは `st.markdown("#### 📈 Aさん株価ボード")` (h4) で少しだけコンパクト・手動更新ボタン/自動更新selectboxは標準サイズ

**取得失敗の扱い**
- 1687 など低流動性ETFの取得失敗は **個別タイル内に小さく「取得失敗」**と表示するだけ (画面上部に大きな黄色警告は出さない)
- `price_provider.py` の6段fallback (history → 5d → fast_info → info → manual → fail) で多くの場合は `data/manual_prices.csv` で救済される

### 価格データの鮮度表示 (ヘッダー直下に1か所だけ)

yfinanceは遅延/準リアルタイムで、証券会社画面と数円〜数十円ずれることがあるため、価格が **参考値であること** と **最終取得時刻** を明示します。

表示位置:
- ヘッダー (タイトル / 手動更新 / 自動更新) の **直下に1行 caption** だけ
- Home / Portfolio / Settings いずれのタブを開いていても **同じ1行が見える** (`st.caption` を `st.tabs` の手前で1回だけ呼ぶため)

表示文言:
```
📡 yfinance参考価格 ｜ 最終取得 HH:MM ｜ 証券会社画面と差異あり (最終判断は証券会社の正式画面で)
```

仕様:
- `fetched_at = datetime.now(JST)` を `fetch_all` 完了直後に取得し、ヘッダー直下 caption に `HH:MM` で表示
- **時刻は必ず日本時間 (Asia/Tokyo) で表示**:
  - Streamlit Community Cloud は UTC 環境のため、そのまま `datetime.now()` だとUTCで表示されてしまう (例: JST 10:40 → UTC 01:40 と9時間ズレ)
  - `from zoneinfo import ZoneInfo` で `JST = ZoneInfo("Asia/Tokyo")` を用意し、`datetime.now(JST)` で確実にJST化
  - tzdata がOSに無い環境向けに `dt.timezone(timedelta(hours=9))` fallback も実装
  - `requirements.txt` に `tzdata>=2024.1` を追加し、Streamlit Cloud (Linux) で `ZoneInfo` が確実に動くようにする
- **銘柄タイル内には source / data_time / fetched_at を表示しない** (タイルが大きくなるため)
- **Portfolio表内にも価格取得時刻列を追加しない** (列構成・並び替えを壊さないため)
- `price_provider.py` の `PriceData.source` 属性は内部追跡のみ・画面には出さない
- 最終判断は証券会社の正式画面で行う旨を caption に含める

### Homeのレイアウト (未選択=全幅タイル / 選択時のみ2カラム)
- **未選択時**: Home全幅でタイルを敷き詰める (「世界の株価」風)。右カラムや説明文の空白は出さない
- **銘柄選択時 (PC)**: `st.columns([0.58, 0.42])` で **左55-60%にタイル / 右40-45%にチャート** の2カラムに切替
  - 銘柄クリック後にページ上部へ戻っても、右カラム上部にチャートが見える (スクロールせず価格一覧とチャートを同時確認)
  - 同じ銘柄を再クリックで閉じると、再び全幅タイル表示に戻る
- **銘柄選択時 (スマホ)**: 2カラムが縦積みになり、**タイル一覧の下にチャート**が表示される (見切れない)

### Homeの並び替え (Portfolioとは別物)
- Home上部に小さめの「並び替え」selectbox: `登録順 / 騰落率 高い順 / 騰落率 低い順 / 価格 高い順 / 価格 低い順 / 銘柄名順` (初期=登録順)
- 保有銘柄・Watch銘柄は **別グループのまま、それぞれの中で並び替え**
- 騰落率=change_pct、価格=current_price、銘柄名=name で並べ替え。**取得失敗銘柄は常に最後**
- Portfolio タブの並び替えとは完全に独立 (Homeタイルのみに適用)

### ヘッダーの余白
- タイトルは h4 (`#### 📈 Aさん株価ボード`)
- `.stApp .block-container` の **padding-top のみ** 控えめに調整 (PC 2.2rem / スマホ 1.0rem)・left/right/bottom や display は触らないため Portfolio/Settings のレイアウトは崩れない
- 手動更新ボタン・自動更新selectbox・価格データ鮮度1行は維持

### Homeチャートの開閉 (タイルクリックでトグル)
- Home の銘柄タイルを**クリックするとチャートが開く**・**同じ銘柄を再クリックで閉じる**・別銘柄をクリックでその銘柄に切替
- 開いているタイルは `.home-tile.selected` で青枠 + 薄い青背景 + 銘柄名太字
- 「✕ 閉じる」リンクでも閉じられる (同じタイル再クリックと同等)
- クリック検知は HTMLタイルの `<a href="?select={code}">` (query parameter)・`st.session_state["open_chart_code"]` にも状態保持
- **現在値は kabuステーション優先 / yfinance fallback**、**チャート履歴は常に yfinance** (kabuはsnapshotのみで履歴を返さないため)

### チャート形式 (原則すべてローソク足・OHLC欠損時のみ折れ線fallback)
- **原則すべてローソク足** (`plotly.graph_objects.Candlestick`)・yfinance履歴の Open/High/Low/Close を使用 (折れ線/ローソクの切替UIはなし)
- 上昇 (close>open) = 青 `#2563eb` / 下降 = 赤 `#dc2626` (アプリ配色に統一)
- Range slider は非表示 (`xaxis_rangeslider_visible=False`)・背景白・grid線は薄め (`#eef1f5`)・価格軸は右側
- 高さ 460px (PC右カラム/スマホ共通)・margin は小さすぎない (l/r/t=12, b=28)
- 出来高は初期版では非表示
- **OHLCのいずれかが欠ける場合のみ** 終値 (Close) の折れ線にfallback し、「OHLCデータなしのため折れ線表示」と小さく注記

### チャートの足種 (ローソク足が潰れない期間設定)
ローソク足が細かく潰れないよう、表示期間を短めに設定:

| 足種 | interval | period | ローソク本数(目安) |
|---|---|---|---|
| **1時間足** (初期表示) | `60m` | `10d` | 約66本 |
| **日足** | `1d` | `3mo` | 約59本 |
| **週足** | `1wk` | `2y` | 約105本 |

- 取得不可時 (1時間足など): 「1時間足データ取得不可。日足に切り替えてください」と表示・アプリは落とさない
- タイトルに「銘柄名 コード / 足種 / 取得期間」を表示 (例: `KDDI 9433 / 1時間足 / 10日`, `/ 日足 / 3ヶ月`, `/ 週足 / 2年`)

### Homeの並び替えは手動更新後も維持
- Home並び替え selectbox は固定 `key="home_sort_mode"` のため `st.session_state` に保持される
- 「🔄 手動更新」は価格キャッシュ (`fetch_one` / `fetch_history_cached`) のみクリアし、**session_state や URLクエリ (`?select=`) は触らない**
- → 手動更新後も並び替え (例: 騰落率 高い順) と選択中チャートは維持される

### 騰落率・損益の色 (統一ルール)
- **プラス: 青 `#2563eb`**
- **マイナス: 赤 `#dc2626`**
- **ゼロ / 未入力 / 取得失敗: グレー `#6b7280`**

色付け対象:
- Home expander 見出しの前日騰落率
- Home チャート周辺の前日比・騰落率
- Portfolio タブの 評価損益 / 評価損益率 / 前日比 / 前日比率
- Charts タブの騰落率

## 🇯🇵 日本語銘柄名マスタ (`data/jpx_listed_companies.csv`)

日本株を **日本語名** で表示・補完するためのローカルマスタです。

### 列構成
```csv
code,name,market,sector,note
9433,KDDI,JP,情報・通信業,
```

| 列 | 説明 |
|---|---|
| `code` | 4桁コード または 英数字コード (例: 285A) — **文字列扱い**で先頭ゼロも保持 |
| `name` | 日本語銘柄名 |
| `market` | JP (将来US対応も) |
| `sector` | 業種 (任意) |
| `note` | メモ (任意) |

### 補完の優先順位 (再掲)
1. `watchlist.csv` に既存コードがあれば、そのname
2. `data/jpx_listed_companies.csv` (日本株のみ・**日本語名**)
3. yfinance `lookup_symbol_name` (英語名)
4. なければ手入力

### マスタの更新方法
- **手動**: 必要な銘柄を追記するだけでOK (UTF-8 BOM 推奨)
- **JPX公式CSV**: https://www.jpx.co.jp/markets/statistics-equities/misc/01.html の「東証上場銘柄一覧」から取得して `code,name` 列を作成
- Yahooファイナンス等のスクレイピングは **採用していません** (HTML仕様変更で壊れやすいため初期版では不採用)

### 初期同梱マスタ
保有・Watch・除外の全日本株コードを日本語名で同梱しています (1687/1695/2780/4633/5032/5857/6326/6432/6702/6814/6995/7864/7994/8020/8059/8253/8316/8593/8830/9433/9960/1980/3626/4206/4722/285A の26銘柄)。

## 📡 yfinance版の限界

1. **完全リアルタイムではない** (遅延/準リアルタイム)
2. **日本株は数分単位で遅れる** 可能性
3. **板情報・約定情報・証券口座情報は取れない**
4. **ファンダメンタル情報は使わない** (価格・出来高のみ・本アプリ方針)
5. **価格誤差はあり得る** (最終判断は証券会社の正式画面で)
6. **1687 WTアグリETF など低流動性銘柄は yfinance の `history` がしばしば空になる** ため、`price_provider.py` で6段fallbackを実装:
   - `history(period, interval)` → `history(period="5d", interval="1d")` → `fast_info` → `info` → **`data/manual_prices.csv` (手動値・最終手段)** → 取得失敗
   - `data/manual_prices.csv` の列: `code,name,price,previous_close,currency,updated_at,note`
   - 手動値が使われた場合 `PriceData.source = "manual"` がセットされる (画面上は通常価格と同じ見た目)
   - 1687 等で yfinance が安定して取れる日も多いため、manual は **fallback時のみ**使われる

## 🛠️ 将来の改善計画

1. **Rakuten RSS Provider 追加** — Excel経由 or RSS API でリアルタイム化
2. **Tachibana API Provider 追加** — 立花証券のe-shopAPI
3. **PWA化** — スマホホーム画面に追加可能に
4. **通知機能追加** — 指定価格到達でPush通知 (FCM等)
5. **為替換算追加** — 別枠USD銘柄のJPY換算表示

## 📡 価格データ Provider (yfinance / kabu_station / auto)

ローカルPCで kabuステーション API が使える場合、yfinance より精度の高い価格を取得できます。本アプリは3つの Provider を切替可能:

| Provider | 取得経路 | 環境 | 用途 |
|---|---|---|---|
| `yfinance` | yfinance API (6段fallback: history → 5d → fast_info → info → manual → fail) | Cloud / ローカル | 既定の遅延/準リアルタイム |
| `kabu_station` | kabuステーション `/token` + `/board` (snapshot) ・米国株は yfinance | **ローカルPCのみ** | 証券会社画面に近い価格・JP株のみ |
| `auto` (推奨) | kabu_station → yfinance fallback | 両対応 | Cloud では yfinance のみ・ローカルでは kabu 優先 |

### Provider 切替方法
1. アプリ起動 → **Settings タブ** → 「📡 価格データ取得元 (Provider)」 selectbox
2. `auto` / `kabu_station` / `yfinance` から選択 → キャッシュクリア + 再取得
3. ヘッダー直下のキャプションが選択 provider に応じて変化:
   - kabu のみ: `📡 kabuステーション価格 ｜ 最終取得 HH:MM ｜ ローカルPC取得 (注文APIは呼びません)`
   - yfinance のみ: `📡 yfinance参考価格 ｜ 最終取得 HH:MM ｜ 証券会社画面と差異あり`
   - 混在 (auto時の典型): `📡 価格データ: kabu優先 / yfinance fallback ｜ 最終取得 HH:MM ｜ kabu 13 銘柄 / yfinance 3 銘柄`

### `kabu_station` / `auto` の前提
- auカブコム証券口座 + kabuステーション (Windows) インストール
- kabuステーション本体を **起動 + ログイン済**
- 「ツール」→「API設定」で **API利用ON**
- `kabu_config.json` 作成 (`kabu_config.example.json` をコピー → `api_password` 設定)
- `kabu_config.json` は `.gitignore` 済 → **GitHub には絶対に上がらない**

### Cloud/スマホ環境での挙動
- Streamlit Community Cloud は Linux 環境で kabuステーションへ直接アクセス不可
- `auto` を選択していても `kabu_config.json` が無いため `kabu.available = False` となり、**透過的に yfinance のみ** が使われる
- 将来は `data/kabu_prices_latest.csv` をローカルでcommit&pushしてCloud側で読む方式を検討 (今回は未実装)

### kabu価格のローカル保存 (`data/kabu_prices_latest.csv`)
- `auto` または `kabu_station` 選択時、**kabu_station から取得できた銘柄だけ** をCSV保存
- 列: `code,name,price,previous_close,change,change_pct,volume,price_time,source,updated_at`
- `.gitignore` 済 (ローカル中間ファイル・GitHubには上げない)
- 用途: 将来 Cloud/スマホへ価格連携するための中間ファイル

### Provider側の安全装置
- 使うkabuエンドポイントは `/token` と `/board` のみ (whitelist `_KABU_SAFE_ENDPOINTS` で物理ガード)
- `base_url` は `http://localhost` / `http://127.0.0.1` のみ許可 (`_load_kabu_config` で弾く)
- API パスワードは print / markdown / log に絶対出さない
- Token はメモリのみ (`self._token`) ・ファイル保存しない
- 米国株 (market != "JP") は kabu 側で即 `source="kabu_station_skip"` → caller (AutoProvider) で yfinance fallback
- 1銘柄失敗してもアプリ全体を落とさない (各銘柄独立 try/except + retry 3回)
- チャート用 history (`interval != "1d"` または `period != "6mo"`) は **常に yfinance** (kabu は snapshot のみで history を返さないため)
- **注文API (`/sendorder` `/cancelorder` `/orders` `/positions` `/wallet`) は関数として存在しない**

## 🧪 kabuステーションAPI 接続テスト (standalone・実験中)

yfinance価格と証券会社画面で乖離があるため、auカブコム証券「kabuステーションAPI」から **価格取得のみ** を試すための独立スクリプトを同梱しています。
**既存ダッシュボード (`app.py` / `price_provider.py`) にはまだ組み込んでいません**。接続性が確認できてから次フェーズで統合検討します。

### 絶対方針 (PRESERVE)

- **自動発注機能は追加しない** (`/sendorder` / `/cancelorder` / `/orders` 等の注文系APIは絶対に呼ばない)
- **証券会社ログイン情報を保存しない**
- **APIパスワードをコードに直書きしない**
- `kabu_config.json` は `.gitignore` 済 (GitHub には絶対に上げない)
- `kabu_config.example.json` (プレースホルダ入り雛形) だけコミットOK

### 前提

- auカブコム証券口座 + kabuステーション (Windowsアプリ) をインストール済
- kabuステーション本体を **起動 → ログイン済** であること
- 「ツール」→「API設定」で **API利用をON** にしておくこと
- ポート `18080` で待ち受けていること (デフォルト)

### 実行手順

1. 雛形をコピーして実体ファイルを作る:
   ```powershell
   copy kabu_config.example.json kabu_config.json
   ```
2. `kabu_config.json` を開き、`api_password` に実パスワードを入力 (この実体ファイルは `.gitignore` 済)
   - パスワードをファイルに置きたくない場合は、環境変数で渡してもOK:
     ```powershell
     $env:KABU_API_PASSWORD = "your-password"
     ```
3. 実行:
   ```powershell
   cd C:\stocks\app\stock_board
   py kabu_test.py
   ```

### 成功時

- 標準出力に Token取得成功 (一部マスク) + 各銘柄の `Symbol / SymbolName / CurrentPrice / CurrentPriceTime / PreviousClose / TradingVolume / ExchangeName` が表示される
- `data/kabu_prices_test.csv` が生成される (列: `code,name,price,previous_close,change,change_pct,volume,price_time,source,updated_at` ・ source=`kabu_station`)

### よくあるエラー

| 症状 | 対処 |
|---|---|
| `kabuステーションAPIに接続できません` | kabuステーション本体を起動 → ログイン → API設定ON |
| `APIパスワードが違う可能性 (HTTP 401)` | パスワード再入力 / 大文字小文字確認 |
| `銘柄が見つかりません (HTTP 404)` | 銘柄コードを4桁数字で・`exchange` 1=東証 確認 |

### タイムアウト / リトライ仕様

低流動性銘柄や瞬間的なネットワーク遅延で `socket.timeout` が出ても、1銘柄のせいで全体取得を止めないように **retry付き** に実装しています。

| 設定キー (kabu_config.json) | デフォルト | 用途 |
|---|---|---|
| `request_timeout_sec` | 10 | 1リクエストあたりの待ち時間 (旧 5秒 → 10秒に延長) |
| `retry_count` | 3 | 同じ銘柄を最大何回まで試すか |
| `retry_sleep_sec` | 0.5 | リトライ間の待機秒 |

**再試行する条件**:
- `socket.timeout` / `TimeoutError` / "timed out" を含む `URLError`
- `ConnectionResetError`
- HTTP `429` (rate limit) / `5xx` (一時的サーバエラー)

**再試行しない条件** (即失敗としてfailedに記録):
- HTTP `404` (銘柄が見つからない)
- HTTP `401` / `403` (認証エラー — APIパスワード違い等)
- その他 `4xx`

**1銘柄失敗時の挙動**: その銘柄を `data/kabu_prices_failed.csv` (列: `code,error,updated_at`) に記録し、**次の銘柄の取得を続行** します。最終的に1銘柄でも成功していれば `data/kabu_prices_test.csv` を生成。

### スクリプトの安全装置

- 呼び出すURLは `/token` または `/board` を含むパスに限定 (whitelist方式)
- `base_url` は `http://localhost` / `http://127.0.0.1` のみ許可 (外部送信防止)
- パスワードは `print()` しない (Token表示も先頭6字+末尾3字のみ・他はマスク)
- 注文系・残高照会系APIは関数自体が存在しない
- 1銘柄の例外でスクリプト全体を止めない (各銘柄独立して try/except + retry)

## ▶️ 次に楽天RSS版へ移行する場合

`price_provider.py` に `RakutenRSSProvider(PriceProvider)` クラスを追加：

```python
class RakutenRSSProvider(PriceProvider):
    name = "rakuten_rss"
    def yf_symbol(self, code, market): ...
    def fetch(self, code, market, period="6mo") -> PriceData:
        # 楽天RSS / マーケットスピード経由のExcel DDE or API呼び出し
        ...
```

`get_provider("rakuten_rss")` を返すよう `get_provider()` を拡張し、`app.py` の `provider_name` 引数を切り替えるだけで移行可能です。

## ⚠️ 免責

本アプリは Aさんの個人的なポートフォリオ確認用です。投資判断・売買執行は必ず証券会社の正式画面で行ってください。表示価格と実取引価格に乖離がある可能性があります。
