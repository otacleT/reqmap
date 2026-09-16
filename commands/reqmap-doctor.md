---
description: この要件定義プロジェクトをちゃんと読めているかを点検する。観点は出さない
argument-hint: [プロジェクトのパス]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli:*) Read
---

!`${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli doctor --root="${1:-.}"`

⚠ は**観点が出ない原因**です。優先して伝えてください。

特に「論点があるのに語が1件も当たらない行」は、次のどちらかです。

- グリッドの語が案件の実体と合っていない → `coverage-grids` スキルを読んで語を直す
- その観点が領域を横断している → グリッドの `area:` を外す

「読めないページ」があれば、**それを捨てたまま点検すると「異常なし」に見えます。**
先に直すよう促してください。
