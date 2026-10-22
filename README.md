# rnote_static

現在のバージョンは **0.9.7.5.1** です。旧rNoteの最終版0.9.7.5に末尾番号を追加し、以後は `0.9.7.5.x` として更新します。`python rnote_static_build.py --version` で確認できます。skin変数 `$rnote_version` もこのバージョンを返します。既存skin内の `rNote <%=$rnote_version%>` は、読込時に `rNote Static <%=$rnote_version%>` として扱い、生成HTMLのクレジットを **Powered by rNote Static 0.9.7.5.1** にします。既存skinファイルや記事本文は書き換えません。

旧rNote 0.9.7.5 の記事・設定・skinを入力として、配信用の静的サイトを生成するPythonプログラムです。互換動作の基準は `rnote.php` 本体です。skinの見た目から意図を推測した自動修正は行いません。

Python 3.9以降の標準ライブラリだけで動作します。pip、仮想環境、追加パッケージ、PHP、データベース、Node.jsは不要です。配信サーバーには生成物だけを配置します。

このリポジトリには新規作成したPythonソース、合成データによるPythonテスト、このREADMEだけを収録します。旧rNoteのPHP、設定、skin、XML、画像、教材、生成済みサイトは同梱していません。既存サイトを別途用意してください。

## 実行

`rnote_static_build.py` と `rnote_static/` を、既存の `rnote.php`、`rnote_config.php`、`entries/`、`style/` のあるディレクトリに配置して実行します。

```console
python rnote_static_build.py
```

環境によっては `python3` を使ってください。Windowsでも通常のPythonインストールだけで実行できます。初期状態のWindowsの `python` アプリ実行エイリアスだけでは、Python本体がまだ入っていない場合があります。

プログラムと入力を別の場所に置くこともできます。

```console
python rnote_static_build.py --source "C:\path\to\legacy-site"
```

出力先は既定で入力ルートの `public/` です。既存の入力ファイルは変更しません。サイトのPHPを実行せず、ビルド中のネットワークアクセスも行いません。

### 検査とオプション

```console
python rnote_static_build.py --source "C:\path\to\legacy-site" --check
python rnote_static_build.py --source "C:\path\to\legacy-site" --output "C:\path\to\build\public" --report "C:\path\to\build\report.json"
python rnote_static_build.py --source "C:\path\to\legacy-site" --site-url "https://example.org/blog/"
```

| オプション | 内容 |
|---|---|
| `--source` | 入力サイトのルート。既定はこのプログラムの配置場所 |
| `--output` | 出力先。既定は `SOURCE/public` |
| `--site-url` | `SITE_URL` の上書き。サイトを別ドメインやサブディレクトリへ移すときに使用 |
| `--check` | 全ページの描画・入力検証だけを行い、配信用ファイルを作らない |
| `--report` | JSON診断レポート。入力を保護するため、原則として入力ツリーの外に指定 |
| `--exclude-category` | 指定カテゴリと子孫を除いた**部分ビルド**。複数回指定可能 |
| `--asset-dir` | コピーするアセットディレクトリを指定。複数回指定可能。指定時は既定一覧を置き換える |
| `--max-pages` | ページ状態数の上限。既定50000 |
| `--version` | ビルダーのバージョンを表示して終了 |

正常時の終了コードは0、検証・ビルド失敗時は1です。警告だけでは失敗しません。標準エラーには先頭30件の警告を表示し、全診断は `--report` に保存できます。

## 出力と再ビルド

記事、カテゴリ、ページ分割、RSSをすべて静的ファイルにします。

| 旧入力／閲覧状態 | 出力例 |
|---|---|
| `entries/work/example.xml` | `public/work/example.htm` |
| `/work/` | `public/work/index.html` |
| `/`、`/index.html` | `public/index.html` |
| `/index.htm` | トップページと同内容の `public/index.htm` |
| `/work/?p=1` 相当 | `public/work/_page/2/index.html` |
| `/?d=2024-01` 相当 | `public/_date/2024-01/index.html` |
| 日付＋ページ | `public/_date/2024-01/_page/2/index.html` |
| RSS | `public/rss.rdf` |

