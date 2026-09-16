# reqmap × fslc 連携と欠陥修正 — 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 評価で出た9項目の推奨案（fslc 連携、conflicts、逆算式、循環の局所化、derives、引用ゲート、基準の分離、バグ・残骸、テスト）を実装し、reqmap を「fslc が検証し、reqmap が問う」ハーネスにする。

**Architecture:** 検証は fslc の CLI（`check` / `kernel` / `verify`）に任せ、新モジュール `scripts/reqmap/fsl.py` がその JSON を確認観点（findings）に写す。状態×イベントの引き出し表は `fslc kernel` の構造から組む。reqmap 固有のメタデータはコメント指令と、fslc が無視する `@reqmap.event(...)` / `@undecided(...)` 注釈を原文から読む。既存の jssm パーサは削除する。

**Tech Stack:** Python 3 標準ライブラリのみ（unittest でテスト）。外部は `fslc` バイナリ（任意。無ければ観点1件を出して省略）。

**Spec:** `docs/superpowers/specs/2026-09-16-fslc-integration-design.md`

## Global Constraints

- 外部依存なし（PyYAML も pytest も使わない。テストは `python3 -m unittest discover -s tests`）。
- 機械が書く frontmatter キーは7つだけ（`blocks_count` `blocking` `impact_count` `ready` `depth` `need_by` `ask_by`）。`status` `decision` `severity` には触らない。
- 観点 ID は内容ハッシュ。`target` は JSON 化できる素の dict にする。
- 出しすぎない。正常な状態（open な論点に紐付いた undecided など）は観点にしない。
- コミットは利用者が判断する。この計画ではコミットしない。
- 文体は既存ドキュメントに合わせる（「なぜ」を先に、太字で要点）。

---

### Task 1: テスト基盤と `reqmap json` のクラッシュ修正

**Files:**
- Create: `tests/__init__.py`（空）
- Create: `tests/helpers.py`
- Create: `tests/test_cli_json.py`
- Modify: `scripts/reqmap/cli.py`（`cmd_json`）

**Interfaces:**
- Produces: `helpers.make_vault(tmpdir, milestone, areas, extra_cfg) -> root`, `helpers.page(root, id, title, **fields) -> path`。以後の全テストがこれを使う。

- [x] **Step 1: ヘルパを書く**

```python
# tests/helpers.py
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

CLI = os.path.join(ROOT, "scripts", "reqmap-cli")
EXAMPLE = os.path.join(ROOT, "examples", "takeout-app")


def make_vault(root, milestone="2026-10-31",
               areas=("A-01 | 領域1 | high", "A-02 | 領域2 | medium"), extra_cfg=""):
    os.makedirs(os.path.join(root, "questions"), exist_ok=True)
    os.makedirs(os.path.join(root, "models", "grids"), exist_ok=True)
    os.makedirs(os.path.join(root, "models", "fsl"), exist_ok=True)
    cfg = ["name: テスト", "milestone: %s" % milestone, "response_days_default: 14",
           "response_days:", "  クライアント: 14", "  自社: 0", "areas:"]
    cfg += ["  - %s" % a for a in areas]
    if extra_cfg:
        cfg.append(extra_cfg)
    with open(os.path.join(root, "reqmap.yml"), "w", encoding="utf-8") as f:
        f.write("\n".join(cfg) + "\n")
    return root


def page(root, pid, title, area="A-01", status="open", owner="クライアント",
         severity="medium", kind="question", prereqs=(), derives=(), constrains=(),
         conflicts=(), decision="", log=(), cells=(), extra_fm="", due=""):
    d = os.path.join(root, "questions", area)
    os.makedirs(d, exist_ok=True)
    fm = ["id: %s" % pid, "title: %s" % title, "kind: %s" % kind, "status: %s" % status,
          "area: %s" % area, "owner: %s" % owner, "severity: %s" % severity,
          "due: %s" % due, "lead_time_days: 0"]
    for key, vals in (("cells", cells), ("derives", derives),
                      ("constrains", constrains), ("conflicts", conflicts), ("log", log)):
        fm.append("%s:" % key if vals else "%s: []" % key)
        fm += ["  - %s" % v for v in vals]
    if extra_fm:
        fm.append(extra_fm)
    body = ["## 前提", ""] + (["- [[%s]]" % p for p in prereqs] or ["- なし"])
    body += ["", "## 論点", "", "## 決まったこと", "", decision, ""]
    path = os.path.join(d, "%s.md" % pid)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(fm) + "\n---\n\n" + "\n".join(body))
    return path
```

- [x] **Step 2: 失敗するテストを書く**

