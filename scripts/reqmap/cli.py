# -*- coding: utf-8 -*-
"""reqmap — 要件定義ハーネスの CLI。**外部依存なし。**

    reqmap init [dir]      プロジェクトの雛形を作る
    reqmap recalc          影響度・深さ・着手可否・逆算日付を frontmatter に書く
    reqmap recalc --check  書かずに、結果と規約違反だけ表示する
    reqmap gaps            確認観点を出す（何も書かない）
    reqmap gaps --new      前回見たときから新しく出たものだけ
    reqmap gaps --snapshot 「ここまでは見た」を記録する（--new の基準になる）
    reqmap gaps --file <観点ID,...>  観点から open な論点ページを起票する（cells: で紐付く）
    reqmap show <id>       1論点の全部（前提・下流・日付・やりとり・仕様側の関連・観点）
    reqmap doctor          この vault をちゃんと読めているかを点検する
    reqmap status          静かな点検。人が動くものだけを出す
    reqmap view            HTML を出力する
    reqmap json            すべてを JSON で出す（他ツール連携用）
    reqmap changes         前回見たときから書き換わった決定を出す（**何も書かない**）
    reqmap changes --ack   「ここまでの決定は見た」を記録する（changes の基準になる）
    reqmap review          Change Set を点検する（引用照合とゲート分類。**何も書かない**）
    reqmap apply           Change Set のうち auto のものを適用する
    reqmap apply --approve <id,...>   human のものを名指しで適用する
    reqmap ci              矛盾と「読めていない」があれば exit 1（CI で PR を止める用。何も書かない）

■ 書き込みの約束

recalc が書くのは frontmatter の**計算済み7キーだけ**。
    blocks_count / blocking / impact_count / ready / depth / need_by / ask_by

`status` `decision` `severity` は**機械が書かない**。決定は人が下す。
機械が決定欄に触れるようになった瞬間、この仕組みは信用できなくなる。
"""
import datetime
import json
import os
import re
import shutil
import sys

from . import changeset, decisions, filing, fm, fsl, gaps, graph, model, seen, turns
from .model import ACTIVE, DECIDED, DROPPED, PROVISIONAL, SETTLED

WRITE_KEYS = ("blocks_count", "blocking", "impact_count", "ready", "depth",
              "need_by", "ask_by")
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.abspath(os.path.join(HERE, "..", "..", "templates"))