ページ番号は表示パスで1始まり、旧クエリの `p` は0始まりです。新しいナビゲーションは実体のある静的URLへ向けます。記事の旧 `.htm` とカテゴリの末尾 `/` は維持します。URI中の日本語や空白はリンク生成時にエンコードします。

静的サーバーは通常、クエリ文字列によって別ファイルを選択しません。既存の `?p=`、`?d=`、`rnote.php?u=` を外部から引き続き使う場合は、配信先に転送ルールが必要です。旧PHPのrewrite設定は配布物へコピーしません。`s`、`c` による任意skin・コンテンツ型の切り替えは対応表がない限りエラーになります。

サイト設置位置は `SITE_URL` から取得します。絶対URLはその値を基準にし、PHPの `HTTP_HOST` や `PHP_SELF` は必要としません。`SITE_URL` にルート相対で直書きされた記事リンクを自動移設する機能はありません。移設時はリンク診断も確認してください。

生成ファイルは一時ディレクトリへ書き、検証後に出力ディレクトリを置き換えます。エラーがあれば既存出力を更新しません。出力には `.rnote-static-output` という管理マーカーを付けます。このマーカーのない既存ディレクトリは上書きしません。手作業のファイルを出力先に混在させないでください。`public/` は削除して再生成できます。

## 互換仕様

### 設定

`rnote_config.php` をテキストとして読み、静的表示に必要な部分だけを解析します。

- `define(NAME, value)` および引用符付き定数名
- 文字列・整数・真偽値、既定義定数、`.` による連結
- `$category_name['key'] = 'value'`
- `$nodisp_at_toplv[] = 'prefix'`
- サイト情報、件数、前後移動範囲、日付書式、タグ名、拡張子、skin名、RSS名・要約長

PHPのコメントを区別し、管理用の値は公開物へ持ち込みません。設定中のリクエスト処理や関数呼び出しは実行しません。対象サイトの設定順序に合わせ、最初の `if (...)` 以降は読込対象外です。一般的なPHPパーサーではなく、このサイトに必要な設定文法の読取器です。文字列補間や動的計算はサポートしません。

`USE_MOD_REWRITE` の値にかかわらず、出力には実体のある静的パスを使います。オンラインCMS用設定は実装対象外です。

### 記事と日付

ドットで始まらないディレクトリを再帰走査し、指定拡張子のファイルを収集します。バックアップらしい名前も、旧コードが収集する名前なら勝手に除外しません。シンボリックリンクには追従しません。

旧 `get_XMLTag()` と同様のテキスト抽出を行うため、本文が厳密なXMLでなくても読み込めます。本文のHTMLをXMLとして再シリアライズしません。タイトルはタグと制御改行を除去し、本文は原則そのまま展開します。要約はDescription、なければTextから作り、旧処理に合わせてタグ除去、空白整理、一部実体参照の変換、長さ制限、HTMLエスケープを行います。

日付は旧 `w3cdtf_to_time()` の成分抽出・正規化に合わせます。日時なしのDateにも対応し、Dateがない場合は旧実装と同様にファイルのctimeを参照して警告します。ctimeと同日時の記事の走査順は環境依存なので、異なるOS・ファイルコピー間の完全一致は保証しません。

旧サイトのサーバー時刻を日本時間（UTC+09:00）として扱います。`%a` は日本語曜日、`%z` は `+09:00` 形式です。OSへの `ja_JP` ロケール追加は不要です。元コードの日時オフセットの引き算も保持しているため、タイムゾーン付きDateは一般的なISO日時パーサーと結果が異なる場合があります。

### skin構文

既存skinを直接読み込み、次を処理します。

- `<%=$変数 オプション="値" %>`、引用符付きオプション、エスケープと `\n`
- `$include`、`$site_items`、`$site_link`、サイト情報とRSS関連変数
- `$Url`、`$Title`、`$Date`、`$Category`、`$Description`、`$Text` と任意記事タグ
- `autolink` と `targetblank`
- 入れ子の `<if ...>`、否定条件、旧 `IsCategory`・`ifdef`・`ifndef`
- `bHome`、`bSingle`、`bCellphone=false`、カテゴリ条件、タグ存在条件
- `<%goto "label"%>` と `<%label "label"%>`
- rNote用の `<!--- ... --->` コメント

