# -*- coding: utf-8 -*-
"""IR から自己完結の HTML を作る。**外部依存なし・CDN なし。**

オフラインのリポジトリ内で開けること、そのまま添付して配れることを優先する。
レイアウト計算は Python 側でやる（決定論的にしたいので JS に任せない）。
JS は hover とタブ切り替えだけ。

■ 4つのビュー

  次に決める順   順位表。**これが本体。** 迷ったらここだけ見る
  決定の変化     前回見たときから書き換わった決定。各自が自分の設計に効くか判断する
  依存の地図     層別DAG。左が先、右が後。構造を見る
  網羅グリッド   1マス1観点のヒートマップ。**空白＝インクが無い**。俯瞰はこれが一番効く
  領域別の進捗   積み上げ棒。未決の質量がどこにあるか

3Dの力学グラフは採らない。Z軸に意味を持たせられないなら、読めなくなるだけで情報は増えない。
層別DAGの横軸は「決める順番」という意味を持つので、そちらを採る。
"""
import html
import json
import os

from . import gaps, model

# 状態の順序ランプ（青・単一色相）。決定=濃い／未決=薄い。
# 既存の「■＝決定、□＝まだ」という読み方をそのまま色にした。
# dataviz の ordinal 検証を light/dark 両方で通してある。
RAMP_L = {"open": "#86b6ef", "investigating": "#3987e5",
          "provisional": "#1c5cab", "decided": "#0d366b", "dropped": "#c3c2b7"}
RAMP_D = {"open": "#184f95", "investigating": "#2a78d6",
          "provisional": "#6da7ec", "decided": "#b7d3f6", "dropped": "#52514e"}
LABEL = {"open": "未決", "investigating": "確認中", "provisional": "仮決定",
         "decided": "決定", "dropped": "取下げ"}
ORDER = ["open", "investigating", "provisional", "decided"]

NODE_W, NODE_H, LAYER_GAP, ROW_GAP, PAD = 196, 34, 258, 46, 28


def ellipsis(text, px, size=11.0):
    """SVG には自動省略が無いので、実効幅で切る。全角は約1em、半角は約0.5em。"""
    w, out = 0.0, []
    for ch in text:
        cw = size * (1.0 if ord(ch) > 0x2E7F else 0.52)
        if w + cw > px - size:
            return "".join(out) + "…"
        w += cw
        out.append(ch)
    return text


def layout(items, res, edges):
    """層別レイアウト。x=前提の深さ（左が先）、y=層内の順序。交差は重心法で2回だけ減らす。"""
    live = {i: it for i, it in items.items() if it["status"] != "dropped"}
    if not live:
        return [], [], 0, 0
    layers = {}
    for i in live:
        layers.setdefault(res[i]["depth"], []).append(i)
    for d in layers:
        layers[d].sort(key=lambda i: (-res[i]["blocks_count"], i))
    ups = {i: [] for i in live}
    for u, outs in edges.items():
        for v, k in outs:
            if u in live and v in live and k != "conflicts":
                ups[v].append(u)
    for _ in range(2):
        for d in sorted(layers)[1:]:
            pos = {i: n for dd in layers for n, i in enumerate(layers[dd])}
            layers[d].sort(key=lambda i: (
                sum(pos.get(u, 0) for u in ups[i]) / len(ups[i]) if ups[i] else 0, i))
    xy = {}
    for d in sorted(layers):
        for n, i in enumerate(layers[d]):
            xy[i] = (PAD + d * LAYER_GAP, PAD + n * ROW_GAP)
    w = PAD * 2 + (max(layers) * LAYER_GAP if layers else 0) + NODE_W
    h = PAD * 2 + max(len(v) for v in layers.values()) * ROW_GAP
    nodes = [{"id": i, "x": xy[i][0], "y": xy[i][1], "t": items[i]["title"],
              "short": ellipsis(items[i]["title"], NODE_W - 20),
              "s": items[i]["status"], "b": res[i]["blocks_count"],
              "im": res[i]["impact_count"], "p": res[i]["priority"],
              "ask": res[i]["ask_by"], "need": res[i]["need_by"],
              "ready": res[i]["ready"], "owner": items[i]["owner"],
              "area": items[i]["area"]} for i in live]
    links = [{"f": u, "t": v, "k": k} for u, outs in edges.items() for v, k in outs
             if u in live and v in live]
    return nodes, links, w, h