# ── init ────────────────────────────────────────────────────
def cmd_init(root, args):
    root = os.path.abspath(root)
    if os.path.exists(os.path.join(root, model.CONFIG)) and "--force" not in args:
        print("すでに %s があります。--force で上書きします。" % model.CONFIG)
        return 1
    for d in ("questions", "models/grids", "models/fsl", ".reqmap"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    shutil.copy(os.path.join(TEMPLATES, "reqmap.yml"), os.path.join(root, model.CONFIG))
    for src in ("grids", "fsl"):
        sd = os.path.join(TEMPLATES, src)
        for f in sorted(os.listdir(sd)):
            dst = os.path.join(root, "models", src, f)
            if not os.path.exists(dst):
                shutil.copy(os.path.join(sd, f), dst)
    shutil.copy(os.path.join(TEMPLATES, "question.md"),
                os.path.join(root, "questions", "_template.md"))
    # .reqmap は**各自のもの**。「前回自分が見たとき」の基準がここに入るので、
    # コミットすると他人の基準で上書きされる。
    open(os.path.join(root, ".reqmap", ".gitignore"), "w",
         encoding="utf-8").write("*\n")
    print("作りました: %s" % root)
    print("  reqmap.yml        まず milestone と areas を書く")
    print("  models/grids/     いらない観点のグリッドは消す。**消すより skip に理由を書くほうがよい**")
    print("  models/fsl/       主フローの状態遷移を fslc の requirements 方言で書く（fslc が検証する）")
    print("  questions/        _template.md をコピーして論点を1つ作る")
    print("\n次: reqmap gaps  で、何も起票していない状態からどれだけ観点が出るか見る")
    return 0


# ── recalc ──────────────────────────────────────────────────
def cmd_recalc(root, args):
    proj = model.Project(root)
    check_only = "--check" in args
    an = graph.analyse(proj)
    res, changed = an["result"], []
    for iid, it in sorted(proj.items.items()):
        r = res[iid]
        new = {k: r[k] for k in WRITE_KEYS}
        cur = {k: it["fm"].get(k, "") for k in WRITE_KEYS}
        diff = {k: (cur[k], new[k]) for k in WRITE_KEYS if str(cur[k]) != str(new[k])}
        if not diff:
            continue
        changed.append((iid, diff))
        if check_only:
            continue
        path = proj.path(it)
        text = open(path, encoding="utf-8").read()
        for k, v in new.items():
            text = fm.set_key(text, k, v)
        open(path, "w", encoding="utf-8").write(text)

    rules = [f for f in gaps.graph_checks(proj, an) if f["kind"] in ("rule", "broken_link", "conflict")]
    print("%s  %d 論点 / 更新 %d 件%s"
          % (proj.cfg.get("name") or os.path.basename(proj.root), len(proj.items),
             len(changed), "（--check のため書いていません）" if check_only else ""))
    if an["cycle_nodes"]:
        # 循環に乗っている論点だけ初期値に落とす。黙って落とすと「なぜ期限が消えたか」が分からない。
        print("循環 %d 本。%s は循環のため depth / need_by が初期値です"
              "（どれかを先に仮決定してください）。他の論点は通常どおり計算しています。"
              % (len(an["cycles"]), "・".join(an["cycle_nodes"][:6])))
    if rules:
        print("\n規約違反・要確認 %d 件" % len(rules))
        for f in rules[:10]:
            print("  - %s" % f["question"])
        if len(rules) > 10:
            print("  … 他 %d 件" % (len(rules) - 10))
    else:
        print("規約違反なし")
    return 0


# ── gaps ────────────────────────────────────────────────────
def cmd_gaps(root, args):
    proj = model.Project(root)
    out = gaps.run(proj)
    only = [a for a in args if not a.startswith("--")]
    F = [f for f in out["findings"] if not only or any(o in f["check"] for o in only)]

    files = [a.split("=", 1)[1] for a in args if a.startswith("--file=")]
    if files:
        return _file_findings(proj, out, [x.strip() for x in ",".join(files).split(",") if x.strip()])
    base = seen.findings_seen(proj)
    seen_ids = base["ids"] if base else None
    if "--snapshot" in args:
        # 観点の既読だけを進める。決定の基準は `changes --ack`（進むタイミングが違う）。
        seen.save_findings_seen(proj, [f["id"] for f in out["findings"]])
        print("観点 %d 件を「見た」として記録しました。次からは `gaps --new` で新しい観点だけが出ます。"
              % len(out["findings"]))
        print("決定の基準は別です。`reqmap changes --ack` で進めます。")
        return 0
    if "--new" in args:
        if seen_ids is None:
            print("基準がありません。まず `reqmap gaps --snapshot` を実行してください。")
            return 1
        F = [f for f in F if f["id"] not in seen_ids]
        if not F:
            print("前回から新しく出た観点はありません。")
            return 0
    if "--quiet" in args:
        F = [f for f in F if f["severity"] == "high"]
        if not F:
            return 0
    if "--json" in args:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=_jsonable))
        return 0

    print("# 確認観点  %s  (%s)" % (proj.cfg.get("name") or "", out["generated_at"]))
    sup = sum(s["suppressed"] for s in out["fsl"])
    line = "  findings %d 件" % len(F) + ("（状態×イベントの自動抑制 %d マス）" % sup if sup else "")
    if seen_ids is not None:
        line += "  / 前回から新規 %d 件" % len(
            [f for f in out["findings"] if f["id"] not in seen_ids])
    print(line)
    for g in out["grids"]:
        print("  %-14s %d マス中  空白 %d / 候補あり %d / 紐付け済み %d / skip %d"
              % (g["grid"], g["total"], g["empty"], g["near"], g["linked"], g["skip"]))
    for s in out["fsl"]:
        print("  %-14s 状態 %d × イベント %d  遷移 %d  穴 %d  検証 %s"
              % (s["model"], s["stages"], s["events"], s["trans"], s["holes"], s["verify"]))
    by = {}
    for f in F:
        by.setdefault(f["check"], []).append(f)
    for check in sorted(by, key=lambda c: (SEV_ORDER[by[c][0]["severity"]], c)):
        rows = by[check]
        print("\n## %s  (%d件)" % (check, len(rows)))
        cap = 3 if check == "grid.unlinked" else 8
        for f in rows[:cap]:
            print("  [%-6s] %s" % (f["severity"], f["question"]))
        if len(rows) > cap:
            print("  … 他 %d 件" % (len(rows) - cap))
    return 0


