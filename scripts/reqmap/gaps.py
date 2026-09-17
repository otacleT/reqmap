# -*- coding: utf-8 -*-
"""確認観点の生成と規約チェック。**外部依存なし。LLMを使わない。**

■ 立場

観点を出すのは**決定論的なチェッカ**。LLM の仕事は2つだけ。
  1. 自然言語（議事録など）を論点ページに落とす
  2. ここが出した `question` を、相手に出せる日本語に整える
この分担を崩すと、幻覚まじりの観点リストになって一度で信用を失う。

■ 出しすぎないための3段階

  真の空白    候補の論点すら無い   → **全部出す。これが新しい観点**
  候補あり    題名の近い論点がある → 件数だけ。cells: を書けば消える
  紐付け済み  cells: が書いてある  → 件数だけ

  候補は**推定**。機械は一切書かない。書くのは人（またはチャットでの合意）。
"""
import datetime
import glob
import hashlib
import json
import os
import re

from . import fm, fsl, graph, model
from .model import ACTIVE, DECIDED, DROPPED, PROVISIONAL, SETTLED, _split3

SEV = {"high": 0, "medium": 1, "low": 2}


class Finding(dict):
    pass


def _f(check, severity, target, question, blocks=(), kind="coverage_hole"):
    return Finding(check=check, kind=kind, severity=severity, target=target,
                   question=question, blocks=sorted(blocks), status="new")


# ── モデルの読み込み ────────────────────────────────────────
def load_grids(proj):
    out = []
    for p in sorted(glob.glob(os.path.join(proj.root, proj.cfg["models_dir"], "grids", "*.yml"))):
        d = fm.parse(open(p, encoding="utf-8").read())
        g = {"id": d.get("id") or os.path.splitext(os.path.basename(p))[0],
             "title": d.get("title") or "", "area": d.get("area") or "",
             "rows": [_split3(x) for x in (d.get("rows") or [])],
             "cols": [_split3(x) for x in (d.get("cols") or [])],
             "skip": {}, "file": os.path.relpath(p, proj.root)}
        for s in d.get("skip") or []:
            left, _, reason = str(s).partition("|")
            a, _, b = left.partition(" x ")
            g["skip"][(a.strip(), b.strip())] = reason.strip() or "（理由なし）"
        out.append(g)
    return out


# ── グリッド ────────────────────────────────────────────────
def _cands(rwords, cwords, items, area):
    """題名に行・列の語が両方出る論点。**推定であって根拠ではない。**

    語は人がグリッドに書く（機械に分かち書きをさせない）。書かなければ候補は出ず、
    そのマスは「真の空白」に落ちる。**安全側に倒すのは意図**で、
    見落としより余分な確認のほうが安い。"""
    if not rwords or not cwords:
        return []
    return [it for it in items
            if (not area or it["area"] == area) and it["status"] != DROPPED
            and any(w in it["title"] for w in rwords)
            and any(w in it["title"] for w in cwords)]


def _row_ctx(rwords, items, area):
    if not rwords:
        return []
    return [it for it in items
            if (not area or it["area"] == area) and it["status"] != DROPPED
            and any(w in it["title"] for w in rwords)]


def claimed_by(proj):
    """cells: で紐付いたマス → 論点ID。**取下げページの分は数えない**（数えると穴が永久に消える）。"""
    out = {}
    for iid, it in sorted(proj.items.items()):
        if it["status"] != DROPPED:
            for c in it["cells"]:
                out.setdefault(str(c).strip(), iid)
    return out


def claimed_cells(proj):
    return set(claimed_by(proj))


