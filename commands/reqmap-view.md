---
description: 要件の全体像をHTMLで可視化する。依存の地図・網羅グリッド・次に決める順・領域別の進捗
argument-hint: [プロジェクトのパス]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli:*)
---

!`${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli view --root="${1:-.}"`

出力先のパスを伝えてください。4つのビューがあります。

- **次に決める順** — 順位表。迷ったらここだけ見れば足ります
- **依存の地図** — 層別DAG。左が先、右が後。横軸は決める順番
- **網羅グリッド** — 1マス1観点。空白は「インクが無い」ことで読みます。俯瞰用
- **領域別の進捗** — 未決の質量がどこに溜まっているか

自己完結HTMLなので、そのまま共有できます（CDN参照なし・オフラインで開けます）。
