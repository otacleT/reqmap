# -*- coding: utf-8 -*-
"""Change Set — 抽出した内容を論点ページに反映する前の中間物。**外部依存なし。**

■ なぜ直接書かないか

議事録から論点を起こすのは LLM の仕事だが、**LLM が questions/ に直接書くと、
何が人の言葉で何がモデルの創作かの区別が消える。** 一度混ざると後から分離できない。

そこで Change Set を挟む。1件ごとに `quote`（原文からの引用）を持たせ、
**機械が原文と照合する。** 原文に無い引用は `blocked` になり、決して適用されない。
これが幻覚に対する唯一の実効的な防波堤で、モデルの自己申告には頼らない。

■ ゲート（ラチェット）

  auto     新規の未決論点・引用が原文に一致・既存ページに触れない → 適用してよい
  human    既存ページの変更、決定に触れるもの、引用が曖昧 → チャットで確認してから
  blocked  引用が原文に無い、参照先が存在しない、必須項目が欠けている → 動かせない

**判定は一方通行。機械は auto → human へ引き上げることしかしない。**
ファイルに手書きで human / blocked と書いてあるものを auto へ下げることはない。
"""
import datetime
import glob
import os
import re

from . import fm, model

REQUIRED = ("op", "id", "title", "quote")
OPS = ("create", "update", "decide")
AUTO, HUMAN, BLOCKED, APPLIED = "auto", "human", "blocked", "applied"
RANK = {AUTO: 0, HUMAN: 1, BLOCKED: 2, APPLIED: -1}
PENDING = (AUTO, HUMAN, BLOCKED)

FIELDS = ("area", "kind", "status", "owner", "severity", "due", "ledger",
          "lead_time_days", "note")