def build(root, args):
    proj = model.Project(root)
    out = gaps.run(proj)
    an = out["analysis"]
    res = an["result"]
    nodes, links, w, h = layout(proj.items, res, an["edges"])

    ranked = sorted(
        [dict(id=i, title=proj.items[i]["title"], owner=proj.items[i]["owner"],
              area=proj.items[i]["area"], status=proj.items[i]["status"], **res[i])
         for i in proj.items if proj.items[i]["status"] not in model.SETTLED
         and proj.items[i]["kind"] not in ("area",)],
        key=lambda r: -r["priority"])
    crit = {r["id"] for r in ranked[:3]}

    areas = []
    for aid, a in (proj.areas or {}).items():
        c = {s: 0 for s in ORDER}
        for it in proj.items.values():
            if it["area"] == aid and it["status"] in c:
                c[it["status"]] += 1
        if sum(c.values()):
            areas.append({"id": aid, "label": a["label"], "risk": a["risk"], "counts": c})
    areas.sort(key=lambda a: -(a["counts"]["open"] + a["counts"]["investigating"]))

    grids = gaps.load_grids(proj)
    claimed = set()
    for it in proj.items.values():
        claimed |= {str(c).strip() for c in it["cells"]}
    gdata = []
    for g in grids:
        cells = []
        for rid, rl, rw in g["rows"]:
            row = []
            for cid, cl, cw in g["cols"]:
                if (rid, cid) in g["skip"]:
                    st, note = "skip", g["skip"][(rid, cid)]
                elif "%s:%s x %s" % (g["id"], rid, cid) in claimed:
                    st, note = "linked", ""
                else:
                    cand = gaps._cands(rw, cw, list(proj.items.values()), g["area"])
                    st = "near" if cand else "empty"
                    note = "・".join(c["id"] for c in cand[:3])
                row.append({"s": st, "n": note, "c": cl})
            cells.append({"label": rl, "row": row})
        gdata.append({"id": g["id"], "title": g["title"] or g["id"],
                      "cols": [{"s": ellipsis(c[1], 120, 11.0), "f": c[1]}
                               for c in g["cols"]], "rows": cells})

    # 前回見たときからの決定の変化。設計側の記帳は要らない。
    from . import decisions as _dc
    snap = None
    try:
        snap = json.load(open(os.path.join(proj.root, proj.cfg["out_dir"],
                                           "findings-seen.json"), encoding="utf-8"))
    except Exception:
        pass
    rew, add, gone = _dc.changed(proj, (snap or {}).get("decisions") or {})
    norm = lambda xs: [dict(x, t=x["title"], s=x["status"]) for x in xs]
    rew, add, gone = norm(rew), norm(add), norm(gone)
    tracked = [{"id": i, "t": proj.items[i]["title"], "s": proj.items[i]["raw_status"],
                "h": h} for i, h in sorted(_dc.snapshot(proj).items())]

    payload = {"rewritten": rew, "added": add, "gone": gone, "tracked": tracked,
               "since": (snap or {}).get("at", ""),
               "project": proj.cfg.get("name") or os.path.basename(proj.root),
               "milestone": str(proj.cfg.get("milestone") or ""),
               "generated": out["generated_at"], "today": model.today().isoformat(),
               "nodes": nodes, "links": links, "w": w, "h": h,
               "ranked": ranked, "crit": sorted(crit), "areas": areas, "grids": gdata,
               "findings": out["findings"],
               "counts": {"items": len(proj.items),
                          "open": sum(1 for i in proj.items.values()
                                      if i["status"] in model.ACTIVE),
                          "findings": len(out["findings"])}}

    htm = TEMPLATE.replace("/*__DATA__*/null",
                           json.dumps(payload, ensure_ascii=False))
    dest = os.path.join(proj.root, proj.cfg["out_dir"], "index.html")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w", encoding="utf-8").write(htm)
    print(dest)
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>要件の地図</title>
<style>
:root{
  color-scheme:light;
  --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s-open:#86b6ef; --s-investigating:#3987e5; --s-provisional:#1c5cab;
  --s-decided:#0d366b; --s-dropped:#c3c2b7;
  --critical:#d03b3b; --warning:#fab219; --good:#0ca30c;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s-open:#184f95; --s-investigating:#2a78d6; --s-provisional:#6da7ec;
  --s-decided:#b7d3f6; --s-dropped:#52514e;
}}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s-open:#184f95; --s-investigating:#2a78d6; --s-provisional:#6da7ec;
  --s-decided:#b7d3f6; --s-dropped:#52514e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:14px/1.6 ui-sans-serif,system-ui,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:19px;margin:0 0 2px;letter-spacing:.01em}
