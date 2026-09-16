# -*- coding: utf-8 -*-
"""FSL（fslc）連携。**検証は fslc に任せ、reqmap は結果を観点に写すだけ。**

FSL は https://github.com/ymm-oss/fsl の形式仕様言語。`models/fsl/*.fsl` を
`requirements` 方言で書くと、fslc が仕様の内部整合を検証する。reqmap の仕事は2つ。

  1. fslc の JSON（check / kernel / verify）を確認観点に写す
     - 禁止したはずの操作列が受理される（後から足した決定が前の決定と矛盾している）
     - 受入基準が通らない、不変条件が破れる、どこにも到達しない状態がある
  2. 仕様の構造から「状態×イベントの穴」を問う（引き出し用の表。fslc は問わない）

reqmap 固有のメタデータはコメント指令で書く（fslc からは不可視）:
  // @area:        どの領域の話か（観点の重み付け）
  // @depends_on:  この仕様を確定させるのに要る論点
  // @events:      まだ遷移が無いイベントも網羅の対象に含める
  // @critical:    隣接に限らず全状態で問うイベント（キャンセル・返金など揉めるもの）
  // @impossible:  「起こり得ない」と判断したマス（未検証の記録。検証したいなら forbidden）

fslc の注釈も読む（fslc は付けられることだけ検査し、JSON には出さない）:
  @reqmap.event("cancel")   同じイベントを複数の遷移に分けたとき、表の上で1つにまとめる
  @undecided("Q-006 理由")  意図的な未決定。**先頭に論点IDを書く。** 論点が open ならそれが
                           正常。論点が決まっているのに残っていれば「決定が仕様に未反映」

fslc が無い環境では観点を1件出して省略する。jssm 形式の旧ファイルは読まない。
"""
import glob
import json
import os
import re
import shutil
import subprocess

from . import model
from .model import SETTLED

DIALECT = re.compile(
    r"^\s*(requirements|spec|business|compose|domain|governance)\s+[\w.]+\s*\{", re.M)
DIRECTIVE = re.compile(r"//\s*@(\w+)\s*:\s*(.+)")
ANNOT = re.compile(r'^\s*@([\w.]+)\s*\(\s*"([^"]*)"\s*\)')
DECL = re.compile(r"^\s*(?:fair\s+)?(transition|action|invariant|trans|reachable|leadsTo"
                  r"|until|unless|init|process)\b\s*([\w.]*)")
SLOT = re.compile(r'"undecided:\s*([^"]*)"')
FORBID = re.compile(r'forbidden\s+(\S+)\s+"[^"]*"\s*\{(.*?)\}', re.S)
STEP = re.compile(r"(\w+)\s*\(\s*([^,)]*)")


# ── 原文から読むもの ─────────────────────────────────────────
def read_source(text):
    """コメント指令・注釈・forbidden の最終ステップ。fslc の意味論には触れない。"""
    out = {"legacy": not DIALECT.search(text), "area": "", "depends_on": [],
           "extra_events": [], "critical": [], "impossible": set(), "events": {},
           "undecided": [], "forbidden": []}
    dv = {}
    for k, v in DIRECTIVE.findall(text):
        dv.setdefault(k, []).append(v.split("//")[0].strip())
    flat = lambda k: [x.strip() for v in dv.get(k, []) for x in v.split(",") if x.strip()]
    out["area"] = (flat("area") or [""])[0]
    out["depends_on"], out["extra_events"], out["critical"] = (
        flat("depends_on"), flat("events"), flat("critical"))
    out["impossible"] = {tuple(x.strip().lower() for x in v.split(" x "))
                         for v in dv.get("impossible", [])}
    pending = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("//")[0]
        m = ANNOT.match(code)
        if m:
            pending.append((m.group(1), m.group(2), n))
            continue
        d = DECL.match(code)
        if d:
            decl = ("%s %s" % (d.group(1), d.group(2))).strip()
            for name, val, ln in pending:
                if name == "reqmap.event" and d.group(1) in ("transition", "action"):
                    out["events"][d.group(2)] = val
                elif name == "undecided":
                    out["undecided"].append({"decl": decl, "reason": val, "line": ln})
            pending = []
            s = SLOT.search(code)
            if s:
                out["undecided"].append({"decl": decl, "reason": s.group(1).strip(), "line": n})
        elif code.strip():
            pending = []
    for fid, body in FORBID.findall(text):
        steps = [(a, arg.strip()) for a, arg in STEP.findall(body.split("expect")[0])]
        if steps:
            out["forbidden"].append({"id": fid, "steps": steps[:-1], "last": steps[-1]})
    return out


