# OKL v1 — OperantKitLog v1

本ドキュメントは `session-recorder` が読み書きする wire format の
**正典仕様** である。**言語非依存**: 任意の実装（Python / Rust /
TypeScript / ...）はこのスキーマにバイト単位で従うこと。

## なぜ新フォーマットか

旧 wire format (JSONL) は最初の実装からの引き継ぎで、他形式と比較されて
採用されたものではなかった。OKL v1 は 1 ファイルで以下 3 種の利用者を
同時に満たすために設計し直された:

- **ベンチ研究者** — 実験中に Notepad / `less` / `grep` で開く
- **パイプライン開発者** — Python / Rust の reader を書く
  （`session-analyzer`, `aba-advisor`, `session-visualizer` ほか）
- **HIL ベンチエンジニア** — ms 解像度の event を hot path で append。
  クラッシュ後の torn-write を検知できる必要がある

OKL v1 は JSONL に対して **人間可読性**・**素ツールでの開封しやすさ**
（Windows クリーンインストール環境でも `.txt` は Notepad で即開ける）・
**schema 進化と自己記述性**（codebook をファイル header に内蔵）で勝ち、
代償として 1 行あたりのわずかな冗長コストを払う（gzip でほぼ消える）。

## ファイル構造

セッションログは **UTF-8 テキストファイル**、拡張子 `.txt`。
ファイルは以下 3 部から構成される:

1. **マジックライン** — 先頭ちょうど `# OKL v1` の後ろに `\n`
2. **Header ブロック** — `#` で始まる 1 行以上の行、
   末尾は単独の `# ---` 行で終端する
3. **Body** — 1 record = 1 行の TAB 区切り

writer の改行は **LF (`\n`)**。reader は CRLF (`\r\n`) も受容し、
parse 前に行末の `\r` を strip しなければならない。**BOM は付けない**:
writer は出力してはならず、reader は先頭が `U+FEFF` で始まるファイルを
generic な「magic 不一致」ではなく明示的なエラーで拒否すること。

## Header

Header に含めるもの:

- `# session_name = "<文字列>"` — 必須。生成側ラベル
- `# clock_type = "<文字列>"` — 必須。clock 識別子
- `# session_start = <数値>` — 必須。session 開始時刻（生成側時計の秒）
- 任意の top-level key（`experiment_core.SessionMeta` をミラー）:
  - `# subject_id = "<str>"`
  - `# replication_index = <int>`
  - `# experiment_name = "<str>"`
  - `# protocol_id = "<str>"`
  - `# task_file_hash = "<str>"`
  - `# wall_clock_start = "<ISO 8601 datetime>"` — timezone-aware 推奨
- 任意の `# notes:` ブロック。続けて `#   "<note>"` を並べる。
  実験者の事後注釈
- 任意の `# meta:` ブロック。続けて `#   <key> = <value>` を並べる。
  自由形式の追加 metadata。key にはドットを許容（namespace 用、例
  `subject.weight_g = 320`）
- 必須の `# events:` ブロック。続けて `#   <type-name>          : <field>...` を
  並べ、このファイルが含みうる event 型と各型の positional payload 列を
  宣言する **codebook**

未知の top-level key を見た reader は、ファイルが round-trip する形で
`metadata` 配下に保存し、warning を 1 度出すこと。これにより spec 拡張で
新しい top-level key を追加しても古い reader は壊れない（forward-compat）。

Header の値は TOML 基本リテラルを使う:

- `"text"` — UTF-8 文字列。`\` `\"` `\n` `\r` `\t` のエスケープ
- `42` — 整数
- `3.14` / `1e6` — 浮動小数
- `true` / `false` — bool

### codebook field 構文

`# events:` の各行は次の形式:

```
<type-name>          : <field>:<ty>[?] <field>:<ty>[?] ...
```

`<ty>` は `int` / `float` / `str` / `bool` のいずれか。`?` 接尾辞で
optional フィールド。optional 値が欠損のときは body で単独の `-` を書く。