.sub{color:var(--ink2);font-size:13px;margin-bottom:18px}
.sub b{color:var(--ink);font-variant-numeric:tabular-nums}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.tabs button{font:inherit;font-size:13px;padding:7px 13px;border-radius:8px;cursor:pointer;
  background:transparent;color:var(--ink2);border:1px solid var(--border)}
.tabs button[aria-selected=true]{background:var(--surface);color:var(--ink);
  border-color:var(--axis);font-weight:600}
.panel{display:none;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:18px}
.panel.on{display:block}
.cap{font-size:12px;color:var(--muted);margin:0 0 14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-weight:600;color:var(--ink2);font-size:12px;
  border-bottom:1px solid var(--axis);padding:6px 8px;white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.crit td:first-child{box-shadow:inset 3px 0 0 var(--critical)}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
  border:1px solid var(--border);color:var(--ink2);white-space:nowrap}
.late{color:var(--critical);font-weight:600}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:0 0 12px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;
  margin-right:5px;vertical-align:-1px;border:1px solid var(--border)}
.scroll{overflow:auto;max-width:100%}
svg{display:block}
.node rect{stroke:var(--surface);stroke-width:2}
.node.crit rect{stroke:var(--critical);stroke-width:2.5}
.node text{font-size:11px;pointer-events:none}
.node:hover rect{filter:brightness(1.12)}
.edge{fill:none;stroke:var(--axis);stroke-width:2}
.edge.constrains{stroke-dasharray:3 3;opacity:.75}
.gcell{width:22px;height:22px;border-radius:4px;display:inline-block}
.gt{border-collapse:separate;border-spacing:2px;font-size:12px;width:auto}
.gt th{border:0;padding:2px 4px;font-weight:500;color:var(--muted);font-size:11px}
.gt th.rot{height:124px;white-space:nowrap;vertical-align:bottom}
.gt th.rot span{display:inline-block;transform:rotate(-60deg);transform-origin:left bottom;
  width:18px}
.gt td{border:0;padding:0}
.gt td.rl{padding-right:10px;color:var(--ink2);white-space:nowrap;font-size:12px}
#tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .08s;z-index:9;
  background:var(--surface);border:1px solid var(--axis);border-radius:8px;padding:8px 10px;
  font-size:12px;max-width:310px;box-shadow:0 6px 22px rgba(0,0,0,.16);color:var(--ink)}
#tip b{display:block;margin-bottom:3px}
.empty{color:var(--muted);font-size:13px;padding:14px 0}
.pill.gap{border-color:var(--critical);color:var(--critical);font-weight:600}
.chip{display:inline-block;padding:0 6px;border-radius:99px;font-size:11px;
  border:1px solid var(--border);white-space:nowrap}
.chip.ok{color:var(--ink2)}
.chip.warn{color:var(--ink);border-color:var(--warning);background:color-mix(in srgb,var(--warning) 14%,transparent)}
.chip.bad{color:var(--critical);border-color:var(--critical);font-weight:600}
code{font-size:12px;background:var(--plane);padding:1px 4px;border-radius:4px}
</style></head><body>
<div class="wrap">
  <h1 id="ttl"></h1>
  <p class="sub" id="sub"></p>
  <div class="tabs" role="tablist" id="tabs"></div>
  <div class="panel on" id="p0"></div>
  <div class="panel" id="p1"></div>
  <div class="panel" id="p2"></div>
  <div class="panel" id="p3"></div>
  <div class="panel" id="p4"></div>
</div>
<div id="tip"></div>
<script>
const D = /*__DATA__*/null;
const LAB={open:"未決",investigating:"確認中",provisional:"仮決定",decided:"決定",dropped:"取下げ"};
const ORDER=["open","investigating","provisional","decided"];
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const col=s=>`var(--s-${s})`;
const late=d=>d&&d<D.today;

