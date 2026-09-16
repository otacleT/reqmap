# -*- coding: utf-8 -*-
"""プロジェクト設定と論点ページの読み込み。**外部依存なし。**"""
import datetime
import glob
import os
import re

from . import fm

CONFIG = "reqmap.yml"

# 正規の状態。日本語などの別名は設定の status_aliases で写す。
OPEN, INVESTIGATING, PROVISIONAL, DECIDED, DROPPED = (
    "open", "investigating", "provisional", "decided", "dropped")
SETTLED = (DECIDED, DROPPED)
ACTIVE = (OPEN, INVESTIGATING, PROVISIONAL)

DEFAULTS = {
    "milestone": "", "questions_dir": "questions", "models_dir": "models",
    "out_dir": ".reqmap", "max_prereqs": 2, "response_days_default": 14,
    "prereq_heading": "前提", "id_pattern": r"^[A-Za-z][\w.\-]*",
    "decision_heading": "決まったこと", "design_dirs": [],
}


def _split3(s):
    """'ID | ラベル | 語,語' → (id, label, [words])"""
    parts = [x.strip() for x in str(s).split("|")]
    pid = parts[0]
    label = parts[1] if len(parts) > 1 and parts[1] else pid
    words = [w.strip() for w in parts[2].split(",")] if len(parts) > 2 else []
    return pid, label, [w for w in words if w]


class Project:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        path = os.path.join(self.root, CONFIG)
        raw = fm.parse(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}
        self.cfg = dict(DEFAULTS)
        self.cfg.update({k: v for k, v in raw.items() if v != ""})
        self.aliases = raw.get("status_aliases") or {}
        self.response_days = raw.get("response_days") or {}
        self.areas = {}
        for a in raw.get("areas") or []:
            aid, label, extra = _split3(a)
            self.areas[aid] = {"label": label, "risk": (extra[0] if extra else "medium")}
        self.items = self._load()
        self.by_title = {}
        for it in self.items.values():
            self.by_title.setdefault(it["title"], it["id"])
            self.by_title.setdefault(os.path.splitext(os.path.basename(it["file"]))[0], it["id"])
            # 旧ID。リネームしても参照が壊れないようにする。
            # 本文の [[旧ID タイトル]] と、frontmatter の `旧ID` 単体の両方が来るので
            # 別名そのものと、その ID 部分の両方を登録する。
            for a in it["aliases"]:
                self.by_title.setdefault(a, it["id"])
                m = re.match(self.cfg["id_pattern"], a)
                if m:
                    self.by_title.setdefault(m.group(0), it["id"])

    # ── 読み込み ────────────────────────────────────────────
    def _norm_status(self, s):
        s = str(s).strip()
        s = self.aliases.get(s, s)
        return s if s in (OPEN, INVESTIGATING, PROVISIONAL, DECIDED, DROPPED) else OPEN

    def _load(self):
        items, qdir = {}, os.path.join(self.root, self.cfg["questions_dir"])
        self.duplicates, self.unreadable = [], []
        for path in sorted(glob.glob(os.path.join(qdir, "**", "*.md"), recursive=True)):
            if os.path.basename(path).startswith("_"):
                continue
            text = open(path, encoding="utf-8").read()
            head, body = fm.split(text)
            rel0 = os.path.relpath(path, self.root)
            # **読めないページを黙って捨てない。** 捨てると点検が不完全なまま
            # 「異常なし」に見える。無いのと壊れているのは別のこと。
            if not head:
                self.unreadable.append((rel0, "frontmatter がない"))
                continue
            d = fm.parse(head)
            if not d.get("id"):
                self.unreadable.append((rel0, "id がない"))
                continue
            rel = os.path.relpath(path, self.root)
            if d["id"] in items:
                # dict に入れると先勝ち／後勝ちで片方が消え、検査もできなくなる。
                # ここで拾わないと「ID を直したのに直っていない」が起きる。
                self.duplicates.append((d["id"], items[d["id"]]["file"], rel))
            items[d["id"]] = {
                "id": d["id"], "title": d.get("title") or d["id"],
                "kind": d.get("kind") or "question",
                "status": self._norm_status(d.get("status")),
                "raw_status": d.get("status"),
                "area": d.get("area") or "", "owner": d.get("owner") or "",
                "severity": d.get("severity") or "medium",
                "due": d.get("due") or "", "need_by": d.get("need_by") or "",
                "ask_by": d.get("ask_by") or "",
                "lead_time_days": int(d.get("lead_time_days") or 0),
                "response_days": d.get("response_days"),
                "cells": d.get("cells") or [], "covers": d.get("covers") or [],
                "aliases": [str(a).strip() for a in (d.get("aliases") or [])],
                "log": [],  # turns.parse で埋める（循環importを避けるため後段で）
                "ledger": d.get("ledger") or "",
                "assumption": d.get("assumption") or {},
                "typed": {k: [_split3(x)[0] for x in (d.get(k) or [])]
                          for k in ("constrains", "derives", "conflicts")},
                "prereq_raw": fm.wikilinks(fm.section(body, self.cfg["prereq_heading"])),
                "stray_links": [],
                "file": rel, "body": body, "fm": d,
            }
            # 前提セクションの外にあるリンク（規約R1違反の検出用）
            inside = fm.section(body, self.cfg["prereq_heading"])
            outside = body.replace(inside, "") if inside else body
            items[d["id"]]["stray_links"] = fm.wikilinks(outside)
        from . import turns
        for it in items.values():
            it["log"] = turns.parse(it["fm"].get("log"))
        return items

    # ── 参照の解決 ──────────────────────────────────────────
    def resolve(self, ref):
        """[[Q-001 タイトル]] や 'Q-001' を id に。見つからなければ None。"""
        ref = str(ref).strip()
        if ref in self.items:
            return ref
        m = re.match(self.cfg["id_pattern"], ref)
        if m and m.group(0) in self.items:
            return m.group(0)
        return self.by_title.get(ref)

    def prereqs(self, it):
        """blocks 依存（本文の ## 前提）。(id, 未解決ラベル) を返す。"""
        out, bad = [], []
        for r in it["prereq_raw"]:
            rid = self.resolve(r)
            (out if rid else bad).append(rid or r)
        return out, bad

    def area_risk(self, aid):
        return self.areas.get(aid, {}).get("risk", "medium")

    def resp_days(self, it):
        if it.get("response_days") not in (None, ""):
            return int(it["response_days"])
        return int(self.response_days.get(it["owner"], self.cfg["response_days_default"]))

    def path(self, it):
        return os.path.join(self.root, it["file"])


def is_aggregator(it):
    """領域の集約点ページか。**id と area が同じなら集約点。**

    「A-03 顔画像のライフサイクル」のような領域ページは、その領域の論点を束ねるために
    前提を何本も持つのが正しい姿。個別の論点と同じ規約で縛ると誤検出になる。
    設定を増やさず id == area で判定できるのは、集約点は自分の領域を代表するから。"""
    return bool(it.get("area")) and it["id"] == it["area"]


def today():
    return datetime.date.today()


def as_date(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except Exception:
        return None
