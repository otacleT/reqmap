# ループを閉じる7機能 — 実装計画（2026-09-17）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 観点→論点→決定→仕様→検証のループで手作業のまま残っている継ぎ目を、決定論的なコマンドと観点で埋める。

**Architecture:** 既存モジュールに小さく足す。新規は `filing.py`（観点→論点ページ）だけ。fslc の呼び出しは `fsl.py` に閉じたまま。HTML は既存の網羅グリッドと同じ読み方（インクが無い＝穴）で状態×イベント表を足す。

**Tech Stack:** Python 3 標準ライブラリ、unittest。fslc は任意。

**Spec:** 会話で合意した順序 3 → 4・5 → 1 → 7 → 2 → 6（下の Task 1〜7）。

## Global Constraints

- 機械が書くのは計算済み7キーと、`gaps --file` が作る **open な論点ページ**だけ。`status` `decision` `severity` には触らない。
- 観点は出しすぎない。起票済み（`cells:` で紐付いた）マスは穴として出さない。
- 外部依存なし。コミットは最後にまとめて（利用者の選択後）。

---

### Task 1: `reqmap ci` — 矛盾と壊れで exit 1

- Modify: `scripts/reqmap/cli.py`（`cmd_ci`）、`scripts/reqmap/model.py`（`DEFAULTS["ci_gate"]`）、`templates/reqmap.yml`
- Test: `tests/test_cli_ci.py`
- ゲート既定: `fsl.forbidden_accepted` `fsl.acceptance_failed` `fsl.violated` `fsl.seam_broken` `fsl.spec_error` `fsl.legacy_format` `graph.conflict` `graph.cycle` `rule.duplicate_id`。仕様があるのに fslc が無い `fsl.tool_missing` も NG（`--allow-missing-fslc` で許す）。`reqmap.yml` の `ci_gate:` で差し替え可。
- [x] テスト（矛盾あり→1 / 無し→0 / fslc 無し→1、フラグで 0）→ RED → 実装 → GREEN

### Task 2: `fsl.thin_spec` — 検証条件の無い仕様

- Modify: `scripts/reqmap/fsl.py`（`read_source` に `acceptance` ID、`gaps` に finding）
- Test: `tests/test_fsl_run.py` に追加
- 遷移があるのに forbidden も acceptance も無い仕様に 1 件（medium）。
- [x] テスト → RED → 実装 → GREEN

### Task 3: 穴の質問文に「いまの仕様ではこうなる」

- Modify: `scripts/reqmap/fsl.py`（`matrix_findings` の文言）
- Test: `tests/test_fsl_matrix.py` に追加
- 「いまの仕様では拒否されます（遷移が無い）。それで良ければ forbidden に…」
- [x] テスト → RED → 実装 → GREEN

### Task 4: `reqmap gaps --file <観点ID,...>` — 観点から論点ページを起票

- Create: `scripts/reqmap/filing.py`（`fileable(f)`, `plan(proj, f) -> {id, title, area, severity, cells, body}`, `write(proj, plan) -> path`）
- Modify: `scripts/reqmap/cli.py`（`cmd_gaps` の `--file=`）、`scripts/reqmap/fsl.py`（`cells:` で紐付いたマスは穴にしない。取下げページの `cells:` は数えない）、`scripts/reqmap/gaps.py`（取下げページの `cells:` は数えない）
- Test: `tests/test_filing.py`
- 起票できる観点: `grid.empty` `grid.row_empty` `grid.not_itemised` `fsl.state_event_hole` `fsl.unused_event` `fsl.undecided_unlinked`。それ以外は「論点ではありません」と断る。ID は slug（`lifecycle.media-retain` / `order.preparing-cancel`）。既存 ID と衝突したら書かない。
- [x] テスト → RED → 実装 → GREEN

### Task 5: `reqmap show <id>` — 1論点の全部

- Modify: `scripts/reqmap/cli.py`（`cmd_show`）
- Test: `tests/test_cli_show.py`
- 基本情報 / 日付と影響度 / 前提と下流（状態つき） / cells / log と指標 / 仮置き / 仕様側の関連宣言 / この論点に関する観点 / 論点と決まったことの本文。
- [x] テスト → RED → 実装 → GREEN

### Task 6: `fsl.spec_behind_decision` — 決定が仕様より新しい

- Modify: `scripts/reqmap/fsl.py`
- Test: `tests/test_fsl_run.py` に追加（mtime で検証）
- 仕様に紐付く論点（@depends_on / cells / @undecided）が decided で、log の `decided` 日付が仕様の更新日（git の最終コミット日と mtime の新しいほう）より新しければ high で 1 件。
- [x] テスト → RED → 実装 → GREEN

### Task 7: HTML に「状態×イベント」タブ

- Modify: `scripts/reqmap/fsl.py`（summary に `matrix` を載せる）、`scripts/reqmap/view.py`
- Test: `tests/test_view.py`
- マスの状態: defined / forbidden / impossible / linked / hole / suppressed / terminal。網羅グリッドと同じ配色と読み方。
- [x] テスト → RED → 実装 → GREEN

### Task 8: ドキュメントと版

- README（何ができるか・仕掛け 7 の表・サンプル表）、GUIDE（1-4 / 3 / 4-2 / 7）、スキル、`commands/reqmap-gaps.md`、新規 `commands/reqmap-show.md`、`plugin.json` 0.3.0
- [x] 書く → `python3 -m unittest discover -s tests` → サンプルで全コマンド