# ── fslc の呼び出し ──────────────────────────────────────────
def fslc_path():
    return shutil.which("fslc")


def run_fslc(args, cwd):
    """stdout の JSON を返す。落ちたら error/internal の形にして返す（例外にしない）。"""
    try:
        r = subprocess.run([fslc_path()] + list(args), capture_output=True, text=True,
                           cwd=cwd, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return {"result": "error", "kind": "internal", "message": str(e)[:200]}
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"result": "error", "kind": "internal",
                "message": (r.stderr or r.stdout).strip()[-200:] or "fslc が JSON を返しませんでした"}


# ── kernel → プロセス構造 ─────────────────────────────────────
def _name(node):
    """index / var ノードの名前。requires 側は collection.name、updates 側は name に入る。"""
    if not isinstance(node, dict):
        return None
    if node.get("kind") == "index":
        return node.get("name") or (node.get("collection") or {}).get("name")
    if node.get("kind") == "var":
        return node.get("name")
    return None


def _stage_eqs(expr, mapname, stages):
    """式の中の `<map>[x] == <Stage>` を集める（or / and 越しに）。"""
    if not isinstance(expr, dict) or expr.get("kind") != "binary":
        return set()
    op = expr.get("operator")
    if op == "==":
        l, r = expr.get("left") or {}, expr.get("right") or {}
        for a, b in ((l, r), (r, l)):
            if (a.get("kind") == "index" and _name(a) == mapname
                    and b.get("kind") == "var" and b.get("name") in stages):
                return {b["name"]}
        return set()
    if op in ("or", "and"):
        return (_stage_eqs(expr.get("left"), mapname, stages)
                | _stage_eqs(expr.get("right"), mapname, stages))
    return set()


def _initial(init, mapname, stages):
    def walk(stmts):
        for s in stmts or []:
            if s.get("kind") == "assign":
                t, v = s.get("target") or {}, s.get("value") or {}
                if _name(t) == mapname and v.get("kind") == "var" and v.get("name") in stages:
                    return v["name"]
            else:
                for key in ("statements", "then", "else"):
                    r = walk(s.get(key) or [])
                    if r:
                        return r
        return None
    return walk((init or {}).get("statements")) or (stages[0] if stages else None)


def processes(kernel):
    """`<entity>_stage: Map<E, <Entity>Stage>` を持つプロセスごとに、状態・初期状態・遷移を返す。

    requirements 方言の process+data プロファイルが落とす形だけを見る。
    kernel を手で書いた spec は（この形なら拾えるが）保証しない。その場合は検証だけが効く。"""
    enums = {t["name"]: list(t["definition"]["members"]) for t in kernel.get("types", [])
             if (t.get("definition") or {}).get("kind") == "enum"}
    out = []
    for sv in kernel.get("state", []):
        ty = sv.get("type") or {}
        vname = (ty.get("value") or {}).get("name")
        if ty.get("kind") != "map" or vname not in enums or not sv["name"].endswith("_stage"):
            continue
        stages, trans = enums[vname], []
        for a in kernel.get("actions", []):
            froms = set()
            for r in a.get("requires") or []:
                froms |= _stage_eqs(r, sv["name"], stages)
            to = None
            for u in a.get("updates") or []:
                t, v = u.get("target") or {}, u.get("value") or {}
                if _name(t) == sv["name"] and v.get("kind") == "var" and v.get("name") in stages:
                    to = v["name"]
            if to and froms:
                for f in sorted(froms, key=stages.index):
                    trans.append((a["name"], f, to))
        out.append({"map": sv["name"], "stages": stages,
                    "initial": _initial(kernel.get("init"), sv["name"], stages), "trans": trans})
    return out


