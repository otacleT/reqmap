# reqmap — 要件定義ハーネス

やりたいことを仕様に落とすには、**何を決めないといけないのかの全体像**と、
**決定どうしの依存関係**が要る。エクセルやQA表ではどちらも表現できない。

reqmap はその2つを機械可読なファイルで持ち、**決定論的な検査で確認観点を生む**。
LLM は観点を出さない。観点を人に出せる日本語にするのが LLM の仕事。

## 入れ方

```bash
/plugin marketplace add /path/to/reqmap
/plugin install reqmap@reqmap-local
```

開発中は `claude --plugin-dir /path/to/reqmap` でも試せます。

CLI 単体でも動きます（**外部依存なし**。PyYAML も不要）:

```bash
/path/to/reqmap/scripts/reqmap-cli init ./myproject
/path/to/reqmap/scripts/reqmap-cli gaps --root=./myproject
```

状態遷移の検証には [fslc](https://github.com/ymm-oss/fsl) を使います（任意。無ければその検査だけ
省略し、`fsl.tool_missing` を1件出します）:

```bash
git clone https://github.com/ymm-oss/fsl ~/.fsl && bash ~/.fsl/install.sh
```

## 使い方

**[GUIDE.md](GUIDE.md)** に、立ち上げから日々の運用までを「やること順」で書いています。
初めてならそちらから読んでください。

## 何ができるか

```
reqmap init      雛形を作る（設定・汎用グリッド・論点テンプレート）
reqmap status    静かな点検。人が動くものだけ。静かな日は1行
reqmap gaps      確認観点を出す。何も書かない
reqmap review    Change Set を点検する（引用照合とゲート分類）
reqmap apply     Change Set の auto を適用する
reqmap doctor    この vault をちゃんと読めているかを点検する（観点は出さない）
reqmap gaps --new       前回見たときから新しく出た観点だけ
reqmap gaps --snapshot  観点を「ここまでは見た」と記録する
reqmap changes   前回見たときから書き換わった決定を出す
reqmap changes --ack    決定を「ここまでは見た」と記録する
reqmap recalc    影響度・依存の深さ・着手可否・逆算した期日を書く
reqmap view      自己完結HTMLを出す（CDN参照なし）
reqmap json      全データをJSONで（他ツール連携用）
```

`/reqmap-extract <議事録>` で議事録から論点を起こします。

## 7つの仕掛け

### 1. 観点を新しく生む — 網羅グリッド

資料どうしを突き合わせる方式では「資料に書いてあることの取りこぼし」しか拾えない。
**「資料にそもそも書かれていないこと」は構造的に出てこない。**

グリッドは「あるべきマス」を人が宣言し、機械が「埋まっていないマス」を引く。
資料に無くても穴が出る。同梱の汎用グリッドは4つ:

| グリッド | 何を問うか |
|---|---|
| `errors` | どの操作が、通信断／タイムアウト／二重送信／同時更新／一部成功／中断復帰／冪等性でどうなるか |
| `lifecycle` | どのデータが、生成／保存／保持期間／論理削除／物理削除／削除伝播／エクスポートでどうなるか |
| `authz` | 誰が（未ログイン／本人／他人／運用者／外部連携先）何にアクセスできるか |
| `i18n` | 何を（文言／コンテンツ／通知／規約／入力データ）どう多言語・多地域対応するか |

主フローの状態遷移は [FSL](https://github.com/ymm-oss/fsl)（fslc の `requirements` 方言）で書きます。
reqmap は仕様の構造から状態×イベントの表を組み、**二重送信・二重決済・例外経路の欠落**を
「どうなりますか？」として出します。仕様そのものの検証は fslc がやります（仕掛け 7）。

### 2. 議事録から論点を起こす — 引用の機械照合

議事録から論点を起こすのは LLM の仕事ですが、**LLM が `questions/` に直接書くと、
何が人の言葉で何がモデルの創作かの区別が消えます。** 一度混ざったら分離できません。

`reqmap-extractor` は `_changesets/` に提案を書き、1件ごとに `quote`（原文からの逐語引用）を
持たせます。**機械が原文と照合します。** モデルの自己申告には頼りません。

| ゲート | 条件 | 扱い |
|---|---|---|
| `auto` | 新規の未決論点・引用が原文に一致・既存ページに触れない | 適用してよい |
| `human` | 既存ページの変更、決定に触れるもの、前提が未起票 | チャットで確認してから |
| `blocked` | **引用が原文に無い**、参照先が存在しない、必須項目が欠けている | 動かせない |

**判定は一方通行（ラチェット）。機械は `auto` → `human` へ引き上げることしかしません。**
ファイルに手書きで `human` / `blocked` と書いてあるものを `auto` へ下げることはありません。

`op: update` は approve しても機械は書き換えません。既存の文はページを直接直します。

議事録に「〜でいきます」と書いてあっても `status: decided` にはしません。
議事録の「決まりました」はしばしばその場の空気であって合意ではなく、
後から「そんなつもりはなかった」になる論点がいちばん高い確率で炎上するからです。

### 3. 決める順番が出る — 型つきの依存

依存は4種類。**上流を指す**（「これが先」）。

| | 意味 | 何が出るか |
|---|---|---|
| `blocks` | 決まらないと着手できない（本文の `## 前提`） | 決める順番・クリティカルパス |
| `derives` | 決まれば機械的に従属する | 冗長な質問の抑制 |
| `constrains` | 選択肢を狭める | **変えたら何が壊れるかの波及** |
| `conflicts` | 両立しない | 矛盾検出 |

影響度は2本立て。1本だと変更時の波及が見えません。

- `blocks_count` … いま何件を**止めている**か → 決める順番
- `impact_count` … 変えたら何件の**再検討が要る**か → 仕様変更が来たときに効く

さらに、マイルストーンから**逆算**して「いつまでに聞かないと間に合わないか」（`ask_by`）を出します。

### 4. やりとりを型付きで残す — 回答日数が実測になる

論点ページは「いまの状態」しか持っていませんでした。`open → decided` の**遷移の履歴が無い**。
その結果、実測できるデータ（出した日・返ってきた日）があるのに、
回答日数が永久に仮置きのままになります。

```yaml
log:
  - 2026-09-10 asked | 定例で確認依頼
  - 2026-09-24 answered | 保持期間は5年と回答
  - 2026-09-24 decided
  - 2026-10-02 reopened | 法務から再検討の指示
```

追記しかしません。これで出るもの:

| check | 意味 |
|---|---|
| `turn.no_response` | 出してから想定の1.5倍待っている＝**催促どき** |
| `turn.reasked` | 3回以上聞き直している＝**相手ではなく問いの立て方の問題** |
| `turn.churn` | 2回以上ひっくり返った決定＝**3回目もひっくり返る** |

`ask_by` の逆算も、実測が溜まるほど精度が上がります。
`status` は log を見て、**すでに出して返事待ちのものを「いま聞け」と言いません。**

### 5. 決定が書き換わったら気づける — 設計側の記帳なしで

**設計ハーネスは作りません。** 設計は各メンバーがそれぞれAIエージェントと進める前提です。

設計ドキュメントに「この決定に基づいて書いた」と記帳させる方式は試して捨てました。
**書くのは設計する人で、得をするのは後から変更を追う人**だからです。
書く人に見返りが無いものは書かれません。トレーサビリティの仕組みが根付かない理由は
だいたいこれで、設計を分散してやるなら全員に守らせることになるので、なおさら成立しません。

分散設計で本当に困るのは「どの設計書が古いか」ではなく、
**決定が変わったことに誰も気づかない**ことです。

```
$ reqmap changes
# 決定の変化  2026-09-16 以降

■ 中身が書き換わった決定 1 件 — **自分の設計に効くか確かめてください**
  Q-005  [決定] 注文ステータス通知をLINEプッシュにするか
         指紋 44b7d4ad → be4fbf0d
```

指紋は `status` と「決まったこと」の本文から取ります。**決定日ではなく中身から取るのが要点**で、
「決定日はそのままで結論だけ直す」が実務では普通に起きるため、日付で見ていると黙って見逃します。

見終わったら `reqmap changes --ack` で基準を進めます。観点の既読（`gaps --snapshot`）とは
**別の基準**です。進むタイミングが違う（決定は毎朝、観点は定例前）ので、1つにすると
片方の差分が黙って消えます。

`.reqmap/` は**各自のもの**です（`init` が `.gitignore` を置きます）。
各メンバーが自分の「前回見たとき」を持ち、自分の設計に効くかを自分で判断します。

### 6. 出しすぎない

**「今週決めないと止まる3件」のほうが、正しい100件より価値がある。**

- **毎朝同じものを見せない。** findings のIDは内容から決まるので、`gaps --new` で
  前回から増えた分だけを出せる（並び順で採番すると1件増えただけで全IDがずれます）
- 状態×イベントは全マス総当たりにしない（実測で 31件 → 10件、残りは全部意味のある質問）
- 行が丸ごと空なら1件にまとめる
- グリッドが丸ごと空なら「まだマス単位に落ちていない」という別種の1件にする
- `status` は静かな日は1行で終わる

### 7. 決定を仕様に写す — 内容の矛盾は fslc が見つける

論点ページの「決まったこと」は自由文です。**自由文どうしの矛盾は機械には見えません。**
そこで、状態遷移に関わる決定は `models/fsl/*.fsl` に写します。遷移を足す、`forbidden` で
拒否を書く、`when` で条件を付ける。それを [fslc](https://github.com/ymm-oss/fsl) が検証します。

```fsl
// Q-007（二重決済）が決まったときに書いた主張
forbidden FB-ORDER-002 "支払済み注文への再決済は拒否される" {
  submit(0) pay(0) repay(0)
  expect rejected
}
```

後日「支払済みでも再決済を受け付ける」と決めて遷移を足すと、この forbidden が受理されて
`fsl.forbidden_accepted` が出ます。**前の決定と後の決定の矛盾**を、日付ではなく内容で検出します。

検証は fslc がやり、reqmap はその JSON を観点に写すだけです。

| check | 意味 |
|---|---|
| `fsl.forbidden_accepted` | 禁止したはずの操作列が受理される＝**後の決定が前の決定と矛盾** |
| `fsl.acceptance_failed` / `fsl.violated` | 受入基準が通らない／不変条件が破れる |
| `fsl.state_event_hole` / `fsl.unused_event` | 状態×イベントの穴（これは reqmap が問う） |
| `fsl.dead_end` / `fsl.dead_action` / `fsl.unreachable_stage` | 行き止まり／起きない遷移／到達しない状態 |
| `fsl.stale_undecided` | 論点は決まったのに仕様が `@undecided` のまま＝**決定が仕様に未反映** |
| `fsl.undecided_unlinked` | 仕様に未決定があるのに論点が起票されていない |
| `fsl.spec_error` / `fsl.tool_missing` | 仕様が読めない／fslc が無い（観点が出ない原因） |

未決定は `@undecided("Q-006 返金条件は決定待ち")` と、**論点IDを先頭に**書きます。
論点が open ならそれが正常で、何も出ません。決まったのに残っていれば出ます。

状態×イベントは全マス総当たりにせず、定義済みの状態の**隣**だけを問います。
ただし `// @critical: cancel` と書いたイベントは全状態で問います。隣接だけだと
「調理中のキャンセル」のような一番揉めるマスが抑制側に落ちるからです。

書き方は `templates/fsl/order.fsl` と、fslc 同梱の `fsl-requirements` スキルを見てください。

## ID は slug

`data.retention-period` のような形。ファイル名と一致させます。連番は使いません。

ID が要るのは**タイトルが変わっても参照が壊れないため**の一点だけで、連番である必要はありません。
連番には4つの問題があります — 採番の調整が要る／意味を持たない／分割すると親子が読めない
（`Q-012` → `Q-138/139/140` では関係が分からない）／若い番号が重要と誤読される。

slug には副作用として良い性質があります。**slug が付けられない論点は、論点が同居している。**
「保持期間・受付経路・対象範囲」に1つの slug は付きません。分割の合図として使えます。

相手側の番号（QA表の #12 など）は `ledger:` に別で持ちます。**ID には混ぜません。**
リネームしたくなったら `aliases:` に旧IDを残せば `[[リンク]]` も型つき依存も壊れません。
連番の既存 vault もそのまま読めます。

## 書き込みの約束

`recalc` が書くのは計算済みの7キーだけ:
`blocks_count` `blocking` `impact_count` `ready` `depth` `need_by` `ask_by`

**`status` `decision` `severity` には機械が触りません。** 決定は人が下します。
機械が決定欄に触れるようになった瞬間、この仕組みは信用できなくなります。

## ファイル構成

```
<project>/
  reqmap.yml           設定（マイルストーン・領域・回答日数）
  questions/           1論点1ファイル（Markdown + frontmatter）
  models/grids/*.yml   N×M の網羅グリッド
  models/fsl/*.fsl     状態遷移の仕様（fslc の requirements 方言）。fslc が検証する
  _changesets/         議事録や設計からの提案。引用照合を通ってから反映される
  .reqmap/             出力と「前回自分が見たとき」の基準。**各自のもの**（gitignore 済み）
```

`questions/` は Obsidian でそのまま開けます。`## 前提` の `[[wikilink]]` が
グラフビューの辺になります。**ただし Obsidian は任意** — CLI と HTML は無しで完結します。

## サンプル

`examples/takeout-app/` に、意図的に欠陥を仕込んだ案件が入っています。

| 仕込んだ欠陥 | 検出されるチェック |
|---|---|
| 期限切れの仮置き（Stripe 前提を10日放置） | `assumption.stale` |
| 上流が未決なのに下流が決定済み | `graph.unsound_decision` |
| 誰も追っていない孤立した論点 | `graph.isolated` |
| 仮決定のまま下流に効いている | `graph.provisional_gate` |
| 取下げなのに辺が残っている | `rule.dropped_has_edge` |
| 二重決済・調理中のキャンセル・返金経路なし | `fsl.state_event_hole` / `fsl.unused_event` |
| 後から足した遷移が、前に書いた禁止経路と矛盾 | `fsl.forbidden_accepted` |
| 仕様の未決定に論点IDが無い（起票されていない） | `fsl.undecided_unlinked` |
| データ種別ごとの削除・保持方針の欠落 | `grid.row_empty` / `grid.empty` |
| 認可が方針レベルで止まっている | `grid.not_itemised` |
| 原文に無い引用（幻覚）を含む Change Set | `review` が `blocked` に分類 |
| 決定済みなのに根拠が空 | `rule.decided_without_rationale` |
| 出したまま返事が来ていない／聞き直しすぎ／決定が不安定 | `turn.no_response` / `turn.reasked` / `turn.churn` |
| リンクは効いているが表示タイトルが古い | `rule.stale_link_text` |

```bash
scripts/reqmap-cli doctor --root=examples/takeout-app   # fslc と仕様が読めているか
scripts/reqmap-cli status --root=examples/takeout-app
scripts/reqmap-cli gaps   --root=examples/takeout-app
scripts/reqmap-cli review --root=examples/takeout-app   # 7件中 blocked 1件（幻覚の引用）
scripts/reqmap-cli view   --root=examples/takeout-app
```

`examples/takeout-app/sources/20260915_定例.md` が議事録、
`_changesets/20260915-teirei.yml` が抽出結果、`models/fsl/order.fsl` が状態遷移の仕様です。

## スキル

| スキル | いつ読むか |
|---|---|
| `requirements-harness` | 要件定義フェーズ全般 |
| `coverage-grids` | 網羅グリッドや、FSL の reqmap 向け指令（`@critical` など）を作る・直す・調整するとき |
| `fsl-requirements`（fslc 同梱） | FSL 仕様そのものを書く・直すとき |

## 開発

```bash
python3 -m unittest discover -s tests
```

上の「仕込んだ欠陥 → 検出されるチェック」の表は、そのまま回帰テスト
（`tests/test_example_vault.py`）です。fslc が無い環境では fslc 由来のテストは skip されます。
