# -*- coding: utf-8 -*-
"""観点 → 論点ページ。**機械が書くのは open な論点だけ。** 決定には触らない。

■ なぜ要るか

`gaps` が出した観点は、人が questions/ に書き写して初めて追跡が始まる。ここが手作業だと
「見たけど起票していない」観点が溜まり、グリッドの穴がいつまでも減らない。
起票すると `cells:` で紐付くので、その穴は表から消え、論点として順位表に乗る。

起票できるのは「問い」の観点だけ。規約違反や既存ページの状態についての観点
（rule.* / graph.* / turn.*）は論点ではないので断る。

ID は slug（`lifecycle.media-retain` / `order.preparing-cancel`）。既存 ID と衝突したら書かない。
"""
import os
import re

from . import fsl, gaps

FILEABLE = ("grid.empty", "grid.row_empty", "grid.not_itemised",
            "fsl.state_event_hole", "fsl.unused_event", "fsl.undecided_unlinked")

PAGE = """---
id: {id}
title: {title}
kind: question
status: open
area: {area}
owner:
severity: {severity}
due:
lead_time_days: 0
aliases: []
cells:{cells}
constrains: []
derives: []
conflicts: []
log: []
blocks_count: 0
blocking: なし
impact_count: 0
ready: true
depth: 0
need_by:
ask_by:
---

## 前提

- なし

## 論点

{body}

## 出どころ

観点 {fid}（`reqmap gaps`、{date}、{check}）

## 自社案

## 決まったこと

<!-- 決まったら status を decided にして、ここに結論と根拠を書く。機械は触らない。 -->
"""


def slug(s):
    return re.sub(r"[^\w.\-]+", "-", str(s).strip()).strip("-.").lower()


def fileable(f):
    return f["check"] in FILEABLE


def plan(proj, f):
    """観点からページの中身を組む。**書かない。** 起票できない観点は None。"""
    if not fileable(f):
        return None
    t, c, body, hint = f["target"], f["check"], f["question"], ""
    if c.startswith("grid."):
        g = {x["id"]: x for x in gaps.load_grids(proj)}.get(t["grid"])
        if not g:
            return None
        area = g["area"]
        if c == "grid.empty":
            pid = "%s.%s-%s" % (g["id"], t["row"], t["col"])
            title = "%sの%s" % (t["row_label"], t["col_label"])
            cells = ["%s:%s x %s" % (g["id"], t["row"], t["col"])]
        elif c == "grid.row_empty":
            pid = "%s.%s" % (g["id"], t["row"])
            title = "%sの扱い（%s）" % (t["row_label"], g["title"] or g["id"])
            cells = ["%s:%s x %s" % (g["id"], t["row"], col) for col in t["cols"]]
        else:
            pid = "%s.itemise" % g["id"]
            title = "%sをマス単位に落とす" % (g["title"] or g["id"])
            cells = []
    else:
        sp = {x["id"]: x for x in fsl.load_specs(proj)}.get(t["model"])
        if not sp:
            return None
        area, base = sp["src"]["area"], t["model"].split("/", 1)[-1]
        if c == "fsl.state_event_hole":
            pid = "%s.%s-%s" % (base, t["state"], t["event"])
            title = "状態『%s』でイベント『%s』が起きたときの扱い" % (t["state"], t["event"])
            cells = ["%s:%s x %s" % (t["model"], t["state"], t["event"])]
            body += "\n\n決まったら仕様に写す: 遷移を足す／forbidden に書く／@impossible に理由を書く。"
        elif c == "fsl.unused_event":
            pid = "%s.%s" % (base, t["event"])
            title = "イベント『%s』はどの状態から発生するか" % t["event"]
            cells = ["%s:* x %s" % (t["model"], t["event"])]
            body += "\n\n決まったら仕様に遷移を足す。"
        else:
            pid = "%s.%s" % (base, str(t["decl"]).split()[-1])
            title = t.get("reason") or t["decl"]
            cells = []
            hint = '@undecided("%s %s")' % (slug(pid), t.get("reason") or "")
            body += "\n\n起票したので、仕様の @undecided の先頭にこのページの ID を書く: `%s`" % hint
    return {"id": slug(pid), "title": title, "area": area or "", "severity": f["severity"],
            "cells": cells, "body": body, "fid": f["id"], "check": c, "hint": hint}


def write(proj, p, today, taken=()):
    """ページを書く。(相対パス, エラー)。既存 ID と衝突したら書かない。"""
    if p["id"] in taken or proj.resolve(p["id"]):
        return None, "すでにあります: %s（別の論点なら ID を変えて手で作ってください）" % p["id"]
    d = os.path.join(proj.root, proj.cfg["questions_dir"], p["area"] or "")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, p["id"] + ".md")
    rel = os.path.relpath(path, proj.root)
    if os.path.exists(path):
        return None, "すでにあります: %s" % rel
    cells = p["cells"]
    text = PAGE.format(id=p["id"], title=p["title"], area=p["area"], severity=p["severity"],
                       cells=(" []" if not cells else "\n" + "\n".join("  - %s" % c for c in cells)),
                       body=p["body"], fid=p["fid"], date=today.isoformat(), check=p["check"])
    open(path, "w", encoding="utf-8").write(text)
    return rel, None