# ── 状態×イベントの穴 ─────────────────────────────────────────
def matrix_findings(src, proc, model_id, sev, related):
    """状態×イベントの穴。**全マス総当たりにはしない。**

    総当たりは無意味セル（未送信の注文を受け渡す、など）で埋まり、一度で信用を失う。
    「そのイベントが定義済みの状態の**隣**」だけを問い、遠いセルは件数のみ記録する。
    ただし @critical のイベント（キャンセル・返金など揉めるもの）は全状態で問う。
    隣接だけだと「調理中のキャンセル」のような一番揉めるマスが抑制側に落ちる。"""
    from .gaps import _f
    ev_of = src.get("events") or {}
    ev = lambda a: ev_of.get(a, a)
    stages, trans = proc["stages"], proc["trans"]
    defined = {(f, ev(a)) for a, f, t in trans}
    events = []
    for a, _, _ in trans:
        if ev(a) not in events:
            events.append(ev(a))
    for e in src.get("extra_events") or []:
        if e not in events:
            events.append(e)
    adj = {s: set() for s in stages}
    for a, f, t in trans:
        adj[f].add(t)
        adj[t].add(f)
    outgoing = {f for _, f, _ in trans}
    incoming = {t for _, _, t in trans}
    terminal = {s for s in stages if s not in outgoing}
    impossible = set(src.get("impossible") or ())
    # forbidden の最終ステップが当たるマスは「拒否する」と回答済み（しかも検証されている）。
    # 前提ステップを遷移表でなぞって、最終ステップ時点の状態を出す。
    by_action = {}
    for a, f, t in trans:
        by_action.setdefault(a, {})[f] = t
    for fb in src.get("forbidden") or []:
        cur, ok = {}, True
        for a, arg in fb["steps"]:
            nxt = by_action.get(a, {}).get(cur.get(arg, proc["initial"]))
            if nxt is None:
                ok = False
                break
            cur[arg] = nxt
        if ok:
            a, arg = fb["last"]
            impossible.add((str(cur.get(arg, proc["initial"])).lower(), ev(a).lower()))
    critical = set(src.get("critical") or ())
    findings, suppressed, holes = [], 0, 0
    for e in events:
        S = {f for (f, x) in defined if x == e}
        if not S:
            findings.append(_f("fsl.unused_event", sev, {"model": model_id, "event": e},
                               "イベント『%s』はどの状態でも定義されていません。"
                               "どの状態で発生し、どこへ遷移しますか？"
                               "（不要なら @events から削除してください）" % e, related))
            continue
        nb = set().union(*[adj[s] for s in S]) - S
        for s in stages:
            if s in S or s in terminal or (s.lower(), e.lower()) in impossible:
                continue
            if s not in nb and e not in critical:
                suppressed += 1
                continue
            holes += 1
            findings.append(_f("fsl.state_event_hole", sev,
                               {"model": model_id, "state": s, "event": e},
                               "状態『%s』のときにイベント『%s』が発生したらどうなりますか？"
                               "（遷移を足す／forbidden で拒否を書く／"
                               "@impossible で起こり得ないと記録する、のいずれか）" % (s, e),
                               related))
    for s in stages:
        if s != proc["initial"] and s not in incoming:
            findings.append(_f("fsl.unreachable_stage", "medium", {"model": model_id, "state": s},
                               "状態『%s』にはどこからも到達できません。入る遷移の定義漏れですか？" % s,
                               related, kind="unreachable"))
    summary = {"model": model_id, "stages": len(stages), "events": len(events),
               "trans": len(trans), "suppressed": suppressed, "holes": holes}
    return findings, summary


# ── vault の仕様を読む ─────────────────────────────────────────
def load_specs(proj):
    out = []
    for sub in ("fsl", "fsm"):  # fsm は旧配置。中身が jssm なら legacy として出る
        for p in sorted(glob.glob(os.path.join(proj.root, proj.cfg["models_dir"], sub, "*.fsl"))):
            text = open(p, encoding="utf-8").read()
            out.append({"id": "fsl/" + os.path.splitext(os.path.basename(p))[0], "path": p,
                        "file": os.path.relpath(p, proj.root), "src": read_source(text)})
    return out


def _ref(proj, reason):
    """@undecided("Q-006 理由") の先頭トークンを論点IDに。解決できなければ None。"""
    head = re.split(r"[\s:：]", str(reason).strip(), 1)[0]
    return proj.resolve(head) if head else None


def _related(proj, spec):
    ids = set()
    for ref in spec["src"]["depends_on"]:
        ids.add(proj.resolve(ref) or ref)
    for i, it in proj.items.items():
        if any(str(c).strip().startswith(spec["id"]) for c in it["cells"]):
            ids.add(i)
    for u in spec["src"]["undecided"]:
        r = _ref(proj, u["reason"])
        if r:
            ids.add(r)
    return sorted(ids)


def _state_str(state):
    parts = []
    for k, v in sorted((state or {}).items()):
        if isinstance(v, dict):
            parts += ["%s[%s]=%s" % (k, i, x) for i, x in sorted(v.items())]
        else:
            parts.append("%s=%s" % (k, v))
    return ", ".join(parts)[:120]


