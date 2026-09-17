# reqmap の使い方

**やること順**に書いています。コマンドの一覧は最後にあります。

---

## 0. 入れる

```bash
/plugin marketplace add /path/to/reqmap
/plugin install reqmap@reqmap-local
```

開発中は `claude --plugin-dir /path/to/reqmap` でも試せます。
CLI 単体でも動きます（**外部依存なし**。PyYAML も不要）。

状態遷移の検証には [fslc](https://github.com/ymm-oss/fsl) を使います。無くても動きますが、
その検査だけ省略されます（`fsl.tool_missing` が出ます）。

```bash
git clone https://github.com/ymm-oss/fsl ~/.fsl && bash ~/.fsl/install.sh
```

---

## 1. 立ち上げ — 案件につき1回、1〜2時間

**ここが一番大事です。** 観点の質は、このとき引いたグリッドとFSLの質で決まります。
ツールは掛け算をして穴を数えるだけで、何を掛けるかは人が決めます。

### 1-1. 雛形を作る

```
/reqmap-init ./myproject
```

対話で `reqmap.yml` を埋めます。決めるのは3つだけ。

- **マイルストーン** — いつまでに要件を固めるか。すべての逆算の起点
- **領域** — 5〜12個。**リスクを全部 high にすると優先度が意味を失います**
- **回答日数** — 相手に聞いてから返ってくるまでの日数。仮置きで構いません（後で実測に変わります）

### 1-2. グリッドの行を引く ← ここに時間を使う

同梱の4枚は**列が汎用**なので、**行だけ**案件に合わせます。

| グリッド | 行に何を書くか |
|---|---|
| `errors` | この案件の主要な操作（送信・アップロード・決済・外部API呼び出し…） |
| `lifecycle` | この案件のデータ種別（ユーザー情報・画像・同意記録・ログ…） |
| `authz` | ロール（未ログイン・本人・他人・運用者・外部連携先） |
| `i18n` | 多言語対象（画面文言・通知本文・規約…） |

行は受領資料の**機能一覧・画面一覧・テーブル一覧**から抽出できます。私（Claude）に
資料を読ませて下書きさせるのが早いですが、**必ずレビューしてください。**

> **語は案件の資料に実際に出てくる語を使うこと。**
> 「たぶんこう呼ぶだろう」で書かないでください。第3フィールドの語が実体と
> ズレると、既にある論点を「真の空白」として出してしまいます。

領域を横断する観点（国モデル差分・異常系など）は **`area:` を指定しない**こと。
指定すると他領域の既存論点が候補から外れます。

### 1-3. FSL を1〜3本書く

業務の主フロー（注文・予約・申込）と、非同期処理の待ち受けあたりが効きます。
**画面遷移を全部FSLにすると書くコストで死にます。**

FSL は [fslc](https://github.com/ymm-oss/fsl) の `requirements` 方言で書きます。
**reqmap が問い、fslc が検証する**、という分担です。

```fsl
// @area: A-04
// @events: refund           // まだ遷移が無いイベントも網羅の対象にする
// @critical: cancel         // キャンセルは全状態で問う（揉めるところ）
// @impossible: Draft x pay  // 未送信の注文に決済は発生しない

requirements OrderStatus {
  process Order {
    stages Draft, PendingPayment, Paid, Cancelled
    initial Draft
    transition submit Draft          -> PendingPayment by Customer covers REQ-ORDER-001 "注文を送信する"
    transition pay    PendingPayment -> Paid           by Customer covers REQ-ORDER-002 "支払いで確定する"
  }
  forbidden FB-ORDER-001 "送信済み注文の再送信は拒否される" {
    submit(0) submit(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Paid or stage(c) == Cancelled } }
}
verify { instances Order = 2 }
```

雛形は `models/fsl/order.fsl` に入っています。書き方は fslc 同梱の `fsl-requirements` スキルに
任せてください（私が下書きします）。**レビューは飛ばせません。**
間違ったFSLは自信たっぷりに間違った観点を出します。

**決まったことは仕様に写します。** 「二重決済は拒否」と決まったら `forbidden` に、
「調理中もキャンセル可」と決まったら遷移に。写しておくと、後から矛盾する決定が入ったときに
fslc が `fsl.forbidden_accepted` として検出します。まだ決まっていない箇所は
`@undecided("Q-006 返金条件は決定待ち")` と**論点IDを先頭に**書いておけば、
その論点が決まったのに仕様が古いままのとき `fsl.stale_undecided` が出ます。

### 1-4. 点検して回す

```
/reqmap-doctor
/reqmap-gaps
```

`doctor` の ⚠ を直してから `gaps` を見ます。**1周10分**で回せるので、
出てきた観点を見て「この行いらない」「この行が抜けてる」を直すのが早いです。
最初から完璧を狙わないでください。

追いかけると決めた観点は、`reqmap gaps --file <観点ID>` で論点ページにします。
open のまま作られ、`cells:` で紐付くので穴から消えます。owner と前提は人が書き足します。

---

## 2. 毎日 — 2分

```
/reqmap-changes    決定が書き換わっていないか
/reqmap-status     動くものがあるか
```

どちらも**何も書きません。** `changes` を見終わったら `reqmap changes --ack` で
基準を進めます（これだけが書き込み。`.reqmap/` の自分の基準にだけ書きます）。

`status` が出すもの:

- **いま聞けて、いちばん効くもの**（まだ出していないもの）
- **出したまま返事が来ていない**もの ← 催促どき
- **前提が崩れかけているもの**（期限切れの仮置き・根拠なき決定・ひっくり返り続けている決定）
- 期限超過 / 規約違反 / 承認待ちの提案 / 前回から新しく出た観点

**静かな日は「動くものはありません。」の1行で終わります。** それが正常です。

---

## 3. 定例の前 — 30分

```
/reqmap-gaps
```

`severity: high` と、止めている件数の多いものから **3件だけ**選びます。
全部を並べないでください。**100件の観点より「今週決めないと止まる3件」です。**

選んだ3件は `reqmap show <id>` で前提・下流・日付・やりとりを確かめてから質問文にします。
私に頼めば、機械が組んだ文を相手に出せる日本語にします。組み立て方は決まっています。

> いま決まっていないこと → 決まらないと何が止まるか → 選択肢 → いつまでに欲しいか

毎朝同じ40件を見せられると読まなくなるので、2回目以降は `gaps --new` を使ってください。

---

## 4. 定例の後 — 15分

### 4-1. 議事録を取り込む

```
/reqmap-extract ./議事録/20260916_定例.md
```

サブエージェントが `_changesets/` に提案を書きます。**`questions/` には直接書きません。**

1件ごとに**原文からの逐語引用**を持たせ、**機械が原文と照合します。**
原文に無い引用は `blocked` になり、決して適用されません。

```
[auto   ] data.deletion-grace-period  削除依頼から実際の削除までの猶予期間
[human  ] ops.withdrawal-screen       退会画面を設けず問い合わせ経由で受け付ける
           - 新規なのに status が decided（未決以外は人が判断する）
[blocked] payment.refund-api-difference
           - 引用が原文に見つからない
```

- `auto` → そのまま反映
- `human` → 1件ずつ確認してから `reqmap apply --approve=<id>`
- `blocked` → **モデルが原文に無いことを書いた合図。** 原文を確認してください

### 4-2. 決まったことを書く

`status` を `decided` にして `## 決まったこと` に**結論と根拠**を書きます。
空のままにすると `rule.decided_without_rationale` が出ます。
**根拠のない決定は3か月後に必ず蒸し返されます。**

状態遷移に関わる決定なら `models/fsl/*.fsl` にも写します（遷移・`forbidden`・`when`）。
写さないと、その決定はいつまでも自由文のままで、後から来る矛盾は誰にも見えません。
写し忘れは `fsl.spec_behind_decision` が拾います（`log:` の `decided` 日付より仕様が古いとき）。

### 4-3. やりとりを記録する

```yaml
log:
  - 2026-09-10 asked | 定例で確認依頼
  - 2026-09-24 answered | 保持期間は1.5年
  - 2026-09-24 decided
```

**追記だけ。** これを書くと回答日数が仮置きから実測になり、催促どき・聞き直しの回数・
決定がひっくり返った回数が出るようになります。

### 4-4. 反映する

```
/reqmap-recalc
/reqmap-view            # 関係者に見せるとき
reqmap gaps --snapshot  # 観点を「ここまで見た」と記録する（定例前に1回）
reqmap changes --ack    # 決定を「ここまで見た」と記録する（毎朝 changes を見たあと）
```

基準は2つあり、進むタイミングが違います。1つにすると片方の差分が黙って消えます。

---

## 5. 設計フェーズ

**設計ハーネスはありません。** 設計は各メンバーがそれぞれAIエージェントと進める前提です。

各自が毎朝 `/reqmap-changes` を見て、**自分の設計に効くかを自分で判断します。**
見終わったら `reqmap changes --ack`。設計側に記帳は要りません。

`.reqmap/` は**各自のもの**です（`.gitignore` 済み）。「前回自分が見たとき」の基準が
入るので、コミットすると他人の基準で上書きされます。

設計中に「これ決まってない」に遭遇したら、要件側に論点を足してください。
Change Set を書いてもいいし、手で `questions/` にファイルを作っても構いません。

`reqmap ci` を CI に入れると、決定どうしの矛盾（`fsl.forbidden_accepted`・`graph.conflict`）と
読めない仕様で PR が止まります。観点の多さでは止めません。

---

## 6. 詰まったとき

| 症状 | 見るところ |
|---|---|
| 観点が出すぎる | 行・列の粒度が細かすぎる。統合する |
| 観点が何も出ない | `doctor`。行・列が案件の実体と合っていない |
| 既存の論点と重複する | 第3フィールドの語が足りない。題名に出る語を足す |
| 全部 high で読めない | `reqmap.yml` の `areas` のリスクを見直す |
| 毎朝同じものが出る | `gaps --snapshot` してから `gaps --new` |
| 抽出が blocked だらけ | 原文が読めていない。PDFならテキスト化してから |
| 抽出が human だらけ | 引用が短いか汎用的。出所が特定できる一文を引く（`quote_min_chars`） |
| `fsl.spec_error` が出る | 仕様が fslc で読めていない。`doctor` の行番号を見て直す |
| `fsl.forbidden_accepted` が出る | 後から足した遷移が前の決定と矛盾している。**どちらが正しいかは人が決める** |
| `fsl.tool_missing` が出る | fslc が入っていない。0 章のインストールを |
| `fsl.thin_spec` が出る | forbidden も acceptance も無い。拒否すると決めたマスを forbidden に写す |
| `fsl.spec_behind_decision` が出る | 決定のほうが仕様より新しい。仕様に写すか、写し済みなら保存・コミット |

グリッドと FSL の reqmap 向け指令を触るときは `coverage-grids` スキル、
FSL 仕様そのものは fslc 同梱の `fsl-requirements` スキルを読んでください。

---

## 7. コマンド早見表

### スラッシュコマンド（Claude 経由）

| | |
|---|---|
| `/reqmap-init` | 立ち上げ。設定を対話で埋める |
| `/reqmap-doctor` | ちゃんと読めているかの点検 |
| `/reqmap-changes` | 書き換わった決定 |
| `/reqmap-status` | 動くものがあるか |
| `/reqmap-gaps` | 確認観点。3件に絞って質問文にしてくれる |
| `/reqmap-show <id>` | 1論点の全部。質問文の材料 |
| `/reqmap-extract <議事録>` | 議事録→論点（引用の原文照合つき） |
| `/reqmap-recalc` | 影響度と期日の再計算 |
| `/reqmap-view` | HTML |

### CLI（直接叩く）

| | 書き込み |
|---|---|
| `reqmap init <dir>` | あり |
| `reqmap doctor` | なし |
| `reqmap changes` | なし |
| `reqmap changes --ack` | 自分の基準のみ（`.reqmap/`） |
| `reqmap status` | なし |
| `reqmap gaps [--new] [--snapshot]` | `--snapshot` のみ |
| `reqmap gaps --file <観点ID,...>` | あり（open な論点ページを作るだけ） |
| `reqmap show <id>` | なし |
| `reqmap ci` | なし（exit 1 で止めるだけ） |
| `reqmap recalc [--check]` | `--check` 以外はあり（計算済み7キーだけ） |
| `reqmap review` | なし |
| `reqmap apply [--approve=<id>]` | あり |
| `reqmap view` / `reqmap json` | 出力先のみ |

**`status` `decision` `severity` には機械が触りません。** 決定は人が下します。
