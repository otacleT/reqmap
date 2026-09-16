# -*- coding: utf-8 -*-
"""決定の指紋と、前回から書き換わった決定。**外部依存なし。**

■ なぜ設計ノート側の記帳をやめたか

以前は設計ドキュメントに `derives_from: [<決定ID> @ <指紋>]` を書かせ、
指紋が合わなくなったら「その設計は古い」と出していた。**これは定着しない。**

書くのは設計する人で、得をするのは後から変更を追う人。
**書く人に見返りが無いものは書かれない。** トレーサビリティの仕組みが
根付かない理由はだいたいこれで、設計を各自がAIと分散してやるなら全員に
守らせることになるので、なおさら成立しない。

■ 代わりに何を出すか

分散して設計しているとき本当に困るのは「どの設計書が古いか」ではなく、
**決定が変わったことに誰も気づかない**こと。先週見た決定が今週書き換わっていても、
本人は知らないまま設計を進める。

だから要件側だけで完結させる。**「前回あなたが見たときから書き換わった決定」**を出し、
自分の設計に効くかは各自が判断する。設計側の記帳はゼロ。

■ 指紋の取り方

status と「決まったこと」の本文から取る。**決定日ではなく中身から取るのが要点**で、
「決定日はそのままで結論だけ直す」は実務で普通に起きる。日付で見ていると黙って見逃す。
"""
import hashlib
import re

from . import fm, model

# 人が設計の土台にするのはこの2つ。open/investigating はまだ土台にならない。
TRACKED = (model.DECIDED, model.PROVISIONAL)


def _norm(s):
    s = re.sub(r"<!--.*?-->", "", str(s), flags=re.S)
    s = re.sub(r"[\s　]+", "", s)
    return s.replace("・", "").replace("-", "").replace("*", "")


def fingerprint(proj, it):
    """決定の「何が決まったか」の指紋。"""
    body = fm.section(it["body"], proj.cfg.get("decision_heading", "決まったこと"))
    return hashlib.sha1(("\x1f".join([it["status"], _norm(body)]))
                        .encode("utf-8")).hexdigest()[:8]


def snapshot(proj):
    """いま決まっている／仮決定のものの指紋。"""
    return {i: fingerprint(proj, it) for i, it in proj.items.items()
            if it["status"] in TRACKED and not model.is_aggregator(it)
            and it["kind"] not in ("area",)}


def changed(proj, prev):
    """前回の指紋と比べる。(書き換わった, 新しく決まった, 取り下げられた)。"""
    now = snapshot(proj)
    if not prev:
        return [], [], []
    rewritten, added, gone = [], [], []
    for i, h in now.items():
        if i not in prev:
            added.append({"id": i, "title": proj.items[i]["title"],
                          "status": proj.items[i]["raw_status"]})
        elif prev[i] != h:
            rewritten.append({"id": i, "title": proj.items[i]["title"],
                              "status": proj.items[i]["raw_status"],
                              "was": prev[i], "now": h})
    for i in prev:
        if i not in now:
            it = proj.items.get(i)
            gone.append({"id": i, "title": it["title"] if it else "(削除)",
                         "status": it["raw_status"] if it else "—"})
    key = lambda x: x["id"]
    return sorted(rewritten, key=key), sorted(added, key=key), sorted(gone, key=key)