def _file_findings(proj, out, ids):
    """観点から論点ページを起票する。書くのは open な論点だけ。"""
    by_id = {f["id"]: f for f in out["findings"]}
    bad, taken = 0, set()
    for fid in ids:
        f = by_id.get(fid)
        if not f:
            print("  見つかりません  %s（gaps の一覧に出る ID を写してください）" % fid)
            bad += 1
            continue
        if not filing.fileable(f):
            print("  起票しない  %s（%s）は論点ではありません。既存ページや規約についての指摘です。"
                  % (fid, f["check"]))
            bad += 1
            continue
        p = filing.plan(proj, f)
        if not p:
            print("  起票しない  %s の元になるグリッド／仕様が見つかりません" % fid)
            bad += 1
            continue
        path, err = filing.write(proj, p, model.today(), taken)
        if err:
            print("  見送り  %s  %s" % (fid, err))
            bad += 1
            continue
        taken.add(p["id"])
        print("  起票  %s  %s" % (p["id"], path))
        if p["hint"]:
            print("        仕様の @undecided の先頭にこの ID を書いてください: %s" % p["hint"])
    if len(taken):
        print("\n起票 %d 件。owner と前提を書き足してから reqmap recalc を実行してください。" % len(taken))
    return 1 if bad else 0


# ── show（1論点の全部） ──────────────────────────────────────
def cmd_show(root, args):
    """1論点について機械が知っている事実を全部出す。定例前の下調べと、質問文の材料。"""
    proj = model.Project(root)
    ref = " ".join(a for a in args if not a.startswith("--")).strip()
    iid = proj.resolve(ref) if ref else None
    if not iid:
        print("見つかりません: %s" % (ref or "（ID を指定してください）"))
        return 1
    it = proj.items[iid]
    out = gaps.run(proj)
    an, res = out["analysis"], out["analysis"]["result"]
    r = res[iid]
    st = lambda i: proj.items[i]["raw_status"] or proj.items[i]["status"]
    L = ["# %s  %s" % (iid, it["title"]),
         "  %s / %s / 領域 %s / 相手 %s / 重要度 %s / %s"
         % (it["kind"], st(iid), it["area"] or "—", it["owner"] or "—", it["severity"], it["file"]),
         "■ 日付と影響度",
         "  出す %s  回答が要る %s  応答日数 %d 日（%s）  止めてる %d  変えたら再検討 %d  深さ %d  優先度 %s%s"
         % (r["ask_by"] or "—", r["need_by"] or "—", r["resp_days"], r["resp_source"],
            r["blocks_count"], r["impact_count"], r["depth"], r["priority"],
            "" if r["ready"] else "  ※前提待ち")]
    L.append("■ 前提（これが先）")
    ups, bad = proj.prereqs(it)
    for u in ups:
        L.append("  blocks      %s  [%s] %s" % (u, st(u), proj.items[u]["title"]))
    for b in bad:
        L.append("  blocks      %s  （未解決の参照）" % b)
    for kind in ("derives", "constrains", "conflicts"):
        for ref_ in it["typed"][kind]:
            u = proj.resolve(ref_)
            L.append("  %-11s %s  %s" % (kind, u or ref_,
                                         "[%s] %s" % (st(u), proj.items[u]["title"]) if u else "（未解決の参照）"))
    if len(L) == 5:
        L.append("  なし")
    L.append("■ 下流（これを待っている）")
    downs = an["edges"].get(iid, [])
    for v, k in sorted(downs, key=lambda x: (x[1], x[0])):
        L.append("  %-11s %s  [%s] %s" % (k, v, st(v), proj.items[v]["title"]))
    if not downs:
        L.append("  なし")
    L.append("■ 紐付け（cells）")
    L += ["  %s" % c for c in it["cells"]] or ["  なし"]
    m = turns.metrics(it)
    L.append("■ やりとり（log）  出した %d 回 / 返答 %d 回 / ひっくり返り %d 回 / 実測 %s%s"
             % (m["ask_count"], m["answer_count"], m["reopen_count"],
                ("%d 日" % m["measured_days"]) if m["measured_days"] is not None else "なし",
                (" / 返事待ち %d 日" % m["waiting_days"]) if m["waiting_days"] is not None else ""))
    for e in it["log"]:
        L.append("  %s %s%s" % (e["date"] or "?", e["kind"] or "（読めない行）",
                                (" | " + e["note"]) if e["note"] else ""))
    if not it["log"]:
        L.append("  なし")
    a = it["assumption"] or {}
    if a:
        L.append("■ 仮置き")
        L.append("  %s  期限 %s  検証 %s  影響 %s" % (a.get("text") or "", a.get("expires") or "—",
                                                    a.get("validate_by") or "—", a.get("impact") or "—"))
    rel_spec = []
    for sp in fsl.load_specs(proj):
        if any(proj.resolve(x) == iid for x in sp["src"]["depends_on"]):
            rel_spec.append("  %s  @depends_on" % sp["file"])
        for u in sp["src"]["undecided"]:
            if fsl._ref(proj, u["reason"]) == iid:
                rel_spec.append("  %s  %s（%d 行）@undecided" % (sp["file"], u["decl"], u["line"]))
    if rel_spec:
        L.append("■ 仕様側の関連")
        L += rel_spec
    mine = [f for f in out["findings"]
            if iid in (f["target"].get("item"), f["target"].get("upstream"), f["target"].get("pending"),
                       f["target"].get("decided")) or iid in (f["target"].get("items") or [])
            or iid in f["blocks"]]
    L.append("■ 観点（この論点に関するもの） %d 件" % len(mine))
    for f in mine[:12]:
        L.append("  [%-6s] %-26s %s" % (f["severity"], f["check"], f["question"][:90]))
    if not mine:
        L.append("  なし")
    for head in ("論点", proj.cfg.get("decision_heading", "決まったこと")):
        body = re.sub(r"<!--.*?-->", "", fm.section(it["body"], head), flags=re.S).strip()
        L.append("■ %s" % head)
        L += ["  " + x for x in body.splitlines() if x.strip()] or ["  （空）"]
    print("\n".join(L))
    return 0


