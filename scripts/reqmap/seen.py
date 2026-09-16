# -*- coding: utf-8 -*-
"""「前回自分が見たとき」の基準。**各自のもの**（.reqmap/ は gitignore 済み）。

基準は2つあり、進むタイミングが違う。
  findings-seen.json   観点の既読。`gaps --snapshot` で進める（定例前に週1）
  decisions-seen.json  決定の基準。`changes --ack` で進める（毎朝）

以前は1ファイルにまとめていた。すると「観点を見終わった」つもりで snapshot したときに
決定の基準まで進み、まだ読んでいない決定の書き換わりが黙って消えた。
"""
import json
import os

from . import model

FINDINGS, DECISIONS = "findings-seen.json", "decisions-seen.json"


def _path(proj, name):
    return os.path.join(proj.root, proj.cfg["out_dir"], name)


def _load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def findings_seen(proj):
    d = _load(_path(proj, FINDINGS))
    return {"at": d.get("at", "?"), "ids": set(d.get("ids") or [])} if d else None


def save_findings_seen(proj, ids):
    _save(_path(proj, FINDINGS), {"at": model.today().isoformat(), "ids": sorted(ids)})


def decisions_seen(proj):
    d = _load(_path(proj, DECISIONS))
    if d:
        return {"at": d.get("at", "?"), "decisions": d.get("decisions") or {}}
    old = _load(_path(proj, FINDINGS))  # 旧形式（1ファイルに両方入っていた）
    if old and old.get("decisions"):
        return {"at": old.get("at", "?"), "decisions": old["decisions"]}
    return None


def save_decisions_seen(proj, snap):
    _save(_path(proj, DECISIONS), {"at": model.today().isoformat(), "decisions": snap})
