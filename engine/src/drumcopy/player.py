"""Self-contained HTML page: the recording plays while the drum grid follows it.

Built from score.txt and beat_times.json, so it shows exactly what the score says
and where each beat sits in the audio. Click a beat to seek there.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .instruments import INSTRUMENTS
from .score import from_text

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__ - drumcopy</title>
<style>
body{font:14px -apple-system,system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1d1f23}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #dcdfe4;padding:12px 20px;z-index:2}
h1{font-size:18px;margin:0 0 8px} .meta{color:#5d636e;margin-left:8px;font-size:13px}
audio{width:100%} .row{display:flex;gap:12px;align-items:center}
main{padding:16px 20px;display:flex;flex-wrap:wrap;gap:10px}
.m{background:#fff;border:1px solid #dcdfe4;border-radius:6px;padding:6px 8px}
.m.now{border-color:#2563eb;box-shadow:0 0 0 2px #bfd3fe}
.mh{font-size:11px;color:#5d636e;margin-bottom:2px}
table{border-collapse:collapse} td{width:11px;height:13px;text-align:center;font:11px ui-monospace,monospace;padding:0;cursor:pointer}
td.k{width:22px;color:#5d636e;text-align:left;cursor:default} td.b{border-left:1px solid #e3e6ea}
td.hit{color:#1d1f23;font-weight:700} td.on{background:#dbe7ff}
label{font-size:13px;color:#5d636e}
</style></head><body>
<header><h1>__TITLE__<span class="meta">__META__</span></h1>
<div class="row"><audio id="a" controls src="__AUDIO__"></audio></div>
<div class="row" style="margin-top:6px">
<label><input type="radio" name="src" value="__AUDIO__" checked> full mix</label>
__DRUMS_OPTION__
<a href="score.pdf" target="_blank">PDF</a> <a href="score.musicxml" download>MusicXML</a></div></header>
<main id="g"></main>
<script>
const S=__DATA__;
const g=document.getElementById('g'),a=document.getElementById('a');
const cells=[];  // [time, element of beat column cells]
S.measures.forEach((m,mi)=>{
  const box=document.createElement('div');box.className='m';box.dataset.start=m.start;
  box.innerHTML='<div class="mh">'+m.label+'</div>';
  const t=document.createElement('table');
  m.rows.forEach(r=>{const tr=document.createElement('tr');
    tr.innerHTML='<td class="k">'+r.key+'</td>';
    r.beats.forEach((cellsInBeat,bi)=>cellsInBeat.forEach((c,si)=>{
      const td=document.createElement('td');td.textContent=c==='-'?'·':c;
      if(c!=='-')td.className='hit';if(si===0)td.classList.add('b');
      td.dataset.beat=m.start+bi;td.onclick=()=>{a.currentTime=S.beats[m.start+bi];a.play()};
      tr.appendChild(td)}));
    t.appendChild(tr)});
  box.appendChild(t);g.appendChild(box)});
const byBeat={};document.querySelectorAll('td[data-beat]').forEach(td=>(byBeat[td.dataset.beat]??=[]).push(td));
const boxes=[...document.querySelectorAll('.m')];
let last=-1;
function tick(){const t=a.currentTime;let lo=0,hi=S.beats.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;if(S.beats[mid]<=t)lo=mid;else hi=mid-1}
  if(lo!==last){(byBeat[last]||[]).forEach(e=>e.classList.remove('on'));(byBeat[lo]||[]).forEach(e=>e.classList.add('on'));
    boxes.forEach(b=>b.classList.remove('now'));
    const cur=boxes.filter(b=>+b.dataset.start<=lo).pop();if(cur){cur.classList.add('now');
      if(!a.paused)cur.scrollIntoView({block:'nearest',behavior:'smooth'})}
    last=lo}
  requestAnimationFrame(tick)}
requestAnimationFrame(tick);
document.querySelectorAll('input[name=src]').forEach(r=>r.onchange=()=>{const t=a.currentTime,p=!a.paused;a.src=r.value;a.currentTime=t;if(p)a.play()});
</script></body></html>
"""


def build(out_dir, audio=None, drums=None):
    out = Path(out_dir)
    beat_times = json.loads((out / "beat_times.json").read_text(encoding="utf-8"))
    score = from_text((out / "score.txt").read_text(encoding="utf-8"), beat_times)
    measures = []
    number = 0 if score.measures and score.measures[0].pickup else 1
    for measure in score.measures:
        keys = [k for k in INSTRUMENTS if any(k in s for b in measure.beats for s in b.slots)]
        rows = [{"key": k, "beats": [["x" if k in s else "-" for s in b.slots] for b in measure.beats]} for k in keys]
        label = f"{number}" + (f" · {measure.section}" if measure.section else "")
        measures.append({"start": measure.start_beat, "label": label, "rows": rows or
                         [{"key": "", "beats": [["-"] * b.division for b in measure.beats]}]})
        number += 1
    report = json.loads((out / "report.json").read_text(encoding="utf-8")) if (out / "report.json").is_file() else {}
    audio = audio or report.get("audio")
    drums = drums or report.get("drums")
    rel = lambda p: _relative(p, out) if p else ""
    drums_option = (f'<label><input type="radio" name="src" value="{rel(drums)}"> drums only</label>'
                    if drums and Path(drums).is_file() else "")
    from .engrave import tempo_marks
    meta = f"♩={tempo_marks(score)[0]} · {score.time_signature} · {score.feel}"
    html = (TEMPLATE.replace("__TITLE__", score.title).replace("__META__", meta)
            .replace("__AUDIO__", rel(audio)).replace("__DRUMS_OPTION__", drums_option)
            .replace("__DATA__", json.dumps({"beats": beat_times, "measures": measures})))
    target = out / "player.html"
    target.write_text(html, encoding="utf-8")
    return target


def _relative(path, start):
    """Relative link for the page; on Windows a file on another drive gets a file:// URL."""
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:
        return Path(path).resolve().as_uri()