# ── status（静かな点検） ─────────────────────────────────────
def cmd_status(root, args):
    """平日朝に読むもの。**静かな日は1行で終わること。長い報告は読まれない。**"""
    proj = model.Project(root)
    out = gaps.run(proj)
    res = out["analysis"]["result"]
    t, lines = model.today(), []
    waiting = {f["target"]["item"]: f for f in out["findings"]
               if f["check"] == "turn.no_response"}
    # **すでに出して返事待ちのものを「いま聞け」と言わない。**
    # 出した記録があるのに再提案されると、一覧そのものが信用されなくなる。
    out_already = {i for i, it in proj.items.items()
                   if turns.metrics(it)["waiting_days"] is not None}

    ready = sorted([(res[i]["priority"], i) for i, it in proj.items.items()
                    if it["status"] in (model.OPEN,) and res[i]["ready"]
                    and not res[i]["derived"] and i not in out_already
                    and it["kind"] not in ("area", "constraint")], reverse=True)[:5]
    # derives の上流が決まった論点は「聞く」ものではなく「書き取る」もの。
    # 「いま聞け」に混ぜると、聞かなくてよいものを相手に投げてしまう。
    derived = sorted([(res[i]["priority"], i) for i, it in proj.items.items()
                      if it["status"] in (model.OPEN,) and res[i]["ready"] and res[i]["derived"]
                      and it["kind"] not in ("area", "constraint")], reverse=True)[:5]
    if ready:
        lines.append("■ いま聞けて、いちばん効くもの（まだ出していないもの）")
        for p, i in ready:
            it, r = proj.items[i], res[i]
            late = "（出し遅れ）" if model.as_date(r["ask_by"]) and \
                model.as_date(r["ask_by"]) < t else ""
            lines.append("  出す %s%s  回答が要る %s  止めてる%-2d  %s  %s"
                         % (r["ask_by"] or "?", late, r["need_by"] or "?",
                            r["blocks_count"], i, it["title"][:34]))

    if derived:
        lines.append("■ 上流が決まったので機械的に決められるもの（聞かなくてよい） %d 件" % len(derived))
        for p, i in derived:
            lines.append("  書き取る  %s  %s" % (i, proj.items[i]["title"][:34]))

    if waiting:
        lines.append("■ 出したまま返事が来ていない %d 件" % len(waiting))
        for i, f in sorted(waiting.items(), key=lambda x: -x[1]["target"]["days"])[:4]:
            lines.append("  %3d日待ち（想定%d日）  %s  %s"
                         % (f["target"]["days"], f["target"]["expected"], i,
                            proj.items[i]["title"][:30]))

    hot = [f for f in out["findings"] if f["severity"] == "high"
           and f["kind"] in ("stale_assumption", "unsound_decision", "conflict", "churn",
                             "contradiction", "spec_error", "stale_undecided")]
    if hot:
        lines.append("■ 前提が崩れかけているもの %d 件" % len(hot))
        for f in hot[:4]:
            lines.append("  %s" % f["question"][:100])

    late = sorted([(res[i]["need_by"], i) for i, it in proj.items.items()
                   if it["status"] in ACTIVE and res[i]["need_by"]
                   and model.as_date(res[i]["need_by"]) < t])
    if late:
        lines.append("■ 期限超過 %d 件" % len(late))
        for d, i in late[:5]:
            lines.append("  %s  %s  %s" % (d, i, proj.items[i]["title"][:34]))

    rules = [f for f in out["findings"] if f["kind"] == "rule"]
    if rules:
        lines.append("■ 規約違反 %d 件（reqmap recalc --check で詳細）" % len(rules))

    # 承認待ちの提案。_changesets/ を自分で見に行かないと分からない、では溜まる。
    pend = {changeset.HUMAN: 0, changeset.BLOCKED: 0}
    for f in changeset.changesets(proj):
        try:
            for r in changeset.review(proj, f)[1]:
                if r["gate"] in pend:
                    pend[r["gate"]] += 1
        except Exception:
            pass
    if pend[changeset.HUMAN] or pend[changeset.BLOCKED]:
        lines.append("■ 承認待ちの提案  確認が要る %d 件 / 動かせない %d 件"
                     " （reqmap review で詳細）"
                     % (pend[changeset.HUMAN], pend[changeset.BLOCKED]))

    fseen = seen.findings_seen(proj)
    if fseen:
        n = len([f for f in out["findings"] if f["id"] not in fseen["ids"]])
        if n:
            lines.append("■ 前回見たときから新しく出た観点 %d 件（reqmap gaps --new）" % n)
    dseen = seen.decisions_seen(proj)
    if dseen:
        rew, add, _ = decisions.changed(proj, dseen["decisions"])
        if rew or add:
            lines.append("■ 決定の変化  書き換わった %d 件 / 新しく決まった %d 件"
                         "（reqmap changes）" % (len(rew), len(add)))
            for x in rew[:3]:
                lines.append("  書き換わり  %-10s %s" % (x["id"], x["title"][:34]))

    if not lines:
        if "--quiet" not in args:
            print("動くものはありません。")
        return 0
    print("%s  点検  %s" % (proj.cfg.get("name") or "", t.isoformat()))
    print("\n".join(lines))
    return 0


