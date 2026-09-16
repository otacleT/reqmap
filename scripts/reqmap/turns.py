# -*- coding: utf-8 -*-
"""やりとりの型付き履歴。**外部依存なし。**

■ なぜ要るか

これまで論点ページは「いまの状態」しか持っていなかった。`status: open → decided` の
**遷移がどう起きたかの履歴が無い**。その結果こうなる。

  - 「質問を出してから回答が返るまでの日数」が**永久に仮置きのまま**。
    実測できるデータ（出した日・返ってきた日）はあるのに、どこにも記録されていない
  - 「この論点は何回聞き直したか」が分からない。3回聞き直しているなら、
    相手が悪いのではなく**問いの立て方が悪い**可能性が高い
  - 「決定が何回ひっくり返ったか」が分からない。2回 reopened した決定は、
    3回目も高い確率でひっくり返る
  - 「いま回答待ちなのはどれか、いつから待っているか」が人の頭の中にしかない

Codex の App Server が thread / turn / item という3層を置き、item を**型付き**にして
ライフサイクルを持たせているのと同じ発想を持ち込む。
論点が thread、1回の確認の往復が turn、その中の出来事が item にあたる。

■ 書き方

frontmatter に1行1イベントで積む。**追記しかしない。** 書き換えない。

    log:
      - 2026-09-10 asked | 定例で確認依頼
      - 2026-09-24 answered | 保持期間は5年と回答
      - 2026-09-24 decided
      - 2026-10-02 reopened | 法務から再検討の指示

種別は下の KINDS だけ。散文で「⚠ 前提を差し替えた（2026-09-13）」と本文に書いても
機械は読めない。**型を付けて初めて数えられる。**
"""
import datetime
import re

from . import model

KINDS = ("asked", "answered", "decided", "provisional", "reopened",
         "split", "dropped", "prereq_changed", "note")
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\w+)\s*(?:\|\s*(.*))?$")


def parse(raw):
    """log: の各行を {date, kind, note} に。読めない行は kind=None で返し、捨てない。

    捨てると「記録が無い」と「書式を間違えた」の区別がつかなくなる。"""
    out = []
    for r in raw or []:
        m = LINE.match(str(r).strip())
        if not m:
            out.append({"date": None, "kind": None, "note": str(r).strip()})
            continue
        out.append({"date": model.as_date(m.group(1)), "kind": m.group(2),
                    "note": (m.group(3) or "").strip()})
    return out


def metrics(it):
    """1論点のやりとり指標。"""
    log = [e for e in it["log"] if e["kind"] in KINDS and e["date"]]
    log.sort(key=lambda e: e["date"])
    asked = [e for e in log if e["kind"] == "asked"]
    answered = [e for e in log if e["kind"] == "answered"]
    reopened = [e for e in log if e["kind"] == "reopened"]

    # 出した→返ってきた の対応を時系列で取る。**返ってこないまま次を出した分は待ち扱い。**
    pairs, pending, ai = [], None, 0
    for e in log:
        if e["kind"] == "asked":
            pending = e["date"]
        elif e["kind"] == "answered" and pending:
            pairs.append((e["date"] - pending).days)
            pending = None
    return {
        "ask_count": len(asked),
        "answer_count": len(answered),
        "reopen_count": len(reopened),
        "round_trips": pairs,
        "measured_days": round(sum(pairs) / len(pairs)) if pairs else None,
        "waiting_since": pending,
        "waiting_days": (model.today() - pending).days if pending else None,
        "malformed": [e["note"] for e in it["log"] if e["kind"] is None],
        "last": log[-1] if log else None,
    }


def resp_days(proj, it):
    """回答日数。**実測があれば実測を使い、無ければ設定の仮置きに落ちる。**

    仮置きのままでも動くが、実測が溜まるほど逆算の精度が上がる。"""
    m = metrics(it)
    if m["measured_days"] is not None:
        return m["measured_days"], "実測"
    return proj.resp_days(it), "仮置き"


def check(proj):
    """やりとり由来の findings。gaps._f と同じ形。"""
    from .gaps import _f
    f = []
    for iid, it in proj.items.items():
        if model.is_aggregator(it):
            continue
        m = metrics(it)
        for bad in m["malformed"]:
            f.append(_f("log.malformed", "low", {"item": iid, "line": bad[:40]},
                        "%s の log に読めない行があります（%s）。"
                        "`YYYY-MM-DD 種別 | メモ` の形で書いてください。" % (iid, bad[:30]),
                        kind="rule"))
        if it["status"] in model.SETTLED:
            continue
        # 回答待ちが想定日数を超えている＝催促どき。
        # 「出した日」は記録されているのに誰も数えていない、が一番よくある取りこぼし。
        if m["waiting_days"] is not None:
            base = proj.resp_days(it)
            if m["measured_days"] is not None:
                base = max(base, m["measured_days"])
            if base and m["waiting_days"] > base * 1.5:
                f.append(_f("turn.no_response", "high",
                            {"item": iid, "days": m["waiting_days"], "expected": base},
                            "『%s』は %s に出してから %d 日、回答がありません"
                            "（想定 %d 日）。催促するか、聞き方を変えるかの判断どきです。"
                            % (it["title"], m["waiting_since"].isoformat(),
                               m["waiting_days"], base), kind="waiting"))
        # 何度も聞き直している＝相手ではなく問いの立て方の問題であることが多い
        if m["ask_count"] >= 3:
            f.append(_f("turn.reasked", "medium",
                        {"item": iid, "count": m["ask_count"]},
                        "『%s』は %d 回聞き直しています。**相手の問題ではなく、"
                        "問いの立て方の問題**である可能性が高いです。分割するか、"
                        "選択肢を用意して聞き直してください。" % (it["title"], m["ask_count"]),
                        kind="churn"))
        if m["reopen_count"] >= 2:
            f.append(_f("turn.churn", "high",
                        {"item": iid, "count": m["reopen_count"]},
                        "『%s』は %d 回ひっくり返っています。**3回目も高い確率で"
                        "ひっくり返ります。** 前提が足りていないか、決める人が違います。"
                        % (it["title"], m["reopen_count"]), kind="churn"))
    return f


def summary(proj):
    """実測がどれだけ溜まっているか。doctor と status で使う。"""
    tot = [metrics(it) for it in proj.items.values() if not model.is_aggregator(it)]
    rts = [d for m in tot for d in m["round_trips"]]
    waiting = [m for m in tot if m["waiting_days"] is not None]
    return {"with_log": sum(1 for m in tot if m["ask_count"] or m["answer_count"]),
            "total": len(tot), "round_trips": len(rts),
            "median_days": sorted(rts)[len(rts) // 2] if rts else None,
            "waiting": len(waiting),
            "longest_wait": max((m["waiting_days"] for m in waiting), default=None)}
