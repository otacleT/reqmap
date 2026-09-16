# -*- coding: utf-8 -*-
"""依存グラフ・影響度・逆算スケジュール。**外部依存なし。**

依存は4種類。**上流を指す**（「これが先」）。
  blocks      本文の `## 前提`。決まらないと着手できない
  derives     決まれば機械的に従属する
  constrains  決定が選択肢を狭める（止めはしないが、変えると再検討が要る）
  conflicts   両立しない

影響度は2本立てにする。1本だと「変更時の波及」が見えない。
  blocks_count  いま何件を**止めている**か           … 決める順番を決める
  impact_count  変えたら何件の**再検討が要る**か     … 仕様変更が来たときに効く
"""
from . import model, turns
from .model import ACTIVE, DECIDED, DROPPED, SETTLED

RISK = {"high": 3.0, "medium": 2.0, "low": 1.0}
BUCKETS = [(20, "甚大"), (10, "大"), (4, "中"), (1, "小"), (0, "なし")]


def bucket(n):
    for lo, name in BUCKETS:
        if n >= lo:
            return name
    return "なし"


def build(proj):
    """上流id -> [(下流id, 種別)] の辺を作る。未解決参照も返す。"""
    edges = {i: [] for i in proj.items}
    dangling = []
    for iid, it in proj.items.items():
        ups, bad = proj.prereqs(it)
        for b in bad:
            dangling.append((iid, b))
        for up in ups:
            edges[up].append((iid, "blocks"))
        for kind, ids in it["typed"].items():
            for ref in ids:
                up = proj.resolve(ref)
                if up is None:
                    dangling.append((iid, ref))
                elif kind != "conflicts":
                    edges[up].append((iid, kind))
    return edges, dangling


def _closure(edges, start, kinds):
    seen, stack = set(), [start]
    while stack:
        for nxt, k in edges.get(stack.pop(), []):
            if k in kinds and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def cycles(edges):
    """blocks の循環。見つけた経路を返す。"""
    color, found = {}, []

    def dfs(u, path):
        color[u] = 1
        for v, k in edges.get(u, []):
            if k not in ("blocks", "derives"):
                continue
            if color.get(v) == 1:
                found.append(path[path.index(v):] + [v] if v in path else [u, v])
            elif color.get(v, 0) == 0:
                dfs(v, path + [v])
        color[u] = 2

    for n in edges:
        if color.get(n, 0) == 0:
            dfs(n, [n])
    return found


def analyse(proj):
    """影響度・深さ・着手可否・逆算日付を計算する。ファイルには書かない。"""
    edges, dangling = build(proj)
    items = proj.items
    has_cycle = bool(cycles(edges))
    up_of = {i: [] for i in items}
    for u, outs in edges.items():
        for v, k in outs:
            up_of[v].append((u, k))

    def settled(i):
        return items[i]["status"] in SETTLED

    res = {}
    for iid in items:
        blocked = {x for x in _closure(edges, iid, ("blocks", "derives")) if not settled(x)}
        impact = {x for x in _closure(edges, iid, ("blocks", "derives", "constrains"))
                  if not settled(x)}
        res[iid] = {"blocks_count": len(blocked), "blocking": bucket(len(blocked)),
                    "impact_count": len(impact), "downstream": sorted(blocked)}

    # 深さ（前提の連なり）と着手可否
    def depth(i, guard=()):
        if i in guard or has_cycle:
            return 0
        ups = [u for u, k in up_of[i] if k in ("blocks", "derives") and not settled(u)]
        return 0 if not ups else 1 + max(depth(u, guard + (i,)) for u in ups)

    for iid in items:
        ups = [u for u, k in up_of[iid] if k in ("blocks", "derives")]
        res[iid]["depth"] = depth(iid)
        res[iid]["ready"] = all(settled(u) for u in ups)
        res[iid]["waiting_on"] = sorted(u for u in ups if not settled(u))

    # 逆算スケジュール: 下流より先に答えが要る
    ms = model.as_date(proj.cfg.get("milestone"))

    def need_by(i, guard=()):
        if i in guard or has_cycle:
            return ms
        own = model.as_date(items[i]["due"]) or ms
        cands = [own] if own else []
        for v, k in edges.get(i, []):
            if k == "conflicts" or settled(v):
                continue
            nb = need_by(v, guard + (i,))
            if nb:
                cands.append(nb - __import__("datetime").timedelta(
                    days=turns.resp_days(proj, items[i])[0]
                         + items[i]["lead_time_days"]))
        return min(cands) if cands else None

    import datetime as _dt
    for iid, it in items.items():
        nb = need_by(iid)
        res[iid]["need_by"] = nb.isoformat() if nb else ""
        rd, src = turns.resp_days(proj, it)
        res[iid]["resp_days"] = rd
        res[iid]["resp_source"] = src
        res[iid]["ask_by"] = ((nb - _dt.timedelta(days=rd)).isoformat() if nb else "")

    # 優先度: 止めている数 × リスク × 期限の逼迫
    t = model.today()
    for iid, it in items.items():
        r = res[iid]
        if it["status"] in SETTLED:
            r["priority"] = 0.0
            continue
        d = model.as_date(r["ask_by"])
        urg = 1.0 if not d else (3.0 if (d - t).days < 0 else
                                 2.0 if (d - t).days <= 7 else
                                 1.5 if (d - t).days <= 21 else 1.0)
        sev = RISK.get(it["severity"], RISK.get(proj.area_risk(it["area"]), 2.0))
        r["priority"] = round((1 + r["blocks_count"] + 0.25 * r["impact_count"]) * sev * urg, 1)
    return {"edges": edges, "up_of": up_of, "dangling": dangling,
            "cycles": cycles(edges), "result": res}