def cmd_changes(root, args):
    """**前回あなたが見たときから書き換わった決定**を出す。何も書かない。

    設計を各自がAIと進めるなら、困るのは「どの設計書が古いか」ではなく
    **決定が変わったことに誰も気づかない**こと。ここを見れば、自分の設計に効くかは
    自分で判断できる。設計側に記帳は要らない。"""
    proj = model.Project(root)
    if "--ack" in args:
        snap = decisions.snapshot(proj)
        seen.save_decisions_seen(proj, snap)
        print("決定 %d 件を「見た」として記録しました。次からは書き換わった決定だけが出ます。" % len(snap))
        return 0
    base = seen.decisions_seen(proj)
    if not base:
        print("基準がありません。まず `reqmap changes --ack` で「ここまで見た」を記録してください。")
        return 1
    rew, add, gone = decisions.changed(proj, base["decisions"])
    print("# 決定の変化  %s 以降  (%s)" % (base["at"], model.today().isoformat()))
    if not (rew or add or gone):
        print("  書き換わった決定はありません。")
        return 0
    if rew:
        print("\n■ 中身が書き換わった決定 %d 件 — **自分の設計に効くか確かめてください**" % len(rew))
        for x in rew:
            print("  %-10s [%s] %s" % (x["id"], x["status"], x["title"][:40]))
            print("             指紋 %s → %s" % (x["was"], x["now"]))
    if add:
        print("\n■ 新しく決まった／仮決定になった %d 件" % len(add))
        for x in add:
            print("  %-10s [%s] %s" % (x["id"], x["status"], x["title"][:40]))
    if gone:
        print("\n■ 決定から外れた %d 件（再オープン・取下げ）" % len(gone))
        for x in gone:
            print("  %-10s [%s] %s" % (x["id"], x["status"], x["title"][:40]))
    print("\n見終わったら `reqmap changes --ack` で基準を進めてください。")
    return 0


