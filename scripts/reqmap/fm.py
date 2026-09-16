# -*- coding: utf-8 -*-
"""frontmatter の読み書き。**外部依存なし。**

PyYAML を使わない理由は2つ。
  1. macOS の Homebrew Python は PEP 668 で pip install が弾かれる
  2. safe_dump はコメントを全部消す。人が手で書くファイルにコメントは要る

解釈するのは reqmap が使う範囲だけ。
  key: value / key: "quoted" / key: [a, b] / key:\\n  - item / key:\\n  sub: value

書き戻しは**その行だけ**を差し替える。他の行とコメントには触らない。
"""
import re

SEP = "---"


def split(text):
    """(frontmatter文字列, 本文) を返す。frontmatter が無ければ ("", text)。"""
    if not text.startswith(SEP):
        return "", text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def _scalar(s):
    s = s.strip()
    # 引用符で囲まれていなければ、' #' 以降はコメントとして落とす。
    # 値そのものの '#'（#fff など）を壊さないよう、前に空白があるときだけ。
    if not (len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'"):
        s = re.split(r"\s+#", s, 1)[0].strip()
    if s in ("", "~", "null"):
        return ""
    if s in ("true", "True", "yes"):
        return True
    if s in ("false", "False", "no"):
        return False
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if re.match(r"^\[.*\]$", s):
        body = s[1:-1].strip()
        return [_scalar(x) for x in body.split(",")] if body else []
    if re.match(r"^-?\d+$", s):
        return int(s)
    return s


def parse(fm_text):
    """frontmatter を dict に。値は 文字列 / 数値 / bool / list / dict。"""
    out, key, lines = {}, None, fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][\w\-]*):\s*(.*)$", line)
        if m:
            key, rest = m.group(1), m.group(2).strip()
            if rest:
                out[key] = _scalar(rest)
                i += 1
                continue
            # 次行以降がリストかマップか
            block, j = [], i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
                block.append(lines[j])
                j += 1
            items = [b for b in block if b.strip() and not b.lstrip().startswith("#")]
            if items and items[0].lstrip().startswith("- "):
                out[key] = [_scalar(b.lstrip()[2:]) for b in items if b.lstrip().startswith("- ")]
            elif items:
                sub = {}
                for b in items:
                    mm = re.match(r"^\s+(?!-)([^:#]+?)\s*:\s*(.*)$", b)
                    if mm:
                        sub[mm.group(1)] = _scalar(mm.group(2))
                out[key] = sub
            else:
                out[key] = ""
            i = j
            continue
        i += 1
    return out


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None or v == "":
        return ""
    s = str(v)
    return '"%s"' % s if re.search(r"[:#]\s|^\s|\s$", s) else s


def set_key(text, key, value):
    """frontmatter の1キーだけを書き換える（無ければ末尾に足す）。他の行は触らない。"""
    fm, body = split(text)
    if not fm:
        return text
    # 複数行の値はブロック形式で書く。引用符で包むと1個のスカラーになり、
    # リストとして読み直せなくなる（= 参照が黙って消える）。
    sval = "" if value is None else str(value)
    if "\n" in sval:
        block = [l for l in sval.split("\n") if l.strip()]
        new_lines = ["%s:" % key] + block
    else:
        new_lines = ["%s: %s" % (key, _fmt(value))]
    lines = fm.splitlines()
    for i, l in enumerate(lines):
        if re.match(r"^%s:\s" % re.escape(key), l) or l.rstrip() == "%s:" % key:
            # 複数行ブロックだったら丸ごと差し替える
            j = i + 1
            while j < len(lines) and lines[j].startswith((" ", "\t")) and lines[j].strip():
                j += 1
            lines[i:j] = new_lines
            break
    else:
        lines.extend(new_lines)
    return "%s\n%s\n%s\n%s" % (SEP, "\n".join(lines), SEP, body)


def section(body, heading):
    """本文から `## <heading>` セクションの中身を取り出す。"""
    m = re.search(r"^##\s*%s.*?$\n(.*?)(?=^##\s|\Z)" % re.escape(heading),
                  body, re.S | re.M)
    return m.group(1) if m else ""


WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def wikilinks(text):
    """[[Q-001 タイトル]] → 'Q-001 タイトル' のリスト。"""
    return [m.strip() for m in WIKILINK.findall(text)]