def grid_gaps(proj, grids):
    findings, summary = [], []
    claimed = claimed_cells(proj)
    items = list(proj.items.values())
    for g in grids:
        linked, near, empty, linked_cells = [], [], [], []
        for rid, rlabel, rw in g["rows"]:
            for cid, clabel, cw in g["cols"]:
                if (rid, cid) in g["skip"]:
                    continue
                key = "%s:%s x %s" % (g["id"], rid, cid)
                if key in claimed:
                    linked.append(key)
                    linked_cells.append((rid, cid))
                    continue
                cand = _cands(rw, cw, items, g["area"])
                (near if cand else empty).append((rid, cid, rlabel, clabel, rw, cand))
        total = len(linked) + len(near) + len(empty)
        summary.append({"grid": g["id"], "title": g["title"] or g["id"], "total": total,
                        "empty": len(empty), "near": len(near), "linked": len(linked),
                        "skip": len(g["skip"]),
                        "whole_empty": bool(empty) and not linked and not near,
                        "rows": [(r[1], r[0]) for r in g["rows"]]})
        risk = proj.area_risk(g["area"])
        sev = "high" if risk == "high" else "medium"
        if empty and not linked and not near:
            # グリッドが丸ごと空。「マスが無い」ではなく
            # **領域がまだ方針レベルで、マス単位に落ちていない**という別種の指摘。
            # 20行並べても読まれないので1件にまとめ、起票単位だけ示す。
            findings.append(_f(
                "grid.not_itemised", sev, {"grid": g["id"], "cells": len(empty)},
                "『%s』はマス単位に落ちていない（%d マス全部が空）。"
                "1マスずつ起票せず、まず行単位（%s）で1件ずつ確認する。"
                % (g["title"] or g["id"], len(empty),
                   "／".join(r[1] for r in g["rows"][:3])),
                kind="not_itemised"))
        else:
            # 行が丸ごと空なら1件にまとめる。**その行はまだ誰も触っていない**ので、
            # マスごとに聞くより「この種別の扱いを一度決める」ほうが早い。
            # 一部が埋まっている行だけ、残ったマスを個別に出す。
            # ここを分けないと、1マス紐付けた瞬間に残り全部が噴き出して読まれなくなる。
            touched = {r for r, c in linked_cells} | {e[0] for e in near}
            by_row = {}
            for rid, cid, rl, cl, rw, _ in empty:
                by_row.setdefault(rid, {"label": rl, "words": rw, "cols": []})["cols"].append(
                    (cid, cl))
            for rid, info in by_row.items():
                ctx = _row_ctx(info["words"], items, g["area"])
                hint = ("（%s はこの話題の論点ですが、この観点では立っていません）"
                        % "・".join(c["id"] for c in ctx[:3])) if ctx else ""
                if rid in touched:
                    for cid, cl in info["cols"]:
                        findings.append(_f(
                            "grid.empty", sev,
                            {"grid": g["id"], "row": rid, "col": cid,
                             "row_label": info["label"], "col_label": cl},
                            "『%s』の『%s』について方針が決まっていません。%s"
                            % (info["label"], cl, hint)))
                else:
                    findings.append(_f(
                        "grid.row_empty", sev,
                        {"grid": g["id"], "row": rid, "row_label": info["label"],
                         "cols": [c[0] for c in info["cols"]]},
                        "『%s』は %s のどれも決まっていません（%d マス）。"
                        "%s まずこの種別の扱いを一度決めるのが早いです。"
                        % (info["label"], "／".join(c[1] for c in info["cols"]),
                           len(info["cols"]), hint),
                        kind="row_empty"))
        for rid, cid, rl, cl, _, cand in near:
            findings.append(_f("grid.unlinked", "low",
                               {"grid": g["id"], "row": rid, "col": cid,
                                "candidates": [c["id"] for c in cand]},
                               "『%s x %s』は %s が該当しそうです。合っていれば cells: に "
                               "`%s:%s x %s` を書いてください（推定なので要確認）。"
                               % (rl, cl, "・".join(c["id"] for c in cand[:3]),
                                  g["id"], rid, cid),
                               kind="unlinked"))
    return findings, summary