def cmd_doctor(root, args):
    """**この vault をちゃんと読めているか**を点検する。観点は出さない。

    読めていないものを黙って捨てると、点検が不完全なまま「異常なし」に見える。
    立ち上げ直後と、スキーマを触ったあとに実行する。"""
    proj = model.Project(root)
    ok, warn = [], []

    ok.append("論点 %d 件を読み込みました" % len(proj.items))
    for rel, why in proj.unreadable:
        warn.append("読めないページ: %s（%s）" % (rel, why))
    for dup, a, b in proj.duplicates:
        warn.append("ID重複: %s（%s / %s）" % (dup, a, b))

    for key in ("questions_dir", "models_dir"):
        d = os.path.join(proj.root, str(proj.cfg[key]))
        (ok if os.path.isdir(d) else warn).append(
            "%s: %s" % (key, proj.cfg[key] if os.path.isdir(d)
                        else "%s が見つかりません" % proj.cfg[key]))

    # 語が効いているかを見る。ただし**論点がまだ無い領域でヒットしないのは当然**なので、
    # 「その領域に論点がそれなりにあるのに、行の語が1件も当たらない」だけを拾う。
    # それは語の問題で、既にある論点を「真の空白」として出してしまう原因になる。
    # 列は、まだ誰も触れていないから当たらない、が正常なので対象にしない。
    MIN = 3
    items = list(proj.items.values())
    for g in gaps.load_grids(proj):
        scope = [it for it in items
                 if (not g["area"] or it["area"] == g["area"])
                 and not model.is_aggregator(it)]
        noword = [l for _, l, w in g["rows"] if not w]
        if noword:
            warn.append("%s: 語が書かれていない行 %s（候補が出ないため常に空白になります）"
                        % (g["id"], "・".join(noword[:3])))
        if len(scope) < MIN:
            ok.append("%s: 対象領域の論点が %d 件なので語の点検は省略（%d 件から）"
                      % (g["id"], len(scope), MIN))
            continue
        dead = [l for _, l, w in g["rows"]
                if w and not any(any(x in it["title"] for x in w) for it in scope)]
        if dead:
            warn.append("%s: 論点が %d 件あるのに語が1件も当たらない行 — %s"
                        % (g["id"], len(scope), "・".join(dead)))
        else:
            ok.append("%s: 行の語はすべて既存論点に当たっています" % g["id"])

    # FSL 仕様。fslc が無い／読めない仕様は、観点が出ない原因なので先に言う。
    specs = fsl.load_specs(proj)
    if specs:
        tool = fsl.fslc_path()
        if not tool:
            warn.append("fslc が見つかりません。FSL 仕様 %d 本の検査を省略します"
                        "（入れ方: https://github.com/ymm-oss/fsl）" % len(specs))
        else:
            import subprocess
            v = subprocess.run([tool, "--version"], capture_output=True, text=True).stdout.strip()
            ok.append("%s を使います" % (v or "fslc"))
            for sp in specs:
                if sp["src"]["legacy"]:
                    warn.append("%s: fslc の仕様として読めません（jssm 形式の旧ファイル？）。"
                                "requirements 方言に書き換えてください" % sp["file"])
                    continue
                chk = fsl.run_fslc(["check", sp["path"]], proj.root)
                if chk.get("result") == "error" and chk.get("kind") not in ("forbidden", "acceptance"):
                    warn.append("%s: fslc で読めません（%s）: %s"
                                % (sp["file"], chk.get("kind"), str(chk.get("message"))[:80]))
                    continue
                ker = fsl.run_fslc(["kernel", sp["path"]], proj.root)
                procs = fsl.processes(ker) if ker.get("actions") is not None else []
                if not procs:
                    warn.append("%s: process が見つからず、状態×イベントの表を組めません"
                                "（fslc の検証だけが効きます）" % sp["file"])
                else:
                    ok.append("%s: 状態 %d・遷移 %d%s"
                              % (sp["file"], sum(len(p["stages"]) for p in procs),
                                 sum(len(p["trans"]) for p in procs),
                                 "（%s %s が受理される。gaps で詳細）"
                                 % (chk.get("kind"), chk.get("id")) if chk.get("result") == "error" else ""))
                for u in sp["src"]["undecided"]:
                    if fsl._ref(proj, u["reason"]) is None:
                        warn.append("%s: @undecided『%s』の先頭に論点IDがありません"
                                    % (sp["file"], u["reason"][:30]))

    t = turns.summary(proj)
    if t["total"]:
        ok.append("やりとりの記録がある論点 %d/%d 件・往復の実測 %d 回%s"
                  % (t["with_log"], t["total"], t["round_trips"],
                     "（中央値 %d 日）" % t["median_days"] if t["median_days"] else ""))
        if not t["round_trips"]:
            warn.append("やりとりの実測が1件もありません。"
                        "log: に `YYYY-MM-DD asked` と `answered` を書くと、"
                        "回答日数が仮置きから実測に変わります")

    cs = changeset.changesets(proj)
    if cs:
        ok.append("Change Set %d 本（reqmap review で点検できます）" % len(cs))

    print("# 点検  %s" % (proj.cfg.get("name") or os.path.basename(proj.root)))
    for l in ok:
        print("  OK   %s" % l)
    for l in warn:
        print("  ⚠    %s" % l)
    if not warn:
        print("\n読み落としはありません。")
    else:
        print("\n⚠ は**観点が出ない原因**になります。先に直してください。")
    return 0


