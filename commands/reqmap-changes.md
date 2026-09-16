---
description: 前回見たときから書き換わった決定を出す。自分の設計に効くかを判断するために毎朝見る
argument-hint: [プロジェクトのパス]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli:*) Read
---

!`${CLAUDE_PLUGIN_ROOT}/scripts/reqmap-cli changes --root="${1:-.}"`

読んで伝えてください。

1. **書き換わった決定があれば、何がどう変わったか**を `git diff` で確かめてから伝える。
   指紋が変わったことだけ伝えても判断できません
2. 「新しく決まった」は、それに依存していた論点が動けるようになった合図です。
   `reqmap status` で次に何が聞けるようになったかを続けて出すと親切です
3. 「決定から外れた（再オープン・取下げ）」は**最優先**。それを前提に進んだ作業が
   全部宙に浮いています
4. 書き換わった決定が状態遷移に関わるなら、`models/fsl/*.fsl` にも写されているか確かめる。
   写されていなければ `reqmap gaps fsl` で `fsl.stale_undecided` が出ているはずです

見終わったら `reqmap changes --ack` で基準を進めるか聞いてください。
**勝手に進めないこと。** 基準を進めると、次回から同じ変化が出なくなります。