# ── 決定グラフの規約と健全性 ─────────────────────────────────
def graph_checks(proj, an):
    f, items, res = [], proj.items, an["result"]
    t = model.today()
    for iid, ref in an["dangling"]:
        f.append(_f("graph.dangling", "medium", {"item": iid, "ref": ref},
                    "%s が参照する『%s』が見つかりません。IDの誤りか、まだ起票されていない論点ですか？"
                    % (iid, ref), kind="broken_link"))
    for cyc in an["cycles"]:
        f.append(_f("graph.cycle", "high", {"cycle": cyc},
                    "依存が循環しています: %s。どれかを先に仮決定する必要があります。"
                    % " → ".join(cyc), kind="conflict"))
    for dup_id, a, b in getattr(proj, "duplicates", []):
        f.append(_f("rule.duplicate_id", "high", {"item": dup_id, "files": [a, b]},
                    "ID %s が2つのファイルにあります（%s / %s）。"
                    "片方は読み込み時に消えるので、検査も可視化も当てになりません。"
                    % (dup_id, a, b), kind="rule"))
    for iid, it in items.items():
        stem = os.path.splitext(os.path.basename(it["file"]))[0]
        # ID とファイル名が食い違うと、[[リンク]] も検索も当たらなくなる。
        # slug 運用ではファイル名がそのまま人の入口なので、ここがずれると効きが悪い。
        if stem != iid and not stem.startswith(iid + " "):
            f.append(_f("rule.id_mismatch", "medium", {"item": iid, "file": it["file"]},
                        "%s の ID とファイル名（%s）が一致しません。"
                        "リンクも検索も当たらなくなります。" % (iid, stem), kind="rule"))
    seen_pairs = set()
    for iid, it in items.items():
        agg = model.is_aggregator(it)
        # 両立しない（conflicts）。両方決まっていれば矛盾。片方だけなら、もう片方は取下げ候補。
        # 辺にはしない（順番も影響度も変えない）。ここで見るだけ。
        for ref in it["typed"]["conflicts"]:
            other = proj.resolve(ref)
            if not other or other == iid:
                continue
            pair = tuple(sorted((iid, other)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            o = items[other]
            if DROPPED in (it["status"], o["status"]):
                continue
            a_set = it["status"] in (DECIDED, PROVISIONAL)
            b_set = o["status"] in (DECIDED, PROVISIONAL)
            if a_set and b_set:
                f.append(_f("graph.conflict", "high", {"items": list(pair)},
                            "『%s』と『%s』は両立しないと宣言されていますが、両方とも決まっています。"
                            "どちらかを取下げるか、宣言を見直してください。"
                            % (it["title"], o["title"]), list(pair), kind="conflict"))
            elif a_set or b_set:
                dec, pend = (it, o) if a_set else (o, it)
                f.append(_f("graph.conflict_pending", "low",
                            {"decided": dec["id"], "pending": pend["id"]},
                            "『%s』が決まったので、両立しない『%s』は取下げ候補です。"
                            % (dec["title"], pend["title"]), [pend["id"]], kind="conflict"))
        # 規約: 前提リンクは所定の見出しの中だけ
        if it["stray_links"]:
            f.append(_f("rule.stray_link", "low", {"item": iid, "links": it["stray_links"][:3]},
                        "%s は『## %s』の外にリンクがあります。依存として数えられません。"
                        % (iid, proj.cfg["prereq_heading"]), kind="rule"))
        # リンクは ID で解決されるので壊れないが、**表示されるタイトルが古いまま**になる。
        # 要件定義ではタイトルが頻繁に変わるので、放っておくと
        # 「ページを開かずにリンクの文字だけ読んだ人」が古い理解のまま進む。
        for raw in it["prereq_raw"]:
            rid = proj.resolve(raw)
            if not rid:
                continue
            m = re.match(proj.cfg["id_pattern"], str(raw).strip())
            shown = str(raw).strip()[len(m.group(0)):].strip() if m else ""
            cur = proj.items[rid]["title"]
            if shown and shown != cur:
                f.append(_f("rule.stale_link_text", "low",
                            {"item": iid, "ref": rid, "shown": shown, "current": cur},
                            "%s のリンク『%s』の表示が古いままです（現在は『%s』）。"
                            "リンクは効いていますが、**開かずに文字だけ読んだ人が"
                            "古い理解のまま進みます。**" % (iid, shown[:24], cur[:24]),
                            kind="rule"))
        ups, _ = proj.prereqs(it)
        mx = int(proj.cfg["max_prereqs"])
        if len(ups) > mx and not agg and it["kind"] != "area":
            f.append(_f("rule.too_many_prereqs", "low", {"item": iid, "count": len(ups)},
                        "%s の前提が %d 本あります（上限 %d）。論点が同居していないか確認してください。"
                        % (iid, len(ups), mx), kind="rule"))
        # 決定なのに根拠が書かれていない。**根拠のない決定は、決定ではなく思い込み。**
        # 3か月後に「なぜこうなったか」を誰も説明できず、同じ議論をやり直すことになる。
        if it["status"] == DECIDED and not agg:
            rationale = fm.section(it["body"], proj.cfg.get("decision_heading", "決まったこと"))
            if not re.sub(r"<!--.*?-->", "", rationale, flags=re.S).strip():
                f.append(_f("rule.decided_without_rationale", "high", {"item": iid},
                            "『%s』は決定済みですが『## %s』が空です。"
                            "**根拠のない決定は3か月後に必ず蒸し返されます。**"
                            % (it["title"], proj.cfg.get("decision_heading", "決まったこと")),
                            kind="rule"))
        if it["status"] == DROPPED:
            if ups:
                f.append(_f("rule.dropped_has_edge", "medium", {"item": iid},
                            "%s は取下げなのに前提が残っています。分割時の引き継ぎ漏れですか？" % iid,
                            kind="rule"))
            if not it["fm"].get("superseded_by") and not it["fm"].get("superseded_reason"):
                f.append(_f("rule.dropped_no_successor", "low", {"item": iid},
                            "%s は取下げですが後継（superseded_by）も理由もありません。" % iid,
                            kind="rule"))
        for up in ups:
            u = items[up]
            if u["status"] == DROPPED:
                f.append(_f("rule.prereq_dropped", "medium", {"item": iid, "upstream": up},
                            "%s の前提 %s は取下げです。永久に前提待ちになります。" % (iid, up),
                            kind="rule"))
            # 上流が未決なのに下流が決まっている＝根拠なき決定
            # 集約点は「領域が閉じたか」を表すページなので、前提が未決なのは当然。
            # ここを除かないと領域ページの数だけ誤検出が出て、本物が埋もれる。
            if not agg and it["status"] in (DECIDED, PROVISIONAL) and u["status"] in (
                    model.OPEN, model.INVESTIGATING):
                f.append(_f("graph.unsound_decision", "high",
                            {"item": iid, "upstream": up},
                            "『%s』は決まっていますが、前提の『%s』がまだ未決です。"
                            "%s の結論次第でこの決定は覆りますか？"
                            % (it["title"], u["title"], u["title"]),
                            [iid], kind="unsound_decision"))
        # 仮置き（前提）の期限切れ
        a = it["assumption"] or {}
        if a:
            exp = model.as_date(a.get("expires"))
            if not exp:
                f.append(_f("rule.assumption_no_expiry", "medium", {"item": iid},
                            "%s は仮置きですが expires がありません。"
                            "期限が無い仮置きは誰も見直しません。" % iid, kind="rule"))
            elif exp < t:
                f.append(_f("assumption.stale", "high",
                            {"item": iid, "days": (t - exp).days},
                            "仮置き『%s』の検証期限が %d 日超過しています。%s は完了しましたか？"
                            "（外れた場合の影響: %s）"
                            % (a.get("text") or it["title"], (t - exp).days,
                               a.get("validate_by") or "検証", a.get("impact") or "不明"),
                            res[iid]["downstream"], kind="stale_assumption"))
        if not agg and it["status"] == PROVISIONAL and res[iid]["blocks_count"]:
            f.append(_f("graph.provisional_gate", "medium", {"item": iid},
                        "『%s』は仮決定のまま下流 %d 件に効いています。"
                        "この状態で設計を進めてよいか、いつ確定させるかを決めてください。"
                        % (it["title"], res[iid]["blocks_count"]),
                        res[iid]["downstream"], kind="provisional"))
        # 孤立: 依存も被依存も無い未決。独立の証拠ではなく、辺の書き忘れの可能性が同じだけある。
        # 書き忘れていた場合、影響度も期限も**過小評価**されて順位表の下に沈む。
        if (it["status"] in ACTIVE and not agg and it["kind"] not in ("area", "constraint")
                and not ups and not res[iid]["blocks_count"] and not it["cells"]):
            f.append(_f("graph.isolated", "medium", {"item": iid},
                        "%s は前提も下流も書かれていません。**独立している証拠ではありません。**"
                        "辺の書き忘れなら影響度も期限も過小評価されています。" % iid,
                        kind="isolated"))
    return f


def run(proj):
    from . import turns
    an = graph.analyse(proj)
    gf, gsum = grid_gaps(proj, load_grids(proj))
    ff, fsum = fsl.gaps(proj)   # 検証は fslc、状態×イベントの穴は reqmap
    findings = graph_checks(proj, an) + gf + ff + turns.check(proj)
    findings.sort(key=lambda x: (SEV[x["severity"]], x["check"]))
    # **IDは内容から決める。** 並び順で採番すると、1件増えただけで全部のIDがずれ、
    # 「前回と同じ観点か」が判定できなくなる（＝毎朝同じ40件を見せることになる）。
    for x in findings:
        key = x["check"] + "\x1f" + json.dumps(x["target"], ensure_ascii=False,
                                                sort_keys=True)
        x["id"] = "f-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return {"analysis": an, "findings": findings,
            "grids": gsum, "fsl": fsum,
            "generated_at": model.today().isoformat()}
