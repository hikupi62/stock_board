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
│   └── positions.csv               # 保有株数・取得単価 (Cloud対応・優先読み込み)
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

### Portfolioタブの表示仕様 (スマホ向け4列+縦並びメトリクス)
- **表は4列のみ**: 銘柄名 / 取得単価 / 現在値 / 評価損益 (コード・株数・評価額・前日比は省略)
- **銘柄名**: watchlist の `short_name` を優先・なければ `name` を6文字短縮
- **初期並び順**: 評価損益_num **降順** (プラス大 → マイナス大の順)
- **並び替えselectbox**: 評価損益/評価額/損益率/前日比率/コード/銘柄名の昇降順 (上部に配置)
- **評価損益列の色**: プラス青 / マイナス赤 / ゼロ灰 (`_pct_color_style`)
- **トータル**: 表の下に **3つの st.metric を縦並び** (st.columns 不使用・スマホで数字省略されない)
  - 日本株PF評価額合計
  - 評価損益合計 (delta = 損益率)
  - 評価損益率
- **下部の注意書きは出さない**

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
| 🏠 Home | 銘柄ごとの **expander 形式**。見出しに 銘柄名・コード・価格・🔵/🔴/⚪+騰落率。開くと色付き騰落率 + **1時間足/日足/週足切替チャート** + Yahoo/TradingView リンク |
| 💼 Portfolio | スマホ向け4列 (銘柄名 / 取得単価 / 現在値 / 評価損益)・並び替えselectbox・トータルは縦並びメトリクス |
| ⚙️ Settings | **銘柄管理フォーム (追加・削除・移動)** + 詳細CSV編集 (折りたたみ) |

> **Chartsタブは廃止**。チャートは Home の各銘柄 expander を開いて確認します。
> Separateタブ・Watchタブは廃止のまま (Watch銘柄は Home の「Watch銘柄」セクションに表示)。
> 「別枠」グループも廃止: 1687/1695 は **保有** / MSTR/WDC/STX は **Watch** に統合済。

### グループ構成

| group | 内容 |
|---|---|
| **保有** | 日本株保有銘柄 + 1687 WTアグリETF + 1695 WT小麦ETF |
| **Watch** | 日本株Watch銘柄 + MSTR / WDC / STX (米国株サテライト) |
| **除外** | 6326 クボタ (売却済) / 285A キオクシア / 6702 富士通 (父保有分) — 通常表示しない |

### Home画面の表示仕様 (世界の株価風・密度高めタイル)
- 各セクション (保有銘柄 / Watch銘柄) を **小型カードタイル** で敷き詰め表示
- **1銘柄 = 1ボタン (カード風)** ・タイル自体タップでチャート選択
- **列数は画面幅で自動**:
  - **小型スマホ (≤360px)**: 2列固定
  - **スマホ (361-640px)**: 3列固定
  - **PC (≥641px)**: 140px幅で auto-fit (4-6列)
- **タイル仕様** (高さ 72px・余白 3-4px・3行固定):
  - 1行目: **銘柄名** (`short_name` 優先、なければ `name` を6文字で短縮・1行省略)
  - 2行目: **現在価格** (¥xxx / $xxx)
  - 3行目: **🔵 +x.xx% / 🔴 -x.xx% / ⚪ 0.00%**
  - コードは表示しない (画面密度優先)
  - 取得失敗時は「取得失敗」と表示
- **`short_name` 列** (`watchlist.csv`):
  - Home タイルでの短縮表示用 (任意)
  - 既存銘柄に「コメ兵HD / クレセゾン / WTアグリ」等を同梱
  - 空欄でも自動短縮 (6文字)
  - Settings の銘柄追加フォーム・詳細CSV編集の両方で編集可能
- **Home上部のヘッダー**:
  - タイトル小型化 (`##### 📈 Aさん株価ボード (yfinance・遅延)`)
  - 自動更新 selectbox のラベル非表示
  - 余計な説明文は省略
- **選択中タイル**: Streamlit primary ボタンで青枠強調
- **選択中チャート (Home下部・タイル選択時のみ表示)**:
  - 初期未選択時は何も表示せず、株価一覧優先
  - 選択後: 1時間足 (初期) / 日足 / 週足 切替 + Yahoo/TradingView リンク
- 取得失敗銘柄: 画面上部大警告なし・小キャプション + タイル内「取得失敗」表示

### チャートの足種
- **1時間足**: yfinance `interval=60m, period=60d` (**初期表示**) — 日本株では取得不可・欠損のケースあり (取得不可時は警告表示・日足/週足への切替を推奨)
- **日足**: yfinance `interval=1d, period=1y`
- **週足**: yfinance `interval=1wk, period=5y`
- タイトルに「銘柄名 コード / 足種 / 取得期間」を表示

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

## 📡 yfinance版の限界 と Fallback (`data/manual_prices.csv`)

1. **完全リアルタイムではない** (遅延/準リアルタイム)
2. **日本株は数分単位で遅れる** 可能性
3. **板情報・約定情報・証券口座情報は取れない**
4. **ファンダメンタル情報は使わない** (価格・出来高のみ・本アプリ方針)
5. **価格誤差はあり得る** (最終判断は証券会社の正式画面で)

### ETF / 低流動性銘柄の取得失敗対策 (Fallback)

`1687 WTアグリETF` のようなETF・低流動性銘柄は **Streamlit Cloud 環境で yfinance 取得に失敗** することがあります。

`price_provider.py` の `fetch_history()` は以下の順でフォールバックします：

| 段 | 取得元 | source |
|---:|---|---|
| 1 | `yfinance.history(period, interval)` | `yfinance` |
| 2 | `yfinance.history(period="5d", interval="1d")` | `yfinance_5d` |
| 3 | `ticker.fast_info` の `last_price` / `previous_close` | `fast_info` |
| 4 | `ticker.info` の `regularMarketPrice` / `previousClose` | `info` |
| 5 | **`data/manual_prices.csv` の手動値** | `manual` |
| 6 | すべて失敗 → 「取得失敗」表示 | (error) |

### `data/manual_prices.csv` の列構成

```csv
code,name,price,previous_close,currency,updated_at,note
1687,WTアグリETF,1018,1019.5,JPY,manual,ETF fallback (yfinance取得不安定)
```

- `code`: 銘柄コード (4桁 / 英数字)
- `name`: 銘柄名 (参考)
- `price`: 手動現在値
- `previous_close`: 手動前日終値 (空欄なら前日比は `-`)
- `currency`: JPY / USD
- `updated_at`: 更新メモ (`manual` / 日付など)
- `note`: 任意メモ

### 手動値の取り扱い

- `manual` source の銘柄はタイル内に **「※ 手動値」** と小さく表示されます
- **古くなる可能性があるため、最終確認は証券会社画面で必ず行ってください**
- 必要に応じて `manual_prices.csv` を編集して値を更新します

## 🛠️ 将来の改善計画

1. **Rakuten RSS Provider 追加** — Excel経由 or RSS API でリアルタイム化
2. **Tachibana API Provider 追加** — 立花証券のe-shopAPI
3. **PWA化** — スマホホーム画面に追加可能に
4. **通知機能追加** — 指定価格到達でPush通知 (FCM等)
5. **為替換算追加** — 別枠USD銘柄のJPY換算表示

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
