# -*- coding: utf-8 -*-
"""テスト用の小さな vault を組む。**外部依存なし。**"""
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