```python
# tests/test_cli_json.py
import json
import os
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


class JsonTest(unittest.TestCase):
    def test_json_serialises_log_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A", log=["2026-09-01 asked | 定例"])
            r = subprocess.run([CLI, "json", "--stdout", "--root=%s" % tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["items"]["a"]["log"][0]["date"], "2026-09-01")
```

- [x] **Step 3: 落ちることを確認** — `python3 -m unittest tests.test_cli_json -v`（`TypeError: Object of type date` で失敗）

- [x] **Step 4: 直す** — `cli.py` の `cmd_json` で `json.dumps(..., default=_jsonable)`。

```python
def _jsonable(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    return str(o)
```

- [x] **Step 5: 通ることを確認** — `python3 -m unittest tests.test_cli_json -v`

---

### Task 2: 逆算式・循環の局所化・メモ化・`derived`（graph.py）

**Files:**
- Modify: `scripts/reqmap/graph.py`（`analyse`、新関数 `scc_cycle_nodes`）
- Modify: `scripts/reqmap/cli.py`（`cmd_recalc` の告知）
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `graph.scc_cycle_nodes(edges, kinds=("blocks","derives")) -> set`、`analyse()` の戻りに `"cycle_nodes": sorted(set)`、`result[i]["derived"]: bool`。

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_graph.py
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import graph, model


class BackCalcTest(unittest.TestCase):
    def test_upstream_deadline_uses_downstream_response_days(self):
        # a（自社・0日）が b（クライアント・14日）を止める。期限 10-31。
        # b は 10-17 に出す必要がある → a はそれまでに決まっていなければならない。
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A", owner="自社")
            page(tmp, "b", "B", owner="クライアント", prereqs=["a"])
            r = graph.analyse(model.Project(tmp))["result"]
            self.assertEqual(r["b"]["ask_by"], "2026-10-17")
            self.assertEqual(r["a"]["need_by"], "2026-10-17")
            self.assertEqual(r["a"]["ask_by"], "2026-10-17")


class CycleTest(unittest.TestCase):
    def test_cycle_only_affects_its_own_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "x", "X", prereqs=["y"])
            page(tmp, "y", "Y", prereqs=["x"])
            page(tmp, "up", "UP", owner="クライアント")
            page(tmp, "down", "DOWN", owner="クライアント", prereqs=["up"])
            an = graph.analyse(model.Project(tmp))
            self.assertEqual(an["cycle_nodes"], ["x", "y"])
            r = an["result"]
            self.assertEqual(r["down"]["depth"], 1)
            self.assertEqual(r["up"]["need_by"], "2026-10-17")

    def test_scc_finds_node_reachable_only_via_cross_edge(self):
        # r→x, x→r, r→y, y→x: y は循環上にあるが DFS の back-edge 経路には出ない
        edges = {"r": [("x", "blocks"), ("y", "blocks")], "x": [("r", "blocks")],
                 "y": [("x", "blocks")]}
        self.assertEqual(graph.scc_cycle_nodes(edges), {"r", "x", "y"})


class DerivedTest(unittest.TestCase):
    def test_derived_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "d", "D", derives=["c"])
            page(tmp, "e", "E")
            r = graph.analyse(model.Project(tmp))["result"]
            self.assertTrue(r["d"]["derived"])
            self.assertTrue(r["d"]["ready"])
            self.assertFalse(r["e"]["derived"])
```

- [x] **Step 2: 落ちることを確認** — `python3 -m unittest tests.test_graph -v`

- [x] **Step 3: 実装**

`graph.py` に追加:

```python
def scc_cycle_nodes(edges, kinds=("blocks", "derives")):
    """循環に乗っている節の集合（Tarjan の強連結成分。大きさ2以上か自己ループ）。

    cycles() が返す経路の和では足りない。DFS の back-edge から見つかる経路には、
    交差辺だけで循環に参加している節が出てこないことがある。"""
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
```

`analyse()` を書き換え（要点）:

```python
    cyc = scc_cycle_nodes(edges)
    ...
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

    # 逆算: 上流 i は、下流 v を出す日（need_by(v) − v の応答日数）より
    # 自分の lead_time だけ前に決まっていなければならない。
    # 引くのは **下流** の応答日数。上流自身の日数を引くと、上下で日数が違うとき
    # 上流の期限が下流を出す日より後ろにずれる。
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
    ...
    return {"edges": edges, "up_of": up_of, "dangling": dangling,
            "cycles": cycles(edges), "cycle_nodes": sorted(cyc), "result": res}