# ── 観点 ───────────────────────────────────────────────────
def gaps(proj):
    """(findings, summaries)。gaps.run から呼ばれる。"""
    from .gaps import _f
    specs = load_specs(proj)
    findings, summaries = [], []
    if not specs:
        return findings, summaries
    if not fslc_path():
        # 無いものは無いと言う。黙って省略すると「異常なし」に見える。
        findings.append(_f("fsl.tool_missing", "medium", {"specs": len(specs)},
                           "fslc が見つからないため、FSL 仕様 %d 本の検査を省略しました。"
                           "入れ方: https://github.com/ymm-oss/fsl" % len(specs), kind="tool"))
        for sp in specs:
            summaries.append({"model": sp["id"], "file": sp["file"], "stages": 0, "events": 0,
                              "trans": 0, "suppressed": 0, "holes": 0, "verify": "fslc なし",
                              "undecided": len(sp["src"]["undecided"])})
        return findings, summaries
    depth = int(proj.cfg.get("fsl_depth") or 8)
    for sp in specs:
        src, related = sp["src"], _related(proj, sp)
        sev = "high" if proj.area_risk(src["area"]) == "high" else "medium"
        summ = {"model": sp["id"], "file": sp["file"], "stages": 0, "events": 0, "trans": 0,
                "suppressed": 0, "holes": 0, "verify": "", "undecided": len(src["undecided"])}
        summaries.append(summ)
        if src["legacy"]:
            findings.append(_f("fsl.legacy_format", "medium", {"model": sp["id"]},
                               "%s は fslc の仕様として読めません（jssm 形式の旧ファイル？）。"
                               "requirements 方言に書き換えてください。" % sp["file"],
                               related, kind="tool"))
            summ["verify"] = "読めない"
            continue

        # check: 構文・型・受入基準・禁止経路。禁止経路の受理は「決定どうしの矛盾」。
        chk = run_fslc(["check", sp["path"]], proj.root)
        if chk.get("result") == "error":
            k = chk.get("kind")
            if k == "forbidden":
                trace = " → ".join(str(s.get("action", "?")) for s in chk.get("accepted_trace") or [])
                findings.append(_f("fsl.forbidden_accepted", "high",
                                   {"model": sp["id"], "id": chk.get("id")},
                                   "%s: 禁止したはずの操作列『%s』（%s）が受理されます: %s。"
                                   "後から足した遷移や決定が、前の決定と矛盾していないか確認してください。"
                                   % (sp["file"], chk.get("text") or "", chk.get("id"), trace),
                                   related, kind="contradiction"))
            elif k == "acceptance":
                findings.append(_f("fsl.acceptance_failed", "high",
                                   {"model": sp["id"], "id": chk.get("id")},
                                   "%s: 受入基準『%s』（%s）が %s 手目で通りません。"
                                   "仕様と受入基準のどちらが正しいか決めてください。"
                                   % (sp["file"], chk.get("text") or "", chk.get("id"),
                                      chk.get("failed_step") or "?"),
                                   related, kind="contradiction"))
            else:
                loc = chk.get("loc") or {}
                findings.append(_f("fsl.spec_error", "high",
                                   {"model": sp["id"], "kind": k, "line": loc.get("line")},
                                   "%s は fslc で読めません（%s%s）: %s"
                                   % (sp["file"], k, "、%s 行" % loc["line"] if loc.get("line") else "",
                                      str(chk.get("message"))[:120]),
                                   related, kind="spec_error"))
                summ["verify"] = "error"
                continue

        # kernel: 状態×イベントの表はここから組む
        ker = run_fslc(["kernel", sp["path"]], proj.root)
        procs = processes(ker) if ker.get("actions") is not None else []
        from_of = {}
        for proc in procs:
            F, ms = matrix_findings(src, proc, sp["id"], sev, related)
            findings += F
            for key in ("stages", "events", "trans", "suppressed", "holes"):
                summ[key] += ms[key]
            for a, f, _ in proc["trans"]:
                from_of.setdefault(a, set()).add(f)
        unreachable = {f["target"]["state"] for f in findings
                       if f["check"] == "fsl.unreachable_stage" and f["target"]["model"] == sp["id"]}

        # verify: 不変条件・到達性・行き止まり・上位層との整合
        ver = run_fslc(["verify", sp["path"], "--depth", str(depth)], proj.root)
        r = ver.get("result")
        summ["verify"] = r or "?"
        if r == "error" and ver.get("kind") in ("acceptance", "forbidden"):
            # check で報告済み。要約には何で止まったかだけ残す
            summ["verify"] = "%s %s で停止" % (ver.get("kind"), ver.get("id") or "")
        if r == "violated":
            req, la = ver.get("requirement") or {}, ver.get("last_action") or {}
            findings.append(_f("fsl.violated", "high",
                               {"model": sp["id"], "kind": ver.get("violation_kind"),
                                "name": ver.get("invariant") or ver.get("property") or ""},
                               "%s: %s『%s』が %s 手目（%s の直後）で破れます。%s"
                               % (sp["file"], ver.get("violation_kind") or "",
                                  ver.get("invariant") or req.get("id") or "",
                                  ver.get("violated_at_step") or "?", la.get("name") or "?",
                                  ("要件: " + req["text"]) if req.get("text") else ""),
                               related, kind="contradiction"))
        elif r == "reachable_failed":
            findings.append(_f("fsl.unreachable", "medium",
                               {"model": sp["id"], "name": ver.get("reachable") or ""},
                               "%s: 到達できるはずの状態『%s』に深さ %d では到達しません。"
                               % (sp["file"], ver.get("reachable") or "", depth),
                               related, kind="unreachable"))
        elif r == "error" and ver.get("kind") not in ("acceptance", "forbidden"):
            findings.append(_f("fsl.spec_error", "high",
                               {"model": sp["id"], "kind": ver.get("kind"), "line": None},
                               "%s: verify が失敗しました（%s）: %s"
                               % (sp["file"], ver.get("kind"), str(ver.get("message"))[:120]),
                               related, kind="spec_error"))
        for w in ver.get("warnings") or []:
            if w.get("kind") != "never_enabled_action":
                continue
            name = w.get("name")
            # 到達不能な状態から出る遷移は unreachable_stage で出ているので重ねない
            if from_of.get(name) and from_of[name] <= unreachable:
                continue
            req = w.get("requirement") or {}
            findings.append(_f("fsl.dead_action", "medium", {"model": sp["id"], "action": name},
                               "%s: 遷移『%s』は深さ %d のどの実行でも起きません"
                               "（前提の状態に入る経路が無い）。%s"
                               % (sp["file"], name, depth,
                                  ("要件: " + req["text"]) if req.get("text") else ""),
                               related, kind="dead_end"))
        dl = ver.get("deadlock") or {}
        if dl.get("found"):
            last = (dl.get("trace") or [{}])[-1].get("state") or {}
            findings.append(_f("fsl.dead_end", "medium",
                               {"model": sp["id"], "state": _state_str(last)},
                               "%s: 終端と宣言していない状態で止まります（%s 手目: %s）。"
                               "ここが終端で正しいなら terminal に足し、違えば出る遷移を足してください。"
                               % (sp["file"], dl.get("at_step") or "?", _state_str(last)),
                               related, kind="dead_end"))
        imp = ver.get("implements") or {}
        if imp.get("result") and imp["result"] != "refines":
            findings.append(_f("fsl.seam_broken", "high",
                               {"model": sp["id"], "abs": imp.get("abs")},
                               "%s: 上位層『%s』との整合が崩れています（%s）。"
                               "要件が業務層の約束を破っていないか確認してください。"
                               % (sp["file"], imp.get("abs"), imp["result"]),
                               related, kind="contradiction"))

        # undecided: 論点が open ならそれが正常。決まっているのに残っていれば未反映。
        for u in src["undecided"]:
            qid = _ref(proj, u["reason"])
            if qid is None:
                findings.append(_f("fsl.undecided_unlinked", "medium",
                                   {"model": sp["id"], "decl": u["decl"], "line": u["line"]},
                                   "%s の『%s』は未決定（%s）ですが、対応する論点が起票されていません。"
                                   "論点を起こし、@undecided の先頭にその ID を書いてください。"
                                   % (sp["file"], u["decl"], u["reason"][:40]),
                                   related, kind="undecided"))
            elif proj.items[qid]["status"] in SETTLED:
                it = proj.items[qid]
                findings.append(_f("fsl.stale_undecided", "high",
                                   {"model": sp["id"], "decl": u["decl"], "item": qid},
                                   "『%s』は%sですが、仕様 %s の『%s』は undecided のままです。"
                                   "決定を仕様に反映してください（遷移・forbidden・guard に写す）。"
                                   % (it["title"], "決定済み" if it["status"] == model.DECIDED else "取下げ",
                                      sp["file"], u["decl"]),
                                   [qid], kind="stale_undecided"))
    return findings, summaries