include、マクロ、記事展開、ナビゲーション・サイト変数、未解決タグ除去、URL補正という旧コードの評価順を基本とします。includeはサイトルート基準の明示パスです。再帰ループは診断して停止します。

**skinの誤記を修正する処理はありません。** たとえば `<%=$site_items% sort="ff" num="1">` は正しい閉じ方ではありませんが、旧 `SkinTagChk()` のように後続の `%>` まで取り込みます。オプションにHTMLが混ざった場合の数値は、旧PHPと同じ先頭数値変換で扱います。誤記を警告しつつ、意図を推測して描画内容を変更しません。未解決の置換タグは旧最終処理と同様に除去して警告します。

### skinの継承

`html_body.skin` と `html_item.skin` は**別々に**、最も近い祖先から継承します。bodyは閲覧カテゴリ、itemは表示する各記事の所属カテゴリから選びます。`site_items skin="..."` はitem skinの明示上書きです。includeで指定したファイルはこの継承には含みません。

### 記事選択・ナビゲーション

カテゴリ一覧には子孫カテゴリの記事も含めます。既定は日付降順（`dr`）、`df` は日付昇順、`ff`・`fr` はファイル名の昇順・降順です。件数、`start`・`end`、固定記事指定、別カテゴリの一覧を扱います。コメント時刻順の `cr`・`cf` は対応しません。

`FORTHBACKMODE=true` での単一記事の前後移動範囲は、直近カテゴリではなく最上位カテゴリです。`work/class/...` の記事なら `work/` 全体になります。パンくず、通常・compact・category・prev・next・linkモードを処理します。

`nodisp_at_toplv` は旧コードの正規表現による先頭一致で、ルート一覧やRSSに作用します。非表示設定はアクセス制御ではありません。個別記事とカテゴリページは生成されます。`navitools` の隠しカテゴリとは別の設定です。

旧 `SelectFileList()` が明示dateではなく閲覧中のdateを実際の絞り込みに使う挙動も保持しています。固定記事だけのbodyでは、閲覧中の記事や日付が変わってもbodyに指定された記事が表示されます。これもskinの意図から補正しません。

### プラグインとRSS

有効な `navitools.category` と旧 `$navi_category` を再現します。カテゴリ順序・隠しカテゴリは `plugins/navitools.php` 内のリテラル設定から読みます。PHPクラスは実行しません。カレンダー、アーカイブ、携帯用プラグイン、その他任意PHPプラグインの有効呼出しは未対応です。rNote専用コメント内の無効な呼出しは処理されません。

RSSは `rss_body.skin` とそこから指定されたitem/sequence skinを使って生成します。対象サイトでは15件・RSS 1.0です。旧コードはrss.rdfの既存有無で再生成を判断しますが、本ビルダーでは完全再生成のため、元のrss.rdfがなくても生成します。

### 静的アセット

既定では `style/`、`image/`、`data/`、`WebApps/` をバイト列のままコピーします。`entries/` 内の非記事アセットも元の `entries/...` パスへコピーします。CSSの `url(...)` を保つためディレクトリ構成を維持し、圧縮・結合・改変はしません。

PHP・CGIなどのサーバープログラム、skin、ログ、キャッシュ、INI、バックアップ、隠しファイルは配布対象外です。アセットディレクトリが別名なら `--asset-dir` で指定してください。任意のルートファイルを無差別にコピーする処理はありません。サーバープログラムが必要なWebアプリを静的化する機能もありません。

旧 `ChangeFullUrl()` と同様、a/img/linkタグのダブルクォート付き相対URLをサイト設置位置基準に補正します。元コードが対象としないscriptタグなどへ処理を広げません。記事内の `$site_link/` と `$site_link_full/`、`$$` によるエスケープにも対応します。

内部リンクの参照先が生成・コピー対象にあるかを検査し、欠落は警告として報告します。元から壊れているリンクは修復しません。外部サイトの到達性、JavaScriptで動的生成するURL、CSSからの参照、ページ内アンカーの存在は検査しません。

## PHP禁止と削除機能