```

`cli.py` の `cmd_recalc`: `an["cycle_nodes"]` があれば
`"循環 %d 本。%s は循環のため depth / need_by が初期値です（先にどれかを仮決定してください）"` を出す。

- [x] **Step 4: 通ることを確認** — `python3 -m unittest tests.test_graph -v`

---

### Task 3: `conflicts` の検出（gaps.py）

**Files:**
- Modify: `scripts/reqmap/gaps.py`（`graph_checks`）
- Test: `tests/test_gaps_graph.py`

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_gaps_graph.py
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import gaps, model


def checks(root):
    return [f["check"] for f in gaps.run(model.Project(root))["findings"]]


class ConflictTest(unittest.TestCase):
    def test_both_decided_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "e", "E", status="decided", decision="Yにする。", conflicts=["c"])
            self.assertIn("graph.conflict", checks(tmp))

    def test_one_decided_marks_the_other_as_drop_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "e", "E", conflicts=["c"])
            cs = checks(tmp)
            self.assertIn("graph.conflict_pending", cs)
            self.assertNotIn("graph.conflict", cs)

    def test_both_open_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C")
            page(tmp, "e", "E", conflicts=["c"])
            self.assertNotIn("graph.conflict", checks(tmp))
            self.assertNotIn("graph.conflict_pending", checks(tmp))
```

- [x] **Step 2: 落ちることを確認** — `python3 -m unittest tests.test_gaps_graph -v`

- [x] **Step 3: 実装** — `graph_checks` の item ループの前に `seen_pairs = set()`、ループ内に:

```python
        # 両立しない（conflicts）。両方決まっていれば矛盾。片方だけなら、もう片方は取下げ候補。
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
```

- [x] **Step 4: 通ることを確認**

---

### Task 4: `derives` を status に反映（cli.py）

**Files:**
- Modify: `scripts/reqmap/cli.py`（`cmd_status`）
- Modify: `scripts/reqmap/view.py`（順位表に「従属」ピル）
- Test: `tests/test_cli_status.py`

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_cli_status.py
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


def status(root):
    r = subprocess.run([CLI, "status", "--root=%s" % root], capture_output=True, text=True)
    return r.stdout


class DerivesTest(unittest.TestCase):
    def test_derived_item_is_not_proposed_as_a_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "d", "Dは機械的に従属", derives=["c"])
            out = status(tmp)
            self.assertIn("機械的に決められるもの", out)
            head = out.split("機械的に決められるもの")[0]
            self.assertNotIn("Dは機械的に従属", head)
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — `cmd_status` の `ready` から `res[i]["derived"]` を除外し、新セクション:

```python
    derived = sorted([(res[i]["priority"], i) for i, it in proj.items.items()
                      if it["status"] == model.OPEN and res[i]["ready"] and res[i]["derived"]],
                     reverse=True)[:5]
    if derived:
        lines.append("■ 上流が決まったので機械的に決められるもの（聞かなくてよい） %d 件" % len(derived))
        for p, i in derived:
            lines.append("  書き取る  %s  %s" % (i, proj.items[i]["title"][:34]))
```

`view.py` の順位表: `r.derived ? ' <span class="pill">従属</span>' : ''`。

- [x] **Step 4: 通ることを確認**

---

### Task 5: 引用ゲートの補強（changeset.py）

**Files:**
- Modify: `scripts/reqmap/changeset.py`（`classify`）
- Modify: `scripts/reqmap/model.py`（`DEFAULTS["quote_min_chars"] = 12`、`design_dirs` と `covers` を削除）
- Modify: `templates/reqmap.yml`（`quote_min_chars`）
- Test: `tests/test_changeset.py`

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_changeset.py
import os
import tempfile
import unittest

from helpers import make_vault
from reqmap import changeset, model

SRC = "田中様: 決まっていません。\n佐藤様: 次回までに整理してお送りします。\n田中様: 次回までに整理してお送りします。\n"


class QuoteGateTest(unittest.TestCase):
    def _proj(self, tmp):
        make_vault(tmp)
        os.makedirs(os.path.join(tmp, "sources"))
        with open(os.path.join(tmp, "sources", "m.md"), "w", encoding="utf-8") as f:
            f.write(SRC)
        return model.Project(tmp)

    def test_short_quote_is_raised_to_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = self._proj(tmp)
            g, why = changeset.classify(
                {"op": "create", "id": "x", "title": "X", "quote": "決まっていません。"}, proj, SRC)
            self.assertEqual(g, changeset.HUMAN)
            self.assertTrue(any("短" in w for w in why))

    def test_ambiguous_quote_is_raised_to_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = self._proj(tmp)
            g, why = changeset.classify(
                {"op": "create", "id": "x", "title": "X",
                 "quote": "次回までに整理してお送りします。"}, proj, SRC)
            self.assertEqual(g, changeset.HUMAN)
            self.assertTrue(any("複数回" in w for w in why))

    def test_missing_quote_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = self._proj(tmp)
            g, _ = changeset.classify(
                {"op": "create", "id": "x", "title": "X", "quote": "原文に無い一文です。"}, proj, SRC)
            self.assertEqual(g, changeset.BLOCKED)
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — `classify` の `verify_quote` 直後:

```python
    if kind != "none":
        # 照合が守るのは「その一文が原文にある」ことだけ。短い・汎用的な一文は
        # どんな title にも付けられるので、出所を特定できない引用は人に回す。
        q = _norm(chg.get("quote"))
        mn = int(proj.cfg.get("quote_min_chars") or 0)
        if mn and len(q) < mn:
            raise_to(HUMAN, "引用が短く出所を特定できない（%d 文字。%d 文字以上にする）" % (len(q), mn))
        if _norm(source_text).count(q) > 1:
            raise_to(HUMAN, "引用が原文に複数回出現し、どの発言か特定できない")
```

- [x] **Step 4: 通ることを確認**

---

### Task 6: 基準の分離（seen.py、`changes --ack`）

**Files:**
- Create: `scripts/reqmap/seen.py`
- Modify: `scripts/reqmap/cli.py`（`cmd_gaps` `cmd_status` `cmd_changes`、`_snap_*` を削除）
- Modify: `scripts/reqmap/view.py`（`decisions_seen` を使う）
- Test: `tests/test_seen.py`

**Interfaces:**
- Produces: `seen.findings_seen(proj) -> {"at","ids":set}|None`、`seen.save_findings_seen(proj, ids)`、`seen.decisions_seen(proj) -> {"at","decisions":dict}|None`（旧 `findings-seen.json` の `decisions` キーも読む）、`seen.save_decisions_seen(proj, snap)`。

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_seen.py
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


def run(*a):
    return subprocess.run([CLI] + list(a), capture_output=True, text=True).stdout


class SeenTest(unittest.TestCase):
    def test_gaps_snapshot_does_not_move_decision_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            run("changes", "--ack", "--root=%s" % tmp)
            page(tmp, "c", "C", status="decided", decision="Yに変えた。")
            run("gaps", "--snapshot", "--root=%s" % tmp)
            out = run("changes", "--root=%s" % tmp)
            self.assertIn("書き換わった決定 1 件", out)
            run("changes", "--ack", "--root=%s" % tmp)
            self.assertIn("書き換わった決定はありません", run("changes", "--root=%s" % tmp))
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装**

```python
# scripts/reqmap/seen.py
# -*- coding: utf-8 -*-
"""「前回自分が見たとき」の基準。**各自のもの**（.reqmap/ は gitignore 済み）。

基準は2つあり、進むタイミングが違う。
  findings-seen.json   観点の既読。`gaps --snapshot` で進める（定例前に週1）
  decisions-seen.json  決定の基準。`changes --ack` で進める（毎朝）
1ファイルにまとめると、片方を進めたつもりでもう片方の差分が消える。"""
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
    old = _load(_path(proj, FINDINGS))  # 旧形式（1ファイル）
    if old and old.get("decisions"):
        return {"at": old.get("at", "?"), "decisions": old["decisions"]}
    return None


def save_decisions_seen(proj, snap):
    _save(_path(proj, DECISIONS), {"at": model.today().isoformat(), "decisions": snap})
```

`cli.py`: `cmd_gaps --snapshot` は `save_findings_seen` のみ。`cmd_changes` に `--ack`（`decisions.snapshot(proj)` を保存し「決定 N 件を基準にしました」）。`cmd_status`・`view.py` は `decisions_seen` を読む。基準が無いときの案内は `reqmap changes --ack`。

- [x] **Step 4: 通ることを確認**

---

### Task 7: fsl.py（原文の指令・注釈・forbidden の読み取り、fslc の検出）

**Files:**
- Create: `scripts/reqmap/fsl.py`
- Test: `tests/test_fsl_source.py`

**Interfaces:**
- Produces: `fsl.read_source(text) -> dict` with keys `legacy: bool`, `area: str`, `depends_on: [str]`, `extra_events: [str]`, `critical: [str]`, `impossible: set((stage_lower, event_lower))`, `events: {action: event}`, `undecided: [{"decl": str, "reason": str, "line": int}]`, `forbidden: [{"id": str, "steps": [(action, arg)], "last": (action, arg)}]`。`fsl.fslc_path() -> str|None`、`fsl.run_fslc(args, cwd) -> dict`。

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_fsl_source.py
import unittest

import helpers  # noqa: F401  (sys.path)
from reqmap import fsl

