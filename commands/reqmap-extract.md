---
description: 議事録・打ち合わせメモから論点を抽出して Change Set を作る。引用を原文と照合してから反映する
argument-hint: [議事録のパス] [プロジェクトのパス]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli:*) Read Glob Grep Write Task
---

議事録: `$1`
プロジェクト: `${2:-.}`

`reqmap-extractor` サブエージェントに抽出させてください。直接書かないこと。

サブエージェントには次を伝えます。

- 原文のパスと、プロジェクトのルート
- `_changesets/` に Change Set を書くこと。`questions/` には触らないこと
- **quote は原文からの逐語引用**。機械が照合するので、要約したものは blocked になる
- **言われたことだけ**を拾う。言われなかった観点は `reqmap gaps` の担当

戻ってきたら、あなたの側で:

1. `reqmap review --root=${2:-.}` を実行して分類を確認する
2. `blocked` があれば**先に伝える**。モデルが原文に無いことを書いた合図です
3. `human` のものを**1件ずつ、何を確認したいかを添えて**ユーザーに聞く。選択式で
4. 合意が取れたら `reqmap apply --root=${2:-.} --approve=<id,...>` を実行
5. 最後に `reqmap recalc --root=${2:-.}`

**Change Set の中身を全部貼らないでください。** 判断が要るものだけを出します。
