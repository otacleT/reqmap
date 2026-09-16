---
id: data.retention-period
# ID は slug。「<領域の語>.<何を決めるか>」。ファイル名と一致させる。
# **slug が付けられないなら論点が同居している。** 分割の合図として使える。
# 採番しないので並行起票でぶつからず、分割しても親子が読める。
title: ここに問いを1つだけ書く
kind: question          # question | decision | constraint | assumption | area
status: open            # open | investigating | provisional | decided | dropped
area: A-01
owner: クライアント
severity: medium        # high | medium | low
due:                    # 個別の期限。空ならマイルストーンから逆算される
lead_time_days: 0       # 決まってから着手までに要る日数（環境準備・翻訳・書面承認など）
ledger:                 # 相手側の番号（QA表の #12 など）。**ID には混ぜない**
aliases: []             # 旧ID。リネームしても [[リンク]] が壊れない

# 網羅グリッドのマスと結び付ける。ページを増やさず、結合だけ持つ。
cells: []

# blocks 以外の依存。上流（これが先）を書く。
constrains: []          # 決まると自分の選択肢が狭まる
derives: []             # 決まれば自分は機械的に従属する
conflicts: []           # 両立しない

# やりとりの記録。**追記しかしない。** 1行1イベント。
#   種別: asked / answered / decided / provisional / reopened / split / dropped
#         / prereq_changed / note
# ここに書くと、回答日数が仮置きから**実測**に変わり、催促どき・聞き直しの回数・
# 決定がひっくり返った回数が機械で出ます。散文で本文に書いても機械は読めません。
log: []
# 例:
#   - 2026-09-10 asked | 定例で確認依頼
#   - 2026-09-24 answered | 保持期間は5年と回答
#   - 2026-09-24 decided

# kind: assumption のときだけ使う。**expires のない仮置きは誰も見直さない。**
# assumption:
#   text: 決済はStripeが使える前提で設計している
#   expires: 2026-10-01
#   validate_by: クライアント経理部門に加盟店審査の可否を確認
#   impact: high

# ↓ ここから下は reqmap recalc が書きます。手で触らないでください。
blocks_count: 0
blocking: なし
impact_count: 0
ready: true
depth: 0
need_by:
ask_by:
---

## 前提

<!-- これが先に決まらないと、この論点は決められない、というものを [[リンク]] で書く。
     **リンクはこの見出しの中だけ。** 外に書くと依存として数えられません。
     2本を超えたら、たぶん論点が同居しています。分割したほうが早く進みます。 -->

## 論点

<!-- 何が争点で、何が判断材料か。1ページ1論点。 -->

## 自社案

## 決まったこと

<!-- 決まったら status を decided にして、ここに結論と根拠を書く。
     **機械はこの欄に触りません。** 決定は人が下します。 -->