SPEC = '''// @area: A-04
// @depends_on: Q-006, Q-007
// @events: refund
// @critical: cancel
// @impossible: Draft x pay   // 未送信に決済は無い
requirements OrderStatus {
  process Order {
    stages Draft, Paid, Cancelled
    initial Draft
    transition pay Draft -> Paid by Customer covers REQ-1 "支払"
    @reqmap.event("cancel")
    @undecided("Q-006 返金条件が未定")
    transition cancel_paid Paid -> Cancelled by Customer covers REQ-2 "支払後取消"
  }
  forbidden FB-1 "二重決済" {
    pay(0) pay(0)
    expect rejected
  }
}
'''


class SourceTest(unittest.TestCase):
    def test_directives(self):
        s = fsl.read_source(SPEC)
        self.assertFalse(s["legacy"])
        self.assertEqual(s["area"], "A-04")
        self.assertEqual(s["depends_on"], ["Q-006", "Q-007"])
        self.assertEqual(s["extra_events"], ["refund"])
        self.assertEqual(s["critical"], ["cancel"])
        self.assertEqual(s["impossible"], {("draft", "pay")})

    def test_annotations_attach_to_next_transition(self):
        s = fsl.read_source(SPEC)
        self.assertEqual(s["events"], {"cancel_paid": "cancel"})
        self.assertEqual(s["undecided"][0]["decl"], "transition cancel_paid")
        self.assertEqual(s["undecided"][0]["reason"], "Q-006 返金条件が未定")

    def test_forbidden_last_step(self):
        s = fsl.read_source(SPEC)
        self.assertEqual(s["forbidden"][0]["id"], "FB-1")
        self.assertEqual(s["forbidden"][0]["steps"], [("pay", "0")])
        self.assertEqual(s["forbidden"][0]["last"], ("pay", "0"))

    def test_legacy_jssm_is_detected(self):
        self.assertTrue(fsl.read_source("machine_name: x;\na 'e' -> b;\n")["legacy"])
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — `fsl.py` の前半:

```python
DIALECT = re.compile(r"^\s*(requirements|spec|business|compose|domain|governance)\s+[\w.]+\s*\{", re.M)
DIRECTIVE = re.compile(r"//\s*@(\w+)\s*:\s*(.+)")
ANNOT = re.compile(r'^\s*@([\w.]+)\s*\(\s*"([^"]*)"\s*\)')
DECL = re.compile(r"^\s*(?:fair\s+)?(transition|action|invariant|trans|reachable|leadsTo|until|unless|init|process)\b\s*([\w.]*)")
SLOT = re.compile(r'"undecided:\s*([^"]*)"')
FORBID = re.compile(r'forbidden\s+(\S+)\s+"[^"]*"\s*\{(.*?)\}', re.S)
STEP = re.compile(r"(\w+)\s*\(\s*([^,)]*)")


def read_source(text):
    out = {"legacy": not DIALECT.search(text), "area": "", "depends_on": [], "extra_events": [],
           "critical": [], "impossible": set(), "events": {}, "undecided": [], "forbidden": []}
    dv = {}
    for k, v in DIRECTIVE.findall(text):
        dv.setdefault(k, []).append(v.split("//")[0].strip())
    flat = lambda k: [x.strip() for v in dv.get(k, []) for x in v.split(",") if x.strip()]
    out["area"] = (flat("area") or [""])[0]
    out["depends_on"], out["extra_events"], out["critical"] = flat("depends_on"), flat("events"), flat("critical")
    out["impossible"] = {tuple(x.strip().lower() for x in v.split(" x ")) for v in dv.get("impossible", [])}
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
```

- [x] **Step 4: 通ることを確認**

---

### Task 8: fsl.py（kernel → プロセス構造 → 状態×イベントの観点）

**Files:**
- Modify: `scripts/reqmap/fsl.py`
- Test: `tests/test_fsl_matrix.py`

**Interfaces:**
- Produces: `fsl.processes(kernel) -> [ {"map","stages","initial","trans":[(action, from, to)]} ]`、`fsl.matrix_findings(src, proc, model_id, sev, related) -> (findings, summary)`。

- [x] **Step 1: 失敗するテストを書く**（kernel JSON は手で作った最小形）