### Canonical codebook

writer は最低限以下を codebook に出力すること（追加は許容）:

```
# events:
#   response          : id:int
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
```

## Body

Body は純 TSV。JSON もクオートも、TSV の流儀以外のエスケープも入らない。
各行は `timestamp` と `type` の 2 列に始まり、その後ろに codebook が
**宣言した順序**で type ごとの payload 列が続く:

```
<timestamp>\t<type>\t<col1>\t<col2>\t...
```

文字列は TSV-escape する:

| リテラル | wire 上の表現 |
|---|---|
| `\`（バックスラッシュ） | `\\` |
| `\t`（タブ） | `\t` |
| `\n`（改行） | `\n` |
| `\r` | `\r` |
| 単独の `-` | `\-` |

単独の `-` は「欠損」を表し、codebook が optional と宣言した列でのみ
許容される。文字値として 1 文字 `-` を書きたいときは `\-` にエスケープ。

未定義のエスケープ列（例: `\q`）を見た reader はそのまま 2 文字 `\q` として
保存しなければならない（forward-compat）。これにより将来仕様で新しい
escape を追加しても古い reader は壊れない。producer は逆にこの寛容性に
依存して非標準のエンコードを密輸してはならない。

### 例

```
# OKL v1
# session_name = "demo"
# clock_type = "ManualClock"
# session_start = 0.0
# subject_id = "rat-001"
# experiment_name = "fr_baseline"
# wall_clock_start = "2026-04-27T14:03:11+09:00"
# notes:
#   "operator note"
# meta:
#   dsl = "FR3"
# events:
#   response          : id:int
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
# ---
0.0	state_change	IDLE	RUNNING
0.523	response	1
1.014	response	2
1.502	response	3
1.502	reinforcer_start	1	1.0	0
2.002	reinforcer_end	1	0
```

`column -t -s $'\t' < session.txt` で完全に整列して見える。
`grep '^[0-9]' session.txt | awk -F'\t' '$2=="response"' | wc -l`
で前処理なしに response 数が数えられる。

## クラッシュ耐性

writer は body 行を 1 件ずつ append し、毎回 flush する。
書き込み途中のクラッシュは末尾の `\n` を欠く torn 行を残す。
reader は最後の完全な行までを正典として扱い、torn 行を捨てなければならない。

## Schema 進化

### 新しい event 型を追加する

producer は `# events:` codebook に新しい行を追加する。新型を知らない
reader はリファレンス実装の `on_unknown` ポリシー（`"warn"` /
`"skip"` / `"error"`）に従う。default の `"warn"` は未知行を skip し
1 度だけ警告する。

### 既存型を削除・改名する

これは破壊的変更。マジックを将来のメジャー版に bump し、reader は
理解できないメジャー版のファイルを拒否すること。

### 既存型に列を追加する

これも破壊的。古い reader が列数を誤算する。マジックを bump するか、
新しい event 型として追加すること。

## 適合性 (Conformance)

任意の reader 実装に対する round-trip テスト: 各 event 型を `OklSink`
で書き、結果のファイルを読み戻し、得られた in-memory event オブジェクトが
元と等価であることを確認する。Python リファレンス実装は
`tests/test_format.py::test_*_round_trip` でこれを実施。

加えて適合 reader は:

- LF と CRLF の両方を受容する
- body の空行を skip する
- 先頭が `# OKL v1` でないファイルを拒否する
- codebook に宣言のない `type` を `on_unknown` ポリシーに従って処理する
- 末尾 `\n` を欠く torn 行を破棄する

## ファイル名規約

producer は `.txt` 拡張子を推奨。base 名の例:
`<session_name>.<YYYYMMDD>.txt` または `<subject_id>.<session_name>.txt`。
複数 session は複数ファイルへ。OKL v1 はファイル内 session 連結を
サポートしない。
