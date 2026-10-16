# session-recorder

:gb: [English README](README.md)

OperantKit セッションイベントの OKL v1 フォーマット定義 +
writer / reader。

## 役割

`session-recorder` は、セッションイベント永続化の正典となる **wire
format**（[OKL v1 スキーマ](docs/ja/format.md)）と、その Python
**writer** + **reader** を提供する。**セッションを駆動したり、
ハードウェアをポーリングしたり、DSL をパースしたりはしない** —
それらの責務は別パッケージに分離されている:

| 責務 | パッケージ |
|---|---|
| セッションライフサイクル（イベント） | `experiment-core` |
| セッション駆動（manual API） | `session-runner` |
| HAL Protocol + ハードウェア駆動 | `experiment-io` |
| DSL パース | `contingency-dsl-py` |
| スケジュールランタイム | `contingency-py` |
| エンドツーエンド CLI glue | `operantkit-cli` |

## 責務

- **`OklSink`** — `experiment_core.EventSink` Protocol を実装。
  OKL v1 ヘッダを 1 度だけ書いた後、`emit` されたイベントを
  1 行 1 TSV で追記する。
- **`read_log` / `iter_records`** — OKL v1 ログを型付き Python
  オブジェクトに読み戻す。未知の event 型は
  `on_unknown="warn" | "skip" | "error"` で挙動を選べる。
- **Format モジュール**（`session_recorder.format`） —
  `experiment_core.SessionEvent` と OKL v1 wire format 間の正典
  シリアライザ / デシリアライザ。
- **Format ドキュメント**（[`docs/en/format.md`](docs/en/format.md)） —
  言語非依存のスキーマリファレンス。将来の Rust / TypeScript reader は
  これにバイト単位で従うこと。

## インストール

```bash
pip install session-recorder
```

開発用:

```bash
mise exec -- python -m venv .venv
mise exec -- .venv/bin/python -m pip install -e ../experiment-core
mise exec -- .venv/bin/python -m pip install -e '.[dev]'
```

`experiment-core` はローカル依存解決のため path install する。

## 30 秒で動く例

短い FR 3 のセッションを OKL v1 ファイルに書き、型付きのイベントとして読み戻す:

```python
from experiment_core import ReinforcerEndEvent, ReinforcerStartEvent, ResponseEvent
from session_recorder import OklSink, read_log

sink = OklSink("fr3.okl")
sink.write_header(session_name="demo", clock_type="VirtualClock", session_start=0.0,
                  metadata={"dsl": "FR 3"})
for i, t in enumerate([1.0, 2.0, 3.0], start=1):
    sink.emit(ResponseEvent(id=i, timestamp=t))
sink.emit(ReinforcerStartEvent(id=1, timestamp=3.0))
sink.emit(ReinforcerEndEvent(id=1, timestamp=6.0))  # 3 秒間の強化子提示

print(open("fr3.okl", encoding="utf-8").read().split("# ---\n")[1], end="")
# 1.0	response	1	-
# 2.0	response	2	-
# 3.0	response	3	-
# 3.0	reinforcer_start	1	1.0	-
# 6.0	reinforcer_end	1	-

log = read_log("fr3.okl")
print(log.meta.session_name, log.meta.metadata, [type(e).__name__ for e in log.events][-2:])
# demo {'dsl': 'FR 3'} ['ReinforcerStartEvent', 'ReinforcerEndEvent']
```

ファイルは注釈行のヘッダ（セッション名・時計・メタデータ、各イベント種別とその列を宣言するコードブック）で始まり、その後に 1 イベント 1 行のタブ区切りの行が続く。`grep` や `awk` がそのまま使える。実際のセッションでは、イベントは [session-runner](https://github.com/OperantKit/session-runner)（`pip install session-runner`）から来る。`OklSink` をその `sink` に渡すか、`tee` で他の sink と組み合わせる。

## 自作の 50 行のロガーでは足りない理由

イベントごとに CSV や `json.dumps` で書くだけのロガーは、セッション記録を再利用可能にする次の点を落とす:

- **自己記述的なファイル.** ヘッダはセッション名・時計の種類・開始時刻・自由形式のメタデータ（例: DSL の原文）と、型付きの列を持つイベント種別のコードブックを持つ。本文の解釈に本パッケージは要らない。
- **型付きイベントへの往復.** `read_log` / `iter_records` は各行を `experiment_core` のイベントクラス（`ResponseEvent`、`ReinforcerStartEvent` など）に戻す。オペランダムと強化子の potency も含む。
- **未知のイベントを明示的に扱う.** コードブックに無いイベント種別は、警告・読み飛ばし・エラーのいずれかにする（`on_unknown="warn" | "skip" | "error"`）。誤って解釈することはない。
- **エスケープと欠損値.** 文字列の列にあるタブ・改行・バックスラッシュはエスケープし、省略可能な値の欠損は `-` で書くので、どの行も列数が決まっている。
- **ヘッダは 1 回だけ、先頭に書く.** `OklSink` は 2 回目のヘッダ、空でないファイルへのヘッダの追加、ヘッダより前のイベントを拒否する。
- **フェーズの区切り.** `write_phase_enter` / `write_phase_exit` で、1 つの記録の中にベースライン・消去・テストなどのフェーズを記せる。
- **仕様のある形式.** 形式は [OperantKitLog](https://github.com/OperantKit/OperantKitLog)（文法・ヘッダ・コードブック・ワイヤ形式）で定義され、本パッケージのテストは正常系と異常系あわせて 10 個の適合性ファイルを読む。

## クイックスタート

### 書き込み

```python
from session_recorder import OklSink
from experiment_core import ResponseEvent

sink = OklSink("session.txt")
sink.write_header(
    session_name="demo",
    clock_type="ManualClock",
    session_start=0.0,
    metadata={"dsl": "FR3"},
)
sink.emit(ResponseEvent(id=1, timestamp=0.5))
```

`OklSink` は `experiment_core.EventSink` Protocol を満たすため、
セッションイベントを emit する任意のプロデューサ（例: `session-runner`
の `SessionRunner`）に渡せる。

### 読み込み

```python
from session_recorder import read_log

log = read_log("session.txt")
print(log.meta.session_name)
for event in log.events:
    print(event)
```

`session.txt` は素の UTF-8 テキストで、`less`・`grep`・`awk`・Notepad
で前処理なしに開ける:

```bash
column -t -s $'\t' < session.txt
grep '^[0-9]' session.txt | awk -F'\t' '$2=="response"' | wc -l
```

## 開発

```bash
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/black --check src tests
```

## フォーマット仕様

OKL v1 スキーマは [`docs/ja/format.md`](docs/ja/format.md) を参照。

## 参考文献

- Ferster, C. B., & Skinner, B. F. (1957). *Schedules of reinforcement*.
  Appleton-Century-Crofts.
