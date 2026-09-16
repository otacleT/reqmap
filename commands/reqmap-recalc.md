---
description: 影響度・依存の深さ・着手可否・逆算した期日を再計算してfrontmatterに書く
argument-hint: [プロジェクトのパス] [--check で書かずに確認]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli:*)
---

!`${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli recalc --root="${1:-.}" $2`

書き換わるのは計算済みの7キーだけです
（blocks_count / blocking / impact_count / ready / depth / need_by / ask_by）。

`status` `decision` `severity` には**機械は触りません。** あなたも触らないでください。
決定は人が下します。

規約違反が出ていたら、内容を噛み砕いて伝え、直し方を提案してください。