```python
# tests/test_fsl_matrix.py
import unittest

import helpers  # noqa: F401
from reqmap import fsl


def idx(name):
    return {"kind": "index", "collection": {"kind": "var", "name": name}, "index": {"kind": "var", "name": "c"}}


def eq(name, member):
    return {"kind": "binary", "operator": "==", "left": idx(name), "right": {"kind": "var", "name": member}}


def act(name, frm, to):
    return {"name": name, "requires": [eq("order_stage", frm)],
            "updates": [{"kind": "assign", "target": {"kind": "index", "name": "order_stage",
                                                      "index": {"kind": "var", "name": "c"}},
                         "value": {"kind": "var", "name": to}}]}


KERNEL = {
    "types": [{"name": "OrderStage", "definition": {"kind": "enum",
                                                    "members": ["Draft", "Pending", "Paid", "Cancelled"]}}],
    "state": [{"name": "order_stage", "type": {"kind": "map", "value": {"kind": "named", "name": "OrderStage"}}}],
    "init": {"statements": [{"kind": "forall", "statements": [
        {"kind": "assign", "target": {"kind": "index", "name": "order_stage"}, "value": {"kind": "var", "name": "Draft"}}]}]},
    "actions": [act("submit", "Draft", "Pending"), act("pay", "Pending", "Paid"),
                act("cancel", "Pending", "Cancelled"), act("cancel_paid", "Paid", "Cancelled")],
}


class ProcessTest(unittest.TestCase):
    def test_process_extraction(self):
        p = fsl.processes(KERNEL)[0]
        self.assertEqual(p["stages"], ["Draft", "Pending", "Paid", "Cancelled"])
        self.assertEqual(p["initial"], "Draft")
        self.assertIn(("pay", "Pending", "Paid"), p["trans"])


class MatrixTest(unittest.TestCase):
    def _run(self, src):
        s = dict(fsl.read_source(""), **src)
        return fsl.matrix_findings(s, fsl.processes(KERNEL)[0], "fsl/order", "medium", [])

    def test_adjacent_holes_and_event_grouping(self):
        F, summ = self._run({"events": {"cancel_paid": "cancel"}})
        cells = {(f["target"]["state"], f["target"]["event"]) for f in F if f["check"] == "fsl.state_event_hole"}
        self.assertIn(("Paid", "pay"), cells)          # 二重決済
        self.assertIn(("Pending", "submit"), cells)    # 二重送信
        self.assertNotIn(("Paid", "cancel"), cells)    # cancel_paid が cancel イベントとして定義済み
        self.assertNotIn(("Draft", "cancel"), cells)   # 隣接だが… Draft は Pending の隣なので出る
        self.assertEqual(summ["events"], 3)

    def test_critical_event_is_asked_everywhere(self):
        F, _ = self._run({"critical": ["pay"]})
        cells = {(f["target"]["state"], f["target"]["event"]) for f in F if f["check"] == "fsl.state_event_hole"}
        self.assertIn(("Draft", "pay"), cells)

    def test_forbidden_covers_a_cell(self):
        F, _ = self._run({"forbidden": [{"id": "FB-1", "steps": [("submit", "0"), ("pay", "0")], "last": ("pay", "0")}]})
        cells = {(f["target"]["state"], f["target"]["event"]) for f in F if f["check"] == "fsl.state_event_hole"}
        self.assertNotIn(("Paid", "pay"), cells)

    def test_unused_event_and_unreachable_stage(self):
        k = dict(KERNEL, actions=KERNEL["actions"][:2])  # Cancelled に入る遷移が無い
        s = dict(fsl.read_source(""), extra_events=["refund"])
        F, _ = fsl.matrix_findings(s, fsl.processes(k)[0], "fsl/order", "medium", [])
        self.assertIn("fsl.unused_event", [f["check"] for f in F])
        self.assertIn("fsl.unreachable_stage", [f["check"] for f in F])
```

注意: `test_adjacent_holes_and_event_grouping` の Draft × cancel の行は「隣接なので出る」が正しい挙動。assert は `assertIn` に直す。

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — `processes()` は kernel の `state` から `_stage` で終わる Map<_, Enum> を拾い、`init` の forall/assign から初期状態、各 action の `requires`（`==` を `or`/`and` 越しに集める）と `updates` から (from, to) を取る。`matrix_findings()` は旧 `fsm_gaps` の隣接ヒューリスティックに `critical`（全状態）、forbidden の最終ステップ（前提を遷移表でシミュレートしたマス）、`@reqmap.event` によるイベント集約を足す。到達不能な状態（initial 以外で入る遷移が無い）は `fsl.unreachable_stage`。

- [x] **Step 4: 通ることを確認**

---

### Task 9: fsl.py（check / verify → 観点、undecided の照合、統合 `gaps(proj)`）

**Files:**
- Modify: `scripts/reqmap/fsl.py`
- Test: `tests/test_fsl_run.py`（fslc が無ければ skip）

**Interfaces:**
- Produces: `fsl.load_specs(proj) -> [spec dict]`（`id`, `file`, `path`, `src`）、`fsl.gaps(proj) -> (findings, summaries)`。

- [x] **Step 1: 失敗するテストを書く**

