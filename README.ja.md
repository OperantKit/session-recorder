# session-recorder

:gb: [English README](README.md)

session-recorder は、オペラント実験のセッションで起きた出来事（反応・強化子の提示・状態の変化・フェイズ）をプレーンテキストのログファイルに保存し、そのファイルを Python に読み戻します。[OperantKit](https://github.com/OperantKit) でセッションを走らせ、人もプログラムも読めるセッション記録を残したい人のためのパッケージです。OperantKit の中では、セッションを走らせるプログラム（[session-runner](https://github.com/OperantKit/session-runner)）と分析（[session-analyzer](https://github.com/OperantKit/session-analyzer)）の間に位置します。

- **1 セッション 1 ファイルで、テキストエディタで読めます。** 短いヘッダの後に、1 つの出来事につきタブ区切りの 1 行が続きます。
- **ファイルが自分自身を説明します。** ヘッダにセッション名・時計・メモが入り、出来事の種類ごとに型付きの列が宣言されます。
- **過去の MED-PC のデータも合流できます。** MED-PC IV / V のデータファイルを同じ形式に変換できます。

ログの形式は OKL（OperantKitLog）と呼びます。仕様は [OperantKitLog](https://github.com/OperantKit/OperantKitLog) リポジトリにあります。AI コーディングエージェント向けの案内は [AGENTS.md](AGENTS.md) にあります。

## インストール

Python 3.11 以上が必要です。session-recorder はまだ PyPI に登録されていないため、`pip install session-recorder` は今のところ使えません。session-recorder と、それが必要とする OperantKit のパッケージを、依存の解決をせずに GitHub から入れてください。

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-py $G/contingency-py $G/experiment-core $G/session-recorder
```

外部ライブラリは必要ありません。`pip check` はこれらの開発版どうしのバージョンの食い違いを報告しますが、以下の例の動作には影響しません。

## 例

短い FR 3 のセッション（3 回目の反応の後に強化子を 1 回提示）をログファイルに書き、読み戻します。

```python
from experiment_core import ReinforcerEndEvent, ReinforcerStartEvent, ResponseEvent
from session_recorder import OklSink, read_log

sink = OklSink("fr3.txt")
sink.write_header(session_name="demo", clock_type="VirtualClock", session_start=0.0,
                  metadata={"dsl": "FR 3"})
for i, t in enumerate([1.0, 2.0, 3.0], start=1):
    sink.emit(ResponseEvent(id=i, timestamp=t))
sink.emit(ReinforcerStartEvent(id=1, timestamp=3.0))
sink.emit(ReinforcerEndEvent(id=1, timestamp=6.0))  # 強化子へのアクセス 3 秒

log = read_log("fr3.txt")
print(log.meta.session_name, log.meta.metadata, [type(e).__name__ for e in log.events])
# demo {'dsl': 'FR 3'} ['ResponseEvent', 'ResponseEvent', 'ResponseEvent', 'ReinforcerStartEvent', 'ReinforcerEndEvent']
```

書き出されるファイル `fr3.txt` は次のとおりです。

```text
# OKL v1
# session_name = "demo"
# clock_type = "VirtualClock"
# session_start = 0.0
# meta:
#   dsl = "FR 3"
# events:
#   response          : id:int operandum:int?
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
# ---
1.0	response	1	-
2.0	response	2	-
3.0	response	3	-
3.0	reinforcer_start	1	1.0	-
6.0	reinforcer_end	1	-
```

本体の各行は、秒単位の時刻・出来事の種類・ヘッダがその種類に宣言した列の順に並びます。`-` は省略可能な列が空であることを示します（ここでは、反応が行われたレバーやキー＝オペランダムの指定がありません）。標準のコマンドがそのまま使えます。

```bash
grep -v '^#' fr3.txt | awk -F'\t' '$2 == "response"' | wc -l   # 3
```

実際のセッションでは、出来事は [session-runner](https://github.com/OperantKit/session-runner) から届きます。その `sink` に `OklSink` を渡してください。

## 中身

- **`OklSink`** は、空のファイルの先頭にヘッダを 1 度だけ書き、その後は出来事 1 つにつき 1 行を書きます。2 度目のヘッダと、ヘッダより前の出来事は受け付けません。`write_phase_enter` / `write_phase_exit` で、ベースライン・消去・テストなどのフェイズを 1 つのログの中に印せます。[experiment-core](https://github.com/OperantKit/experiment-core) の `EventSink` プロトコルを実装しているため、セッションの出来事を出す OperantKit のプログラムはどれもこれを通して書けます。
- **`read_log` / `iter_records`** は、ログを型付きの `experiment_core` の出来事として読み戻します。ヘッダに無い種類の出来事は、警告・読み飛ばし・エラーのいずれかで扱います（`on_unknown="warn" | "skip" | "error"`）。
- **`session_recorder.format`** は、`experiment_core.SessionEvent` と OKL v1 の wire format の間の正典のシリアライザです。
- **`session_recorder.medpc`** は、MED-PC IV / V のデータファイル（FORMAT 1 Annotated、FORMAT 4 Stripped with Variable Identification）を OKL のログに変換します。
- **[形式の資料](docs/ja/format.md):** session-recorder はセッションの出来事を保存するための正典の wire format を持ちます。このページはその言語に依存しないスキーマの資料です。

### MED-PC のデータを変換する

MED-PC のデータファイルには、出来事のコードが何を意味するかが書かれていません。それを決めているのは、ファイルを書いた MSN プログラムです。そのため `medpc_to_okl` は、`session_recorder.medpc.PROTOCOLS` のうちの 1 つをプロトコルとして受け取ります。組み込みの 4 つのプロトコル（`bernardy-vdrl`、`bernardy-training`、`sosa-inh`、`mccutcheon-prpr`）は、3 つの公開データセット（Bernardy, 2025; McCutcheon, 2022; Sosa et al., 2026）の公開されたプログラムに対応しています。Annotated 形式のファイルは `MSN:` の行からプロトコルを判定します。FORMAT 4 のファイルにはプログラム名が無いため、`protocol=` の指定が必要です。

```python
from pathlib import Path

from session_recorder import read_log
from session_recorder.medpc import medpc_to_okl, read_medpc

Path("JL4.txt").write_text(  # MED-PC FORMAT 1 (Annotated) のファイル
    "Start Date: 08/19/24\nEnd Date: 08/19/24\nSubject: JL4\nExperiment: VDRL\n"
    "Group: 1\nBox: 4\nStart Time:  9:51:02\nEnd Time: 11:08:00\nMSN: Training\n"
    "A:\n     0:  0.000  270000.000  60.000  3.000  30.000\n"
    "C:\n     0:  0.111  2742.200  5763.400  27000.999\n"
)
for i, session in enumerate(read_medpc("JL4.txt")):
    result = medpc_to_okl(session, f"session_{i}.txt")  # プロトコルは MSN から判定
    assert result.primary + sum(result.unmapped.values()) == result.source_events

log = read_log("session_0.txt")
print(log.meta.metadata["schedule.spec_dsl"], [type(e).__name__ for e in log.events])
# VI 30s ['StateChangeEvent', 'ResponseEvent', 'ReinforcerStartEvent', 'StateChangeEvent']
```

元のファイルの出来事はすべて、1 行に書かれるか、対応なし（ヘッダの `medpc.unmapped_codes`）として数えられます。ファイルに記録されていないセッション開始など、変換の側で足した行は `medpc.synthesised_lines` に数えられます。別の MSN プログラムを読むには、`MedPcSession` を `Converted` に変える関数を書き、`Protocol` として登録してください。

## 制限

- Python 専用です。他の言語の読み取りプログラムは、[OperantKitLog](https://github.com/OperantKit/OperantKitLog) の仕様に沿って書く必要があります。
- 1 ファイルに 1 セッションです。OKL は 1 つのファイルに複数のセッションをつなげません。
- MED-PC の取り込みが読めるのは、プロトコルのあるプログラムだけです。それらのプログラムが記録する餌皿への頭部の進入・退出は拡張の種類 `head_entry` / `head_exit` として書かれ、`read_log` はこれらを `events` ではなく `raw_records` に入れます。

## 開発

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/pytest
```

この README と `README.md` の `python` のコードブロックはすべて、`tests/test_readme_examples.py` が実行します。

## 参考文献

- Bernardy, J. L. (2025). *Supplemental material: Feedback function and performance on variable differential reinforcement of low rates: Tempus urgit vel abundat?* [Data set]. Harvard Dataverse. https://doi.org/10.7910/DVN/BXVB2F
- McCutcheon, J. (2022). *Progressive ratio in protein-restricted vs. non-restricted rats* [Data set]. Zenodo. https://doi.org/10.5281/zenodo.5409201
- Sosa, R., Mata-Luévanos, J., Tapia-de-Jesús, A., Saavedra, P., & Buenrostro-Jáuregui, M. (2026). *Longitudinal association between different indices of behavioral inhibition* [Data set]. Zenodo. https://doi.org/10.5281/zenodo.19164959

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
