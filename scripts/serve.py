# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "fastapi>=0.115",
#   "uvicorn>=0.30",
# ]
# ///
"""serve.py - Subsystem 5: local web UI (plan v3 section 6).

Serves the case workspace on 127.0.0.1 only: case results, the argument DAG
(rendered from the case JSON; Sugiyama-lite layering computed server-side),
provenance inspector data, and the audit tab with on-load chain verification.
The graph is small (tens of nodes): a layered SVG layout in the browser is
sufficient and dependency-free (ADR-002 rationale carried over: no external
layout binary, full interactivity control).

Usage:
  uv run scripts/serve.py [--data DIR] [--port 8765]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))

from audit import verify as verify_ledger  # noqa: E402

app = FastAPI()
SETTINGS = {"data": APP_ROOT / "data"}

LABEL_COLORS = {"IN": "#1a7f37", "OUT": "#b02a2a",
                "UNDECIDED": "#b58a2a", "INSUFFICIENT_GROUNDING": "#6e7781"}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Legal Harness</title>
<style>
 body{font-family:Segoe UI,system-ui,sans-serif;margin:0;background:#0d1117;color:#e6edf3}
 header{padding:12px 20px;border-bottom:1px solid #21262d;display:flex;gap:24px;align-items:baseline}
 header h1{font-size:16px;margin:0}
 .disclaimer{font-size:11px;color:#8b949e}
 main{display:flex;height:calc(100vh - 52px)}
 #graph{flex:1;position:relative} #side{width:420px;overflow:auto;border-left:1px solid #21262d;padding:14px}
 .node{cursor:pointer} .node rect{stroke-width:2}
 .chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-right:6px}
 pre{background:#161b22;padding:8px;border-radius:6px;font-size:11px;white-space:pre-wrap}
 .row{margin:6px 0;font-size:13px}
 .audit-ok{color:#3fb950}.audit-bad{color:#f85149}
</style></head><body>
<header><h1>Neuro-Symbolic Legal Harness</h1>
<span id="caseid"></span><span id="disp"></span>
<span class="disclaimer">Decision-support artifact. Not legal advice. Draft for practitioner review.</span></header>
<main><div id="graph"></div><div id="side"></div></main>
<script>
const COLORS = %COLORS%;
function load(){fetch('/api/case').then(r=>r.json()).then(d=>{
  if(d.error){document.getElementById('graph').innerHTML='<p style="padding:20px">'+d.error+'</p>';return;}
  document.getElementById('caseid').textContent=d.case_id;
  const disp=document.getElementById('disp');
  disp.innerHTML='<span class="chip" style="background:'+ (COLORS[d.disposition]||'#333') +'">'+d.disposition+'</span>';
  drawGraph(d.graph,d.labels);
  const side=document.getElementById('side');
  side.innerHTML='<h3>Nodes</h3>'+d.graph.arguments.map(a=>{
     const lab=d.labels[a.id];
     return '<div class="row"><span class="chip" style="background:'+COLORS[lab]+'">'+lab+'</span><b>'+a.role+'</b> '+a.claim
       +'<br><small>trace: '+a.trace+'</small></div>';
  }).join('')
  +'<h3>Findings</h3><pre>'+JSON.stringify(d.findings,null,1)+'</pre>'
  +'<h3>Grounding events</h3><pre>'+JSON.stringify(d.grounding_events,null,1)+'</pre>'
  +'<h3>Audit ledger</h3><pre class="'+(d.audit.ok?'audit-ok':'audit-bad')+'">'+d.audit.msg+'</pre>'
  +'<p><small>reproducibility: pack '+d.pack_sha256+'</small></p>';
});}
function drawGraph(g,labels){
  // Sugiyama-lite: longest-path layering (defendants sink), simple barycenter-free
  // coordinate assignment - sufficient at tens of nodes (ADR-002)
  const N={}, outs={}, ins={};
  g.arguments.forEach(a=>{N[a.id]=a;outs[a.id]=[];ins[a.id]=[];});
  g.attacks.forEach(e=>{if(e[0]!==e[1]){outs[e[0]].push(e[1]);ins[e[1]].push(e[0]);}});
  const layer={};
  function depth(n,seen){ if(layer[n]!==undefined)return layer[n];
    if(seen.has(n))return 0; seen.add(n);
    layer[n]=outs[n].length? 1+Math.max(...outs[n].map(c=>depth(c,seen))) : 0;
    return layer[n];}
  Object.keys(N).forEach(n=>depth(n,new Set()));
  const byL={};Object.keys(layer).forEach(n=>{(byL[layer[n]]=byL[layer[n]]||[]).push(n);});
  const W=140,H=46,GX=90,GY=40;
  const maxW=Math.max(...Object.values(byL).map(a=>a.length));
  const svgW=(Object.keys(byL).length+1)*GX, svgH=(maxW+1)*(H+GY)+40;
  const pos={};Object.keys(byL).forEach(L=>{byL[L].forEach((n,i)=>{pos[n]=[GX*(+L+1), (svgH/2)+(i-byL[L].length/2)*(H+GY)];});});
  let s='<svg width="'+svgW+'" height="'+svgH+'" style="max-width:100%">';
  g.attacks.forEach(e=>{const a=pos[e[0]],b=pos[e[1]];if(!a||!b)return;
    s+='<path d="M'+a[0]+' '+a[1]+' C '+(a[0]+GX/2)+' '+a[1]+', '+(b[0]-GX/2)+' '+b[1]+', '+b[0]+' '+b[1]+'" fill="none" stroke="#8b949e" stroke-width="1.5" marker-end="url(#arrow)"/>';});
  s+='<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="#8b949e"/></marker></defs>';
  g.arguments.forEach(a=>{const p=pos[a.id],lab=labels[a.id],c=COLORS[lab]||'#333';
    s+='<g class="node" onclick="document.querySelectorAll(\'#side pre\')[0] && window.showNode(\''+a.id+'\')">';
    s+='<rect x="'+(p[0]-W/2)+'" y="'+(p[1]-H/2)+'" width="'+W+'" height="'+H+'" rx="8" fill="#161b22" stroke="'+c+'"/>';
    s+='<text x="'+p[0]+'" y="'+(p[1]-4)+'" text-anchor="middle" fill="#e6edf3" font-size="11">'+a.id.slice(0,18)+'</text>';
    s+='<text x="'+p[0]+'" y="'+(p[1]+12)+'" text-anchor="middle" fill="'+c+'" font-size="11" font-weight="bold">'+lab+'</text></g>';});
  s+='</svg>';document.getElementById('graph').innerHTML=s;
}
window.showNode=id=>{fetch('/api/node/'+id).then(r=>r.json()).then(d=>{
  document.getElementById('side').insertAdjacentHTML('afterbegin','<pre>'+JSON.stringify(d,null,1)+'</pre>');});};
load();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.replace("%COLORS%", json.dumps(LABEL_COLORS))


@app.get("/api/case")
def api_case():
    case_file = SETTINGS["data"] / "case_result.json"
    if not case_file.exists():
        raise HTTPException(404, "no case yet - run the pipeline")
    d = json.loads(case_file.read_text(encoding="utf-8"))
    ok, msg = verify_ledger(SETTINGS["data"] / "audit.jsonl")
    d["audit"] = {"ok": ok, "msg": msg}
    return d


@app.get("/api/node/{node_id}")
def api_node(node_id: str):
    case_file = SETTINGS["data"] / "case_result.json"
    d = json.loads(case_file.read_text(encoding="utf-8"))
    for a in d["graph"]["arguments"]:
        if a["id"] == node_id:
            return a
    raise HTTPException(404, "node not found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=SETTINGS["data"])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    SETTINGS["data"] = args.data
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