```python
# tests/test_fsl_run.py
import os
import shutil
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import fsl, model

BASE = '''// @area: A-01
requirements OrderStatus {
  process Order {
    stages Draft, PendingPayment, Paid, Cancelled
    initial Draft
    transition submit Draft -> PendingPayment by Customer covers REQ-O-001 "送信"
    transition pay PendingPayment -> Paid by Customer covers REQ-O-002 "支払"
    transition cancel PendingPayment -> Cancelled by Customer covers REQ-O-003 "取消"
    %(extra)s
  }
  forbidden FB-O-001 "二重決済は拒否" {
    submit(0) pay(0) %(last)s(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Paid or stage(c) == Cancelled } }
}
verify {
  instances Order = 2
}
'''


def spec(root, text, name="order.fsl"):
    with open(os.path.join(root, "models", "fsl", name), "w", encoding="utf-8") as f:
        f.write(text)


def checks(root):
    F, _ = fsl.gaps(model.Project(root))
    return [f["check"] for f in F]


@unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
class RunTest(unittest.TestCase):
    def test_clean_spec_yields_only_matrix_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": "", "last": "pay"})
            cs = checks(tmp)
            self.assertIn("fsl.state_event_hole", cs)
            self.assertNotIn("fsl.forbidden_accepted", cs)
            self.assertNotIn("fsl.spec_error", cs)

    def test_later_decision_contradicting_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": 'transition repay Paid -> Paid by Customer covers REQ-O-004 "再決済"',
                              "last": "repay"})
            self.assertIn("fsl.forbidden_accepted", checks(tmp))

    def test_parse_error_is_a_spec_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, "requirements Broken {\n  process Order {\n")
            self.assertIn("fsl.spec_error", checks(tmp))

    def test_undecided_linked_to_open_question_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "Q-006", "キャンセル")
            spec(tmp, BASE % {"extra": '@undecided("Q-006 返金条件")\n    transition refund Paid -> Cancelled by Shop covers REQ-O-005 "返金"',
                              "last": "pay"})
            cs = checks(tmp)
            self.assertNotIn("fsl.stale_undecided", cs)
            self.assertNotIn("fsl.undecided_unlinked", cs)

    def test_undecided_on_decided_question_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "Q-006", "キャンセル", status="decided", decision="返金する。")
            spec(tmp, BASE % {"extra": '@undecided("Q-006 返金条件")\n    transition refund Paid -> Cancelled by Shop covers REQ-O-005 "返金"',
                              "last": "pay"})
            self.assertIn("fsl.stale_undecided", checks(tmp))

    def test_undecided_without_question_is_unlinked(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": '@undecided("返金条件が未定")\n    transition refund Paid -> Cancelled by Shop covers REQ-O-005 "返金"',
                              "last": "pay"})
            self.assertIn("fsl.undecided_unlinked", checks(tmp))

    def test_legacy_jssm_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, "machine_name: x;\na 'e' -> b;\n")
            self.assertIn("fsl.legacy_format", checks(tmp))


class NoToolTest(unittest.TestCase):
    def test_missing_fslc_is_one_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": "", "last": "pay"})
            old = fsl.fslc_path
            fsl.fslc_path = lambda: None
            try:
                cs = checks(tmp)
            finally:
                fsl.fslc_path = old
            self.assertEqual(cs.count("fsl.tool_missing"), 1)
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — `run_fslc` は `subprocess.run([fslc, *args], capture_output=True, text=True, cwd=cwd, timeout=120)` の stdout を JSON として読む。`gaps(proj)` は各 spec について: legacy → `fsl.legacy_format`；fslc 無し → 全体で1件 `fsl.tool_missing`；`check` の `result == "error"` を `kind` で振り分け（`forbidden` → `fsl.forbidden_accepted`、`acceptance` → `fsl.acceptance_failed`、それ以外 → `fsl.spec_error`。parse/type/semantics/io なら以降を省略）；`kernel` → `processes()` → `matrix_findings()`；`verify --depth N` → `violated`→`fsl.violated`、`reachable_failed`→`fsl.unreachable`、`warnings[kind=never_enabled_action]`→`fsl.dead_action`（到達不能な状態から出る遷移は重複なので省く）、`deadlock.found`→`fsl.dead_end`、`implements.result != "refines"`→`fsl.seam_broken`；undecided → 論点IDの解決で `fsl.stale_undecided` / `fsl.undecided_unlinked`。`related` は `@depends_on` ＋ `cells:` が `fsl/<name>` で始まる論点 ＋ undecided で解決した論点。

- [x] **Step 4: 通ることを確認**

---

### Task 10: 配線（gaps.run / cli / init / テンプレート / サンプル）と jssm の削除

**Files:**
- Modify: `scripts/reqmap/gaps.py`（`_directives` `load_fsms` `fsm_gaps` を削除、`run()` で `fsl.gaps`）
- Modify: `scripts/reqmap/cli.py`（`cmd_gaps` の要約行、`cmd_status` の hot に `contradiction` `spec_error` `stale_undecided`、`cmd_doctor` の FSL 節、`cmd_init` が `templates/fsl/` を `models/fsl/` へ）
- Create: `templates/fsl/order.fsl`、Delete: `templates/fsm/example.fsl`
- Create: `examples/takeout-app/models/fsl/order.fsl`、Delete: `examples/takeout-app/models/fsm/example.fsl`
- Modify: `examples/takeout-app/questions/A-04/Q-007 二重送信.md`（古いリンク文字を仕込む）
- Modify: `templates/reqmap.yml`（`fsl_depth: 8`）
- Modify: `.claude-plugin/plugin.json`（0.2.0）
- Test: `tests/test_example_vault.py`

- [x] **Step 1: 失敗するテストを書く**（README の「仕込んだ欠陥」表そのもの）

```python
# tests/test_example_vault.py
import shutil
import unittest