PHP本体、PHP短縮タグ、PHPの出力を実行する経路はありません。`eval`、PHPインタープリター、外部評価サービスも使いません。公開される内容からPHP構文を検出すると、ファイル名と行番号付きで停止します。XML宣言の `<?xml ... ?>` は許可します。検出は保守的で、JavaScript内のPHP開始タグ文字列なども停止対象になります。

調査対象の既存サイトには `entries/private/html_head.skin` にPHP短縮タグがありました。この入力をそのまま全件ビルドすると、現仕様では**終了コード1で停止します**。PHPを黙って削除したり、特定コードを代行評価したりはしません。この点は互換性の不具合ではなく、PHP禁止仕様による既知の制約です。

既存入力を変更せずに他カテゴリを確認する場合は、明示的な部分ビルドができます。

```console
python rnote_static_build.py --source "C:\path\to\legacy-site" --exclude-category private/ --output "C:\path\to\build\partial-public"
```

除外は記事選択、カテゴリ索引、RSSにも反映されます。部分ビルドを全件サイトの完成と見なさないでください。全件の静的出力が必要なら、埋め込みPHPの表示をどう扱うかを別途決める必要があります。

オンライン管理、投稿、コメント・TrackBack受信、BBS投稿、Cookie、セッション、参照元収集、動的キャッシュは実装しません。`WriteBack` 展開を無効化し、関連条件はfalseとして扱い、生成HTMLのPOSTフォームは除去します。過去コメントやログの読取表示も初期実装の対象外です。

## テスト

```console
python -m unittest discover -s tests -v
```

標準の `unittest` を使用します。テスト用の記事・skin・設定は一時フォルダに合成して作り、旧サイト素材を必要としません。継承、並べ替え、前後移動、ページ分割、raw HTML、skin誤記、条件とgoto、PHP拒否、出力保護、元データ不変、リンク検査などを確認します。

元サイトとのバイト単位の一致を検証するためにPHPを実行するテストはありません。互換性は旧ソースの読解から導いた規則と、合成フィクスチャ・実データの静的検査で検証します。

0.9.7.5.1の検証では合成テスト20件が成功しました。調査対象の全859記事・168カテゴリの検査では、既知のprivate用ヘッダのPHPだけがエラーになり、出力更新を停止しました。privateカテゴリを明示的に除外した検証では、840記事・154カテゴリから1390ページと1052アセットを生成できました。RSSのXML構文と15件のitem、トップページ別名の一致、CSSのバイト一致、読込元ファイルのハッシュ不変も確認しています。skin誤記や元から存在しないリンクなどの警告は残ります。

## モジュール

| ファイル | 役割 |
|---|---|
| `rnote_static_build.py` | 実行入口 |
| `rnote_static/config.py` | 必要なPHP設定文法の読込 |
| `rnote_static/entries.py` | 記事・カテゴリ索引、入力ハッシュ |
| `rnote_static/common.py` | 旧タグ抽出、日付、数値変換、PHP検出 |
| `rnote_static/skins.py` | skin読込、オプション解析、継承に使う読込、マクロ |
| `rnote_static/selection.py` | 記事選択と閲覧状態 |
| `rnote_static/urls.py` | 静的URL・出力パス、相対URL補正 |
| `rnote_static/render.py` | 記事・ページ・ナビゲーション・RSS |
| `rnote_static/validation.py` | 出力一覧を使う内部リンク検査 |
| `rnote_static/build.py` | 全体制御、アセットコピー、段階的出力 |

## 公開用Gitリポジトリ

既存サイトのルートをGitHubへそのまま追加しないでください。独立したディレクトリに上記Pythonソース、`tests/test_compatibility.py`、このREADMEだけを置いて管理します。設定ファイル、記事、skin、画像、教材、`public/`、検証レポート、`__pycache__/` を含めません。

公開前には次のコマンドで追跡対象を確認できます。

```console
git status --short
git ls-files
git log -1 --oneline
```

GitHubリポジトリの作成、remoteの追加、pushは利用者側で行います。配信用サイトをアップロードする場合も、GitHub公開用プログラムと `public/` は別の成果物として扱ってください。