def parse(path):
    """Change Set を読む。`changes:` の下に `- key: value` の塊が並ぶ形だけを解釈する。"""
    text = open(path, encoding="utf-8").read()
    head, _, body = text.partition("changes:")
    meta = fm.parse(head)
    changes, cur = [], None
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*-\s+([^:#]+?)\s*:\s*(.*)$", line)
        if m:
            cur = {}
            changes.append(cur)
            cur[m.group(1).strip()] = fm._scalar(m.group(2))
            continue
        m = re.match(r"^\s+([^:#\-][^:]*?)\s*:\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1).strip()] = fm._scalar(m.group(2))
    meta["_file"] = path
    return meta, changes


def _norm(s):
    """引用照合用の正規化。全角空白・改行・記号ゆれだけを吸収し、語は変えない。"""
    s = str(s)
    s = re.sub(r"[\s　]+", "", s)
    return (s.replace("｢", "「").replace("｣", "」")
             .replace("（", "(").replace("）", ")")
             .replace("、", ",").replace("。", ".").lower())


def verify_quote(quote, source_text):
    """(一致の種類, 説明) を返す。exact / normalized / none。"""
    if not quote:
        return "none", "引用がない"
    if quote in source_text:
        return "exact", ""
    if _norm(quote) in _norm(source_text):
        return "normalized", "空白や記号のゆれを吸収すれば一致した"
    return "none", "原文に見つからない"


def applied_already(chg, proj, meta):
    """この提案はもう反映済みか。

    反映済みが `human` のまま残ると、承認待ちの件数が減らず、やがて誰も見なくなる。
    ID があるだけでは足りない（別の Change Set が同じIDを別内容で提案しているかもしれない）
    ので、**そのページの「出どころ」がこの Change Set と同じ**ことまで確かめる。"""
    if chg.get("op") != "create":
        return False
    rid = proj.resolve(str(chg.get("id") or ""))
    if not rid:
        return False
    src = str(meta.get("source") or "").strip()
    return bool(src) and src in proj.items[rid]["body"]


def classify(chg, proj, source_text, declared=None):
    """1件をゲート分類する。戻り値は (gate, 理由)。**引き上げのみ。**"""
    reasons, notes = [], []
    gate = AUTO

    def raise_to(g, why):
        nonlocal gate
        reasons.append(why)
        if RANK[g] > RANK[gate]:
            gate = g

    for k in REQUIRED:
        if not str(chg.get(k, "")).strip():
            raise_to(BLOCKED, "必須項目 %s がない" % k)
    if chg.get("op") not in OPS:
        raise_to(BLOCKED, "op が create/update/decide のいずれでもない")

    kind, why = verify_quote(chg.get("quote"), source_text)
    if kind == "none":
        raise_to(BLOCKED, "引用が原文に見つからない（%s）" % (chg.get("quote") or "")[:28])
    elif kind == "normalized":
        # 正規化は空白と記号ゆれだけを吸収する。語の順序も内容も変わらないので、
        # 改行位置の違いで止めない。日本語の議事録は常に折り返すため、
        # ここで毎回止めると使われなくなる（**煩わしさは正しさより早く効く**）。
        notes.append("引用は改行・記号のゆれを吸収して一致")
    if kind != "none":
        # 照合が守るのは「その一文が原文にある」ことだけ。短い・汎用的な一文は
        # どんな title にも付けられる。出所を特定できない引用は blocked ではなく人に回す
        # （存在はするので、モデルの作文とは限らない）。
        q = _norm(chg.get("quote"))
        mn = int(proj.cfg.get("quote_min_chars") or 0)
        if mn and len(q) < mn:
            raise_to(HUMAN, "引用が短く出所を特定できない（%d 文字。%d 文字以上にする）" % (len(q), mn))
        if _norm(source_text).count(q) > 1:
            raise_to(HUMAN, "引用が原文に複数回出現し、どの発言か特定できない")

    cid = str(chg.get("id", "")).strip()
    exists = proj.resolve(cid) if cid else None
    if chg.get("op") == "create":
        if exists:
            raise_to(HUMAN, "%s はすでにあります。更新のつもりですか？" % cid)
        st = str(chg.get("status") or "open")
        if proj._norm_status(st) not in (model.OPEN, model.INVESTIGATING):
            raise_to(HUMAN, "新規なのに status が %s（未決以外は人が判断する）" % st)
    else:
        if not exists:
            raise_to(BLOCKED, "更新先 %s が見つからない" % cid)
        raise_to(HUMAN, "既存ページを書き換える")
    if chg.get("op") == "decide" or str(chg.get("decision", "")).strip():
        raise_to(HUMAN, "決定に触れる。**決定は人が下す**")

    for ref in str(chg.get("prereqs") or "").split(",") if isinstance(
            chg.get("prereqs"), str) else (chg.get("prereqs") or []):
        ref = str(ref).strip()
        if ref and not proj.resolve(ref):
            raise_to(HUMAN, "前提 %s がまだ存在しない（先に起票が要る）" % ref)

    # ラチェット: ファイルに書かれた判定より緩くはしない
    if declared in (HUMAN, BLOCKED) and RANK[declared] > RANK[gate]:
        gate = declared
        reasons.append("ファイルに %s と書かれている" % declared)
    return gate, reasons + notes


def review(proj, path):
    meta, changes = parse(path)
    src = os.path.join(proj.root, str(meta.get("source") or ""))
    if not os.path.exists(src):
        src = str(meta.get("source") or "")
    source_text = open(src, encoding="utf-8").read() if os.path.exists(src) else ""
    out = []
    for chg in changes:
        if applied_already(chg, proj, meta):
            g, r = APPLIED, ["反映済み"]
        elif not source_text:
            g, r = BLOCKED, ["source が読めない: %s" % meta.get("source")]
        else:
            g, r = classify(chg, proj, source_text, str(chg.get("gate") or "") or None)
        out.append({"change": chg, "gate": g, "reasons": r})
    return meta, out


# ── 適用 ────────────────────────────────────────────────────
PAGE = """---
id: {id}
title: {title}
kind: {kind}
status: {status}
area: {area}
owner: {owner}
severity: {severity}
due:{due}
lead_time_days: {lead}
{ledger}aliases: []
cells:{cells}
constrains: []
derives: []
conflicts: []
blocks_count: 0
blocking: なし
impact_count: 0
ready: true
depth: 0
need_by:
ask_by:
---

## 前提

{prereqs}

## 論点

{note}

## 出どころ

> {quote}

— {source}{ledger_note}

## 自社案

## 決まったこと

<!-- 決まったら status を decided にして、ここに結論と根拠を書く。機械は触らない。 -->
"""


def _safe(name):
    return re.sub(r'[/\\:*?"<>|]', "_", str(name)).strip()


def apply_one(proj, chg, meta):
    """create のみ。update は人がページを直接直す（機械が既存文を書き換えない）。"""
    cid = str(chg["id"]).strip()
    area = str(chg.get("area") or "")
    d = os.path.join(proj.root, proj.cfg["questions_dir"], _safe(area) if area else "")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, _safe(cid) + ".md")
    if os.path.exists(path):
        return None, "すでにある: %s" % os.path.relpath(path, proj.root)
    prereqs = chg.get("prereqs") or []
    if isinstance(prereqs, str):
        prereqs = [x.strip() for x in prereqs.split(",") if x.strip()]
    cells = chg.get("cells") or []
    if isinstance(cells, str):
        cells = [x.strip() for x in cells.split(",") if x.strip()]
    led = str(chg.get("ledger") or "")
    text = PAGE.format(
        id=cid, title=chg["title"], kind=chg.get("kind") or "question",
        status=chg.get("status") or "open", area=area,
        owner=chg.get("owner") or "", severity=chg.get("severity") or "medium",
        due=(" " + str(chg["due"])) if chg.get("due") else "",
        lead=chg.get("lead_time_days") or 0,
        ledger=('ledger: "%s"\n' % led) if led else "",
        cells=(" []" if not cells else "\n" + "\n".join("  - %s" % c for c in cells)),
        prereqs=("\n".join("- [[%s]]" % p for p in prereqs) or "- なし"),
        note=chg.get("note") or "", quote=chg["quote"],
        source=meta.get("source") or "",
        ledger_note=("（%s）" % led) if led else "")
    open(path, "w", encoding="utf-8").write(text)
    return os.path.relpath(path, proj.root), None


def changesets(proj):
    return sorted(glob.glob(os.path.join(proj.root, "_changesets", "*.yml")))