from helpers import EXAMPLE
from reqmap import changeset, gaps, model

EXPECTED = ["assumption.stale", "graph.unsound_decision", "graph.isolated", "graph.provisional_gate",
            "rule.dropped_has_edge", "grid.row_empty", "grid.empty", "grid.not_itemised",
            "rule.decided_without_rationale", "turn.no_response", "turn.reasked", "turn.churn",
            "rule.stale_link_text"]
EXPECTED_FSL = ["fsl.state_event_hole", "fsl.unused_event", "fsl.forbidden_accepted",
                "fsl.undecided_unlinked"]


class ExampleVaultTest(unittest.TestCase):
    def setUp(self):
        self.proj = model.Project(EXAMPLE)
        self.checks = {f["check"] for f in gaps.run(self.proj)["findings"]}

    def test_planted_defects_are_detected(self):
        for c in EXPECTED:
            self.assertIn(c, self.checks, c)

    @unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
    def test_planted_fsl_defects_are_detected(self):
        for c in EXPECTED_FSL:
            self.assertIn(c, self.checks, c)

    def test_review_blocks_the_hallucinated_quote(self):
        gates = [r["gate"] for f in changeset.changesets(self.proj)
                 for r in changeset.review(self.proj, f)[1]]
        self.assertEqual(gates.count(changeset.BLOCKED), 1)
```

- [x] **Step 2: 落ちることを確認**

- [x] **Step 3: 実装** — 上記ファイルを作る／消す。サンプルの仕様は旧 `example.fsl` の遷移を `requirements` 方言に写し、欠陥を2つ仕込む（後日追加した `repay Paid -> Paid` が `FB-ORDER-002` と矛盾／論点IDの無い `@undecided`）。`cmd_gaps` の要約: `  fsl/order      状態 7 × イベント 9  遷移 9  抑制 N  検証 <結果>`。`cmd_doctor`: fslc の有無とバージョン、各仕様の check 結果。

- [x] **Step 4: 通ることを確認** — `python3 -m unittest discover -s tests -v`（全件）。`scripts/reqmap-cli gaps --root=examples/takeout-app` を目視。

---

### Task 11: ドキュメント

**Files:**
- Modify: `README.md`（入れ方に fslc、何ができるか、仕掛け1の FSL 段落、ファイル構成、サンプル表、`trace` 削除、スキル表、テストの走らせ方）
- Modify: `GUIDE.md`（0 / 1-3 / 2 / 4-4 / 6 / 7）
- Modify: `skills/requirements-harness/SKILL.md`（コマンド、`changes --ack`、FSL は `fsl-requirements` スキルへ）
- Modify: `skills/coverage-grids/SKILL.md`（FSL 節を書き換え）
- Modify: `commands/reqmap-changes.md`（`--ack`）、`commands/reqmap-extract.md`（`Agent`）、`commands/reqmap-doctor.md`（fslc）、`commands/reqmap-gaps.md`（fsl 絞り込み）
- Modify: `templates/reqmap.yml`（キーの説明）

- [x] **Step 1: 書き換える**（文体は既存に合わせる。要点: 「reqmap が問い、fslc が検証する」「決定は仕様に写す」「undecided は論点IDを頭に書く」「基準は2つ」）
- [x] **Step 2: `grep -rn "jssm\|fsm/\|trace \|--snapshot" README.md GUIDE.md skills commands templates` で残骸が無いことを確認**

---

### Task 12: 総合確認

- [x] `python3 -m unittest discover -s tests -v` が全件 OK
- [x] `scripts/reqmap-cli doctor|status|gaps|review|recalc --check|view|json --root=examples/takeout-app` が全部 exit 0
- [x] `fslc check --strict-tags templates/fsl/order.fsl` と `fslc lint` がクリーン
- [x] `git status` で `.reqmap/` が混じっていない