document.getElementById("ttl").textContent=D.project+" — 要件の地図";
document.getElementById("sub").innerHTML=
  `論点 <b>${D.counts.items}</b> 件（未決 <b>${D.counts.open}</b>）・確認観点 <b>${D.counts.findings}</b> 件`
  +(D.milestone?` ・ 目標 <b>${esc(D.milestone)}</b>`:"")+` ・ ${esc(D.generated)} 時点`;

const TABS=["次に決める順","依存の地図","網羅グリッド","領域別の進捗","決定の変化"];
const tb=document.getElementById("tabs");
TABS.forEach((t,i)=>{const b=document.createElement("button");b.textContent=t;
  b.setAttribute("role","tab");b.setAttribute("aria-selected",i===0);
  b.onclick=()=>{[...tb.children].forEach((x,j)=>{x.setAttribute("aria-selected",j===i);
    document.getElementById("p"+j).classList.toggle("on",j===i)});};tb.appendChild(b);});

const tip=document.getElementById("tip");
function hook(el,html){
  el.addEventListener("mousemove",e=>{tip.innerHTML=html;tip.style.opacity=1;
    const r=tip.getBoundingClientRect();
    tip.style.left=Math.min(e.clientX+14,innerWidth-r.width-8)+"px";
    tip.style.top=Math.min(e.clientY+14,innerHeight-r.height-8)+"px";});
  el.addEventListener("mouseleave",()=>tip.style.opacity=0);
}
function lg(items){return `<div class="legend">`+items.map(x=>
  `<span><i style="background:${x.c}"></i>${esc(x.l)}</span>`).join("")+`</div>`;}

/* 1 ─ 次に決める順 ─────────────────────────────────────── */
{
  const rows=D.ranked.map(r=>`<tr class="${D.crit.includes(r.id)?'crit':''}">
    <td><b>${esc(r.id)}</b><br><span style="color:var(--ink2)">${esc(r.title)}</span></td>
    <td><span class="pill">${LAB[r.status]}</span>${r.ready?"":' <span class="pill">前提待ち</span>'}</td>
    <td>${esc(r.owner||"—")}</td>
    <td class="n ${late(r.ask_by)?'late':''}">${esc(r.ask_by||"—")}</td>
    <td class="n">${esc(r.need_by||"—")}</td>
    <td class="n">${r.blocks_count}</td><td class="n">${r.impact_count}</td>
    <td class="n">${r.priority}</td></tr>`).join("");
  document.getElementById("p0").innerHTML=
    `<p class="cap">未決の論点を「止めている数 × 重要度 × 期限の逼迫」で並べたもの。
      赤い縦線が上位3件。<b>迷ったらここだけ見れば足ります。</b>
      「出す日」を過ぎたものは赤字 — 依存順を守ると間に合わないので、先に出す判断が要ります。</p>
     <div class="scroll"><table><thead><tr>
     <th>論点</th><th>状態</th><th>相手</th><th>出す日</th><th>回答が要る日</th>
     <th>止めてる</th><th>変えたら再検討</th><th>優先度</th></tr></thead>
     <tbody>${rows||'<tr><td colspan="8" class="empty">未決の論点はありません。</td></tr>'}</tbody></table></div>`;
}

