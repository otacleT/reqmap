# -*- coding: utf-8 -*-
"""依存グラフ・影響度・逆算スケジュール。**外部依存なし。**

依存は4種類。**上流を指す**（「これが先」）。
  blocks      本文の `## 前提`。決まらないと着手できない
  derives     決まれば機械的に従属する（聞くものではなく、書き取るもの）
  constrains  決定が選択肢を狭める（止めはしないが、変えると再検討が要る）
  conflicts   両立しない（gaps.graph_checks が矛盾として出す。辺にはしない）

影響度は2本立てにする。1本だと「変更時の波及」が見えない。
  blocks_count  いま何件を**止めている**か           … 決める順番を決める
  impact_count  変えたら何件の**再検討が要る**か     … 仕様変更が来たときに効く
"""
import datetime as _dt

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
    """blocks / derives の循環。人に見せる用に、見つけた経路を返す。"""
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


def scc_cycle_nodes(edges, kinds=("blocks", "derives")):
    """循環に乗っている節の集合（Tarjan の強連結成分。大きさ2以上か自己ループ）。

    cycles() が返す経路の和では足りない。DFS の back-edge から見つかる経路には、
    交差辺だけで循環に参加している節が出てこないことがある。
    ここで拾った節だけを初期値に落とし、**他の論点の計算は巻き込まない。**"""
    index, low, stack, on, out, counter = {}, {}, [], set(), set(), [0]

    def adj(u):
        return [v for v, k in edges.get(u, []) if k in kinds]

    def strong(u):
        index[u] = low[u] = counter[0]
        counter[0] += 1
        stack.append(u)
        on.add(u)
        for v in adj(u):
            if v not in index:
                strong(v)
                low[u] = min(low[u], low[v])
            elif v in on:
                low[u] = min(low[u], index[v])
        if low[u] == index[u]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == u:
                    break
            if len(comp) > 1 or u in adj(u):
                out.update(comp)

    for n in edges:
        if n not in index:
            strong(n)
    return out


def analyse(proj):
    """影響度・深さ・着手可否・逆算日付を計算する。ファイルには書かない。"""
    edges, dangling = build(proj)
    items = proj.items
    cyc = scc_cycle_nodes(edges)
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

    # 深さ（前提の連なり）と着手可否。循環に乗っている節だけ 0 に落とす。
    memo_d = {}

    def depth(i):
        if i in cyc:
            return 0
        if i not in memo_d:
            ups = [u for u, k in up_of[i] if k in ("blocks", "derives") and not settled(u)]
            memo_d[i] = 0 if not ups else 1 + max(depth(u) for u in ups)
        return memo_d[i]

    for iid in items:
        ups = [u for u, k in up_of[iid] if k in ("blocks", "derives")]
        res[iid]["depth"] = depth(iid)
        res[iid]["ready"] = all(settled(u) for u in ups)
        res[iid]["waiting_on"] = sorted(u for u in ups if not settled(u))
        # derives の上流を持つ論点は「聞く」ものではなく「書き取る」もの
        res[iid]["derived"] = any(k == "derives" for _, k in up_of[iid])

    # 逆算スケジュール: 上流 i は、下流 v を**出す日**（need_by(v) − v の応答日数）より
    # 自分の lead_time だけ前に決まっていなければならない。
    # 引くのは**下流**の応答日数。上流自身の日数を引くと、上下で日数が違うとき
    # 上流の期限が「下流を出す日」より後ろにずれて、下流が間に合わなくなる。
    ms = model.as_date(proj.cfg.get("milestone"))
    memo_n = {}

    def need_by(i):
        own = model.as_date(items[i]["due"]) or ms
        if i in cyc:
            return own
        if i in memo_n:
            return memo_n[i]
        cands = [own] if own else []
        for v, k in edges.get(i, []):
            if k == "conflicts" or settled(v):
                continue
            nb = need_by(v)
            if nb:
                cands.append(nb - _dt.timedelta(
                    days=turns.resp_days(proj, items[v])[0] + items[i]["lead_time_days"]))
        memo_n[i] = min(cands) if cands else None
        return memo_n[i]

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
            "cycles": cycles(edges), "cycle_nodes": sorted(cyc), "result": res}
