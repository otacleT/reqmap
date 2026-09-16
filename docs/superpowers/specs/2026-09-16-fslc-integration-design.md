# reqmap × fslc 連携と、評価で見つかった欠陥の修正 — 設計

2026-09-16。評価（設計レビュー）で出た9項目の推奨案を実装するための設計メモ。
「FSL」は https://github.com/ymm-oss/fsl の fslc を指す。jssm 互換の遷移表記は廃止する。

## 決めたこと

### 1. FSL の位置づけ — 「reqmap が問い、答えを fslc が検証する」二段構え

- `models/fsl/*.fsl` は fslc の `requirements` 方言で書く（旧 `models/fsm/` も読むが、
  jssm 形式のファイルは `fsl.legacy_format` として警告し、読まない）。
- 検証は fslc に任せる。reqmap は `fslc check` / `fslc kernel` / `fslc verify` の JSON を読み、
  確認観点（findings）に写すだけ。fslc が無い環境では `fsl.tool_missing` を1件出して省略する。
- 状態×イベントの網羅（引き出し用の表）は残す。表の構造は `fslc kernel` から取る
  （`<entity>_stage` の Map と `<Entity>Stage` の enum、各アクションの requires/updates）。
  同じイベントを複数の遷移に分ける場合は遷移の前行に `@reqmap.event("cancel")` を書く。
- reqmap 固有のメタデータはコメント指令のまま（fslc からは不可視）:
  `// @area:` `// @depends_on:` `// @events:` `// @critical:` `// @impossible:`。
  `@critical` に書いたイベントは隣接に限らず全状態で問う（再現率の穴を塞ぐ）。
- 「起こり得ない」の記録は2通り。`// @impossible: Stage x event | 理由`（未検証の記録）と、
  `forbidden`（検証される記録）。forbidden の最終ステップが当たるマスも「回答済み」と扱う。
- 未決定は fslc の `@undecided("<論点ID> 理由")` で仕様側に置く。
  論点が open ならそれが正常なので何も出さない。論点が decided/dropped なのに残っていれば
  `fsl.stale_undecided`（決定が仕様に反映されていない）。論点IDが解決できなければ
  `fsl.undecided_unlinked`（仕様にある未決定が起票されていない）。
- fslc 由来の finding: `fsl.spec_error` `fsl.forbidden_accepted` `fsl.acceptance_failed`
  `fsl.violated` `fsl.seam_broken` `fsl.dead_action` `fsl.dead_end` `fsl.unreachable_stage`
  `fsl.state_event_hole` `fsl.unused_event` `fsl.stale_undecided` `fsl.undecided_unlinked`
  `fsl.tool_missing` `fsl.legacy_format`。
  「後から書いた決定が前の決定と矛盾する」は `fsl.forbidden_accepted` に出る。これが
  評価で無かった「内容の矛盾」の検出経路。
- 注釈（`@undecided` `@reqmap.event`）と forbidden の最終ステップは fslc の JSON に出ないので
  原文の正規表現で読む。fslc の意味論には触れない範囲に限定する。
- 深さは `reqmap.yml` の `fsl_depth`（既定 8）。

### 2. `conflicts` の実装

両方が決定／仮決定なら `graph.conflict`（high）。片方だけ決まっていれば
もう片方を「取下げ候補」として `graph.conflict_pending`（low）。

### 3. 逆算日付の式

上流 i、下流 v について `need_by(i) = need_by(v) − resp_days(v) − lead_time(i)`。
これまでは resp_days(i) を引いていた（上下の応答日数が同じ時だけ偶然一致していた）。

### 4. 循環の局所化

強連結成分（Tarjan）で循環に乗っている論点だけを初期値に落とす。他は通常計算。
`recalc` は「循環 N 本、M 論点は初期値」と告知する。depth/need_by はメモ化する。

### 5. `derives` の意味を持たせる

derives の上流が決まった論点は「聞く」ものではなく「書き取る」もの。
`status` の「いま聞けて」から外し、「上流が決まったので機械的に決められるもの」として別枠で出す。

### 6. 引用ゲートの補強

`quote_min_chars`（既定 12）未満、または原文に複数回出現する引用は `human` に引き上げる
（存在はするので blocked にはしない）。

### 7. 基準の分離

観点の既読は `.reqmap/findings-seen.json`（`gaps --snapshot`）、決定の基準は
`.reqmap/decisions-seen.json`（`changes --ack`）。旧形式（1ファイル）は読める。

### 8. 実装バグと残骸

`reqmap json` の日付シリアライズ、README の `trace`、`design_dirs` `covers` `Task`。
README の「仕込んだ欠陥」表をそのまま回帰テスト（unittest、外部依存なし）にする。

## やらないこと

- 設計ハーネス。設計側の記帳。
- fslc の出力をキャッシュすること（十分速い）。
- jssm 形式からの自動変換。