def _jsonable(o):
    """json.dumps の default。log の日付は date で持っているので ISO 文字列にする。"""
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


# ── ci（PR を止める） ────────────────────────────────────────
def cmd_ci(root, args):
    """ゲートに当たる観点があれば exit 1。**観点の多さでは止めない。** 止めるのは矛盾と「読めていない」。

    仕様があるのに fslc が無いのも NG にする。黙って省略すると、通ったように見えて
    状態遷移は何も検査されていない。--allow-missing-fslc で許せる。"""
    proj = model.Project(root)
    out = gaps.run(proj)
    gate = set(proj.cfg.get("ci_gate") or [])
    if "--allow-missing-fslc" not in args:
        gate.add("fsl.tool_missing")
    ng = [f for f in out["findings"] if f["check"] in gate]
    name = proj.cfg.get("name") or os.path.basename(proj.root)
    print("# CI ゲート  %s  (%s)" % (name, out["generated_at"]))
    if not ng:
        print("  通過。観点は %d 件あります（reqmap gaps で）。" % len(out["findings"]))
        return 0
    for f in ng:
        print("  NG  %-24s %s" % (f["check"], f["question"][:110]))
    by = {}
    for f in ng:
        by[f["check"]] = by.get(f["check"], 0) + 1
    print("\nゲート NG %d 件（%s）" % (len(ng), " / ".join("%s %d" % kv for kv in sorted(by.items()))))
    return 1