/* 2 ─ 依存の地図（層別DAG） ─────────────────────────────── */
{
  const NW=196,NH=34;
  const pos={};D.nodes.forEach(n=>pos[n.id]=n);
  const edges=D.links.filter(l=>pos[l.f]&&pos[l.t]).map(l=>{
    const a=pos[l.f],b=pos[l.t];
    const x1=a.x+NW,y1=a.y+NH/2,x2=b.x,y2=b.y+NH/2,mx=(x1+x2)/2;
    return `<path class="edge ${l.k}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
  }).join("");
  const svg=`<svg width="${D.w}" height="${D.h}" viewBox="0 0 ${D.w} ${D.h}" role="img"
      aria-label="論点の依存関係">${edges}`+
    D.nodes.map(n=>{
      const dark=["provisional","decided"].includes(n.s);
      return `<g class="node ${D.crit.includes(n.id)?'crit':''}" data-id="${n.id}">
        <rect x="${n.x}" y="${n.y}" width="${NW}" height="${NH}" rx="7" fill="${col(n.s)}"/>
        <text x="${n.x+9}" y="${n.y+14}" fill="${dark?'#fff':'#0b0b0b'}"
          font-weight="600">${esc(n.id)}</text>
        <text x="${n.x+9}" y="${n.y+27}" fill="${dark?'#fff':'#0b0b0b'}"
          opacity=".82">${esc(n.short)}</text>
        ${n.b?`<text x="${n.x+NW-9}" y="${n.y+21}" text-anchor="end"
          fill="${dark?'#fff':'#0b0b0b'}" font-weight="700">${n.b}</text>`:""}
      </g>`;}).join("")+`</svg>`;
  document.getElementById("p1").innerHTML=
    `<p class="cap"><b>左が先、右が後。</b>横軸は「前提の深さ」＝決める順番です。
      実線は前提（決まらないと着手できない）、破線は制約（止めはしないが、変えると再検討が要る）。
      右肩の数字は止めている件数。赤枠が上位3件。</p>`
    +lg(ORDER.map(s=>({c:col(s),l:LAB[s]})))
    +`<div class="scroll">${svg}</div>`;
  document.querySelectorAll("#p1 .node").forEach(g=>{
    const n=pos[g.dataset.id];
    hook(g,`<b>${esc(n.id)} ${esc(n.t)}</b>
      状態 ${LAB[n.s]}${n.ready?"":"（前提待ち）"}・相手 ${esc(n.owner||"未定")}<br>
      止めてる ${n.b} 件 / 変えたら再検討 ${n.im} 件<br>
      出す日 ${esc(n.ask||"—")} ・ 回答が要る日 ${esc(n.need||"—")}`);
  });
}

/* 3 ─ 網羅グリッド ──────────────────────────────────────── */
{
  const FILL={empty:"transparent",near:"var(--s-open)",linked:"var(--s-decided)",
              skip:"var(--grid)"};
  const BD={empty:"1px dashed var(--axis)",near:"1px solid var(--border)",
            linked:"1px solid var(--border)",skip:"1px solid var(--border)"};
  const html=D.grids.map(g=>{
    const head=`<tr><th></th>`+g.cols.map(c=>
      `<th class="rot" title="${esc(c.f)}"><span>${esc(c.s)}</span></th>`).join("")+`</tr>`;
    const body=g.rows.map(r=>`<tr><td class="rl">${esc(r.label)}</td>`+
      r.row.map(c=>`<td><span class="gcell" data-t="${esc(r.label)} × ${esc(c.c)}"
        data-s="${c.s}" data-n="${esc(c.n)}"
        style="background:${FILL[c.s]};border:${BD[c.s]}"></span></td>`).join("")+
      `</tr>`).join("");
    const n=g.rows.reduce((a,r)=>a+r.row.filter(c=>c.s==="empty").length,0);
    return `<h3 style="font-size:14px;margin:24px 0 8px">${esc(g.title)}
      <span class="pill gap">空白 ${n}</span></h3>
      <div class="scroll"><table class="gt">${head}${body}</table></div>`;
  }).join("");
  document.getElementById("p2").innerHTML=
    `<p class="cap"><b>1マス＝1つの確認観点。空白は「インクが無い」ことで読みます</b>
      — 穴とは、そこに何も無いことなので。破線の枠が未着手のマスです。件数は見出しの横に出ます。
      <b>俯瞰にはこのビューが一番効きます。</b></p>`
    +lg([{c:"transparent",l:"空白（破線）"},{c:"var(--s-open)",l:"候補あり（推定）"},
         {c:"var(--s-decided)",l:"紐付け済み"},{c:"var(--grid)",l:"skip（理由あり）"}])
    +(html||'<div class="empty">グリッドがありません。models/grids/ に置いてください。</div>');
  const N={empty:"候補の論点すら無い。**ここが新しい観点**",
           near:"題名の近い論点がある（推定）",linked:"cells: で紐付け済み",
           skip:"理由付きで対象外"};
  document.querySelectorAll("#p2 .gcell").forEach(el=>hook(el,
    `<b>${esc(el.dataset.t)}</b>${N[el.dataset.s].replace(/\*\*/g,"")}
     ${el.dataset.n?"<br>候補: "+esc(el.dataset.n):""}`));
}

/* 4 ─ 領域別の進捗 ─────────────────────────────────────── */
{
  const max=Math.max(1,...D.areas.map(a=>ORDER.reduce((s,k)=>s+a.counts[k],0)));
  const rows=D.areas.map(a=>{
    const tot=ORDER.reduce((s,k)=>s+a.counts[k],0);
    const segs=`<span style="display:flex;gap:2px;width:${tot/max*100}%">`+
      ORDER.filter(k=>a.counts[k]).map(k=>
      `<span data-t="${esc(a.label)} — ${LAB[k]} ${a.counts[k]}件"
        style="flex:${a.counts[k]};height:17px;border-radius:3px;background:${col(k)}"></span>`
      ).join("")+`</span>`;
    const un=a.counts.open+a.counts.investigating;
    return `<tr><td style="white-space:nowrap">${esc(a.id)} ${esc(a.label)}
        ${a.risk==="high"?'<span class="pill">高リスク</span>':""}</td>
      <td style="width:62%">${segs}</td>
      <td class="n">${a.counts.decided}/${tot}</td><td class="n">${un}</td></tr>`;
  }).join("");
  document.getElementById("p3").innerHTML=
    `<p class="cap">未決の多い順。<b>棒の長さは論点の件数</b>で、色が濃いほど決着しています。
      どこに未決の質量が溜まっているかを見るためのビューです。</p>`
    +lg(ORDER.map(s=>({c:col(s),l:LAB[s]})))
    +`<div class="scroll"><table><thead><tr><th>領域</th><th></th>
      <th>決定/件数</th><th>未決</th></tr></thead><tbody>${rows||
      '<tr><td colspan="4" class="empty">領域が設定されていません。</td></tr>'}</tbody></table></div>`;
  document.querySelectorAll("#p3 [data-t]").forEach(el=>hook(el,`<b>${esc(el.dataset.t)}</b>`));
}

/* 5 ─ 決定の変化 ─────────────────────────────────────── */
{
  const row=(x,chip)=>`<tr><td style="white-space:nowrap"><b>${esc(x.id)}</b></td>
    <td>${esc(x.t)} <span class="chip">${esc(x.s)}</span>${chip||""}</td></tr>`;
  let html="";
  if(!D.since){
    html=`<div class="empty">まだ基準がありません。
      <code>reqmap gaps --snapshot</code> を実行すると、次からここに差分が出ます。</div>`;
  }else{
    if(D.rewritten.length) html+=`<h3 style="font-size:14px;margin:18px 0 8px">
        中身が書き換わった決定 <span class="pill gap">${D.rewritten.length}</span></h3>
      <table><tbody>`+D.rewritten.map(x=>row(x,
        ` <span class="chip bad">指紋 ${esc(x.was)} → ${esc(x.now)}</span>`)).join("")+`</tbody></table>`;
    if(D.added.length) html+=`<h3 style="font-size:14px;margin:22px 0 8px">
        新しく決まった／仮決定になった <span class="pill">${D.added.length}</span></h3>
      <table><tbody>`+D.added.map(x=>row(x)).join("")+`</tbody></table>`;
    if(D.gone.length) html+=`<h3 style="font-size:14px;margin:22px 0 8px">
        決定から外れた（再オープン・取下げ） <span class="pill">${D.gone.length}</span></h3>
      <table><tbody>`+D.gone.map(x=>row(x)).join("")+`</tbody></table>`;
    if(!html) html=`<div class="empty">前回見たときから書き換わった決定はありません。</div>`;
  }
  html+=`<h3 style="font-size:14px;margin:26px 0 8px">いま追跡している決定
      <span class="pill">${D.tracked.length}</span></h3>
    <table><tbody>`+D.tracked.map(x=>
      `<tr><td style="white-space:nowrap"><b>${esc(x.id)}</b></td>
       <td>${esc(x.t)} <span class="chip">${esc(x.s)}</span></td>
       <td class="n" style="color:var(--muted);font-size:11px">${esc(x.h)}</td></tr>`
    ).join("")+`</tbody></table>`;
  document.getElementById("p4").innerHTML=
    `<p class="cap">前回あなたが見たときから<b>中身が書き換わった決定</b>です。
      指紋は status と「決まったこと」の本文から取っているので、
      <b>決定日をそのままに結論だけ直した場合も出ます</b>。
      設計は各自が進める前提なので、ここを見て<b>自分の設計に効くかは自分で判断します</b>。
      設計側に記帳は要りません。</p>`+html;
}
</script></body></html>
"""
