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
| エンドツーエンド CLI glue | `operant-cli` |

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
mise exec -- python -m venv .venv
mise exec -- .venv/bin/python -m pip install -e ../experiment-core
mise exec -- .venv/bin/python -m pip install -e '.[dev]'
```

`experiment-core` はローカル依存解決のため path install する。

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