def cmd_json(root, args):
    proj = model.Project(root)
    out = gaps.run(proj)
    an = out.pop("analysis")
    out["items"] = {i: dict(proj.items[i], body="", fm={}, **an["result"][i])
                    for i in proj.items}
    out["edges"] = [{"from": u, "to": v, "kind": k}
                    for u, outs in an["edges"].items() for v, k in outs]
    out["areas"] = proj.areas
    out["project"] = proj.cfg.get("name") or os.path.basename(proj.root)
    out["milestone"] = str(proj.cfg.get("milestone") or "")
    dest = os.path.join(proj.root, proj.cfg["out_dir"], "reqmap.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, indent=2, default=_jsonable)
    open(dest, "w", encoding="utf-8").write(text)
    if "--stdout" in args:
        print(text)
    else:
        print(dest)
    return 0


def cmd_view(root, args):
    from . import view
    return view.build(root, args)


def _sets(proj, args):
    """指定が無ければ _changesets/ 全部。指定があれば cwd 基準でもルート基準でも受ける。"""
    given = [a for a in args if a.endswith(".yml")]
    if not given:
        return changeset.changesets(proj), []
    found, missing = [], []
    for f in given:
        for cand in (f, os.path.join(proj.root, f),
                     os.path.join(proj.root, "_changesets", os.path.basename(f))):
            if os.path.exists(cand):
                found.append(os.path.abspath(cand))
                break
        else:
            missing.append(f)
    return found, missing


def cmd_review(root, args):
    proj = model.Project(root)
    files, missing = _sets(proj, args)
    for m in missing:
        print("見つかりません: %s" % m)
    if not files:
        if not missing:
            print("_changesets/ に Change Set がありません。")
        return 1 if missing else 0
    total = {changeset.AUTO: 0, changeset.HUMAN: 0, changeset.BLOCKED: 0,
             changeset.APPLIED: 0}
    for f in files:
        meta, rows = changeset.review(proj, f)
        print("■ %s  ← %s  (%d件)"
              % (os.path.relpath(f, proj.root), meta.get("source") or "?", len(rows)))
        for r in rows:
            total[r["gate"]] += 1
            c = r["change"]
            print("  [%-7s] %s  %s" % (r["gate"], c.get("id") or "?", c.get("title") or ""))
            for why in r["reasons"]:
                print("            - %s" % why)
        print()
    print("auto %d / human %d / blocked %d / 反映済み %d"
          % (total[changeset.AUTO], total[changeset.HUMAN], total[changeset.BLOCKED],
             total[changeset.APPLIED]))
    if total[changeset.BLOCKED]:
        print("\n**blocked は適用されません。** 引用が原文に無いものは、"
              "モデルが作文した可能性があります。原文を確認してください。")
    return 0


def cmd_apply(root, args):
    proj = model.Project(root)
    approve = set()
    for a in args:
        if a.startswith("--approve="):
            approve |= {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
    dry = "--dry-run" in args
    files, missing = _sets(proj, args)
    for m in missing:
        print("見つかりません: %s" % m)
    if missing and not files:
        return 1
    written, skipped = [], []
    for f in files:
        meta, rows = changeset.review(proj, f)
        for r in rows:
            c, g = r["change"], r["gate"]
            cid = str(c.get("id") or "?")
            if g == changeset.APPLIED:
                continue
            if g == changeset.BLOCKED:
                skipped.append((cid, "blocked: " + "; ".join(r["reasons"])))
                continue
            if g == changeset.HUMAN and cid not in approve:
                skipped.append((cid, "human: 確認が要る（--approve=%s で適用）" % cid))
                continue
            if c.get("op") != "create":
                skipped.append((cid, "op=%s は機械が書き換えません。ページを直接直してください"
                                % c.get("op")))
                continue
            if dry:
                written.append((cid, "(dry-run)"))
                continue
            path, err = changeset.apply_one(proj, c, meta)
            (skipped if err else written).append((cid, err or path))
    for cid, p in written:
        print("  書いた  %s  %s" % (cid, p))
    for cid, why in skipped:
        print("  見送り  %s  %s" % (cid, why))
    print("\n適用 %d 件 / 見送り %d 件" % (len(written), len(skipped)))
    if written and not dry:
        print("次: reqmap recalc で影響度と期日を計算してください。")
    return 0


CMDS = {"init": cmd_init, "review": cmd_review, "apply": cmd_apply, "ci": cmd_ci, "show": cmd_show,
        "doctor": cmd_doctor, "changes": cmd_changes, "recalc": cmd_recalc, "gaps": cmd_gaps,
        "status": cmd_status, "view": cmd_view, "json": cmd_json}


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv.pop(0)
    if cmd not in CMDS:
        print("不明なコマンド: %s\n" % cmd + __doc__)
        return 2
    root = os.environ.get("REQMAP_ROOT", ".")
    rest = []
    for a in argv:
        if a.startswith("--root="):
            root = a.split("=", 1)[1]
        else:
            rest.append(a)
    if cmd == "init" and rest and not rest[0].startswith("--"):
        root = rest.pop(0)
    return CMDS[cmd](root, rest)
