"""Generate the COVID equity-weight-timeline artifact HTML from eqweight_covid.json."""
from __future__ import annotations
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DATA = json.loads((_REPO / "webapp" / "eqweight_covid.json").read_text(encoding="utf-8"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else (_REPO / "webapp" / "eqweight_covid.html")

HTML = r"""<title>Equity-weight timeline through COVID · Index-timed vs Sleeve-timed</title>
<style>
  :root{
    --bg:#eef1f5; --panel:#ffffff; --ink:#141a22; --muted:#5a6675; --faint:#8090a0;
    --grid:#e4e8ee; --hair:#d7dde5;
    --index:#009e78; --sleeve:#e07d16; --book:#9aa6b6; --crash:#e5484d;
    --shadow:0 1px 2px rgba(20,30,45,.06),0 8px 30px rgba(20,30,45,.07);
  }
  @media (prefers-color-scheme:dark){
    :root{ --bg:#0c1015; --panel:#141b23; --ink:#e8edf3; --muted:#93a0b0; --faint:#66727f;
      --grid:#212a35; --hair:#273140; --index:#18c79a; --sleeve:#f7a233; --book:#6f7c8c; --crash:#f2555a;
      --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 34px rgba(0,0,0,.36);}
  }
  :root[data-theme="light"]{ --bg:#eef1f5; --panel:#ffffff; --ink:#141a22; --muted:#5a6675; --faint:#8090a0;
    --grid:#e4e8ee; --hair:#d7dde5; --index:#009e78; --sleeve:#e07d16; --book:#9aa6b6; --crash:#e5484d;
    --shadow:0 1px 2px rgba(20,30,45,.06),0 8px 30px rgba(20,30,45,.07);}
  :root[data-theme="dark"]{ --bg:#0c1015; --panel:#141b23; --ink:#e8edf3; --muted:#93a0b0; --faint:#66727f;
    --grid:#212a35; --hair:#273140; --index:#18c79a; --sleeve:#f7a233; --book:#6f7c8c; --crash:#f2555a;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 34px rgba(0,0,0,.36);}

  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    line-height:1.5;-webkit-font-smoothing:antialiased;}
  .mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;}
  .wrap{max-width:960px;margin:0 auto;padding:44px 22px 72px;}
  .eyebrow{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:var(--sleeve);font-weight:700;}
  h1{font-size:clamp(25px,3.6vw,36px);line-height:1.12;margin:12px 0 8px;letter-spacing:-.02em;text-wrap:balance;font-weight:750;}
  .sub{color:var(--muted);font-size:16.5px;max-width:64ch;text-wrap:pretty;}
  .sub b{color:var(--ink);font-weight:650;}

  .stats{display:flex;flex-wrap:wrap;gap:12px;margin:26px 0 22px;}
  .stat{flex:1 1 160px;background:var(--panel);border:1px solid var(--hair);border-radius:13px;padding:15px 17px;box-shadow:var(--shadow);}
  .stat .k{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);font-weight:650;}
  .stat .v{font-size:26px;font-weight:750;margin-top:4px;letter-spacing:-.01em;}
  .stat .d{font-size:12.5px;color:var(--muted);margin-top:2px;}
  .v.idx{color:var(--index)} .v.slv{color:var(--sleeve)}

  .card{background:var(--panel);border:1px solid var(--hair);border-radius:16px;padding:20px 20px 16px;box-shadow:var(--shadow);}
  .chart-h{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px;}
  .chart-h h2{font-size:16px;margin:0;font-weight:700;}
  .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);}
  .legend span{display:inline-flex;align-items:center;gap:6px;}
  .legend i{width:15px;height:3px;border-radius:2px;display:inline-block}
  .canvas-box{position:relative;width:100%;overflow-x:auto;}
  canvas{width:100%;height:460px;display:block;}
  .axhint{font-size:11.5px;color:var(--faint);margin-top:2px;}

  .phases{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:22px;}
  @media(max-width:720px){.phases{grid-template-columns:1fr}}
  .ph{background:var(--panel);border:1px solid var(--hair);border-radius:14px;padding:16px 17px;box-shadow:var(--shadow);position:relative;overflow:hidden;}
  .ph::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--edge,var(--faint));}
  .ph .when{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);font-weight:650;}
  .ph .ttl{font-size:15.5px;font-weight:700;margin:3px 0 9px;}
  .ph .wts{display:flex;gap:14px;margin-bottom:9px;}
  .ph .wt{font-size:13px;color:var(--muted);}
  .ph .wt b{display:block;font-size:19px;font-weight:750;letter-spacing:-.01em;}
  .ph p{margin:0;font-size:13.5px;color:var(--muted);text-wrap:pretty;}
  .ph.crash{--edge:var(--crash)}
  .b-idx{color:var(--index)} .b-slv{color:var(--sleeve)}

  .note{margin-top:22px;font-size:13.5px;color:var(--muted);border-left:3px solid var(--hair);padding:4px 0 4px 15px;text-wrap:pretty;}
  .note b{color:var(--ink);font-weight:650;}
</style>

<div class="wrap">
  <div class="eyebrow">Risk-dial diagnostic · Mode C · RupeeCase</div>
  <h1>The sleeve re-loaded to 100% equity at the top — the index had already stepped down</h1>
  <p class="sub">The 3-asset dial sets equity exposure from a 3-month momentum. Reading it off the <b>equity sleeve's own returns</b> (amber) instead of the <b>broad Nifty&nbsp;500 index</b> (green) makes the book maximally invested right into the COVID crash. Here is the daily equity weight, Dec&nbsp;2019 → Jun&nbsp;2020.</p>

  <div class="stats">
    <div class="stat"><div class="k">Feb 2020 · into the crash</div><div class="v"><span class="slv">100%</span> <span style="color:var(--faint);font-weight:400">vs</span> <span class="idx">75%</span></div><div class="d">sleeve vs index equity weight</div></div>
    <div class="stat"><div class="k">Book peak → trough</div><div class="v mono">−43%</div><div class="d">₹107 (Feb 7) → ₹61 (Mar 23)</div></div>
    <div class="stat"><div class="k">Full-window Max DD</div><div class="v mono"><span class="idx">−31%</span> <span style="color:var(--faint)">/</span> <span class="slv">−50%</span></div><div class="d">index-timed / sleeve-timed dial</div></div>
  </div>

  <div class="card">
    <div class="chart-h">
      <h2>Daily equity weight held by the dial</h2>
      <div class="legend">
        <span><i style="background:var(--index)"></i>Index-timed</span>
        <span><i style="background:var(--sleeve)"></i>Sleeve-timed</span>
        <span><i style="background:var(--book);height:2px"></i>RupeeCase book level</span>
      </div>
    </div>
    <div class="canvas-box"><canvas id="c" aria-label="Equity weight over time, index-timed versus sleeve-timed"></canvas></div>
    <div class="axhint">Left axis: equity weight (35% floor → 100%). Right axis: equity-book level, base 100. Shaded band = the crash (Feb 20 – Mar 23).</div>
  </div>

  <div class="phases">
    <div class="ph"><div class="when">January · held from the Dec rebalance</div><div class="ttl">Sleeve sat on the floor</div>
      <div class="wts"><div class="wt">index<b class="b-idx">100%</b></div><div class="wt">sleeve<b class="b-slv">35%</b></div></div>
      <p>The book had dipped, so the sleeve's own momentum was weak and the dial hugged its 35% floor. The index was fine, so it stayed fully invested. The book then drifted sideways — the sleeve missed nothing but was out of position.</p></div>
    <div class="ph"><div class="when">February · the top</div><div class="ttl">Sleeve chased the bounce all the way in</div>
      <div class="wts"><div class="wt">index<b class="b-idx">75%</b></div><div class="wt">sleeve<b class="b-slv">100%</b></div></div>
      <p>The book rallied to its high (₹107), so the sleeve's 3-month momentum flipped strongly positive and it re-loaded to <b>100% equity — at the top</b>. The broad index's momentum was softer, so it <b>trimmed to 75%</b>.</p></div>
    <div class="ph crash"><div class="when">Late Feb → March · the crash</div><div class="ttl">Sleeve took the first leg fully exposed</div>
      <div class="wts"><div class="wt">index<b class="b-idx">75→35%</b></div><div class="wt">sleeve<b class="b-slv">100→35%</b></div></div>
      <p>Feb 20–28 the book fell ~11% — the sleeve ate it at <b>100%</b> while the index sat at 75%. By the end-Feb rebalance both cut to 35%, but the sleeve had already opened the drawdown deeper.</p></div>
  </div>

  <div class="note"><b>What this window proves — and doesn't.</b> It's one clean instance of the mechanism: the sleeve's own momentum peaks just before a top, so it re-loads exactly when it should de-risk. The full-window gap (−31% index vs −50% sleeve) accumulates from repeated mistimed re-loads like this one, not from COVID alone. A market-regime read — the broad index — de-risks on the market's condition, not on the book's own recent P&L.</div>
</div>

<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), cx = cv.getContext('2d');
const P = DATA.dates.map((d,i)=>({d, i, ie:DATA.index_eq[i], se:DATA.sleeve_eq[i], b:DATA.book[i]}));
const N = P.length;
const css = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();

function fmtMonth(s){ const [y,m]=s.split('-'); return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m-1]+" '"+y.slice(2); }
const crashStart = P.findIndex(p=>p.d>='2020-02-20');
const trough = P.reduce((mi,p,i)=>p.b<P[mi].b?i:mi,0);

function draw(){
  const box = cv.parentElement.getBoundingClientRect();
  const W = Math.max(560, box.width), H = 460, dpr = Math.min(2, window.devicePixelRatio||1);
  cv.width = W*dpr; cv.height = H*dpr; cv.style.height = H+'px';
  cx.setTransform(dpr,0,0,dpr,0,0); cx.clearRect(0,0,W,H);

  const padL=46, padR=54, padT=26, padB=42, pw=W-padL-padR, ph=H-padT-padB;
  const C={ink:css('--ink'),muted:css('--muted'),faint:css('--faint'),grid:css('--grid'),
    index:css('--index'),sleeve:css('--sleeve'),book:css('--book'),crash:css('--crash'),panel:css('--panel')};
  const bMin=55,bMax=110;
  const X=i=>padL+(i/(N-1))*pw;
  const Yw=v=>padT+(1-v/100)*ph;                     // equity weight 0..100
  const Yb=v=>padT+(1-(v-bMin)/(bMax-bMin))*ph;      // book level

  // crash band
  cx.fillStyle=C.crash; cx.globalAlpha=0.09;
  cx.fillRect(X(crashStart),padT,X(trough)-X(crashStart),ph); cx.globalAlpha=1;

  // horizontal gridlines + left axis labels (equity %)
  cx.font="11px ui-monospace,Menlo,monospace"; cx.textBaseline="middle";
  [0,25,35,50,75,100].forEach(v=>{
    const y=Yw(v); cx.strokeStyle=C.grid; cx.lineWidth=1;
    cx.setLineDash(v===35?[4,4]:[]); cx.beginPath(); cx.moveTo(padL,y); cx.lineTo(W-padR,y); cx.stroke(); cx.setLineDash([]);
    cx.fillStyle=v===35?C.muted:C.faint; cx.textAlign="right"; cx.fillText(v+'%',padL-8,y);
  });
  cx.fillStyle=C.muted; cx.textAlign="right"; cx.fillText('floor',padL-8,Yw(35)+13);

  // month gridlines + labels
  cx.textAlign="center"; cx.textBaseline="top";
  let lastM=null;
  P.forEach((p,i)=>{ const m=p.d.slice(0,7); if(m!==lastM){ lastM=m;
    cx.strokeStyle=C.grid; cx.lineWidth=1; cx.beginPath(); cx.moveTo(X(i),padT); cx.lineTo(X(i),padT+ph); cx.stroke();
    cx.fillStyle=C.faint; cx.fillText(fmtMonth(p.d),X(i),padT+ph+8);
  }});

  // right axis labels (book)
  cx.textAlign="left"; cx.textBaseline="middle"; cx.fillStyle=C.faint;
  [60,80,100].forEach(v=>cx.fillText('₹'+v,W-padR+8,Yb(v)));

  // book line (faint)
  cx.strokeStyle=C.book; cx.lineWidth=1.6; cx.globalAlpha=.85; cx.beginPath();
  P.forEach((p,i)=>{ const x=X(i),y=Yb(p.b); i?cx.lineTo(x,y):cx.moveTo(x,y); }); cx.stroke(); cx.globalAlpha=1;

  // weight lines
  function line(key,color){ cx.strokeStyle=color; cx.lineWidth=2.6; cx.lineJoin="round"; cx.beginPath();
    P.forEach((p,i)=>{ const x=X(i),y=Yw(p[key]); i?cx.lineTo(x,y):cx.moveTo(x,y); }); cx.stroke();
    const lp=P[N-1]; cx.fillStyle=color; cx.beginPath(); cx.arc(X(N-1),Yw(lp[key]),3.4,0,7); cx.fill();
  }
  line('ie',C.index); line('se',C.sleeve);

  // markers on book line: peak & trough
  const peak=P.reduce((mi,p,i)=>p.b>P[mi].b?i:mi,0);
  function mark(i,val,label,dy){ const x=X(i),y=Yb(P[i].b);
    cx.fillStyle=C.book; cx.beginPath(); cx.arc(x,y,3,0,7); cx.fill();
    cx.fillStyle=C.muted; cx.font="11px ui-monospace,Menlo,monospace"; cx.textAlign="center"; cx.textBaseline="middle";
    cx.fillText(label,x,y+dy); }
  mark(peak,0,'peak ₹107',-14); mark(trough,0,'−43%',16);

  // annotations
  cx.textBaseline="alphabetic";
  function tag(text,x,y,color,align){ cx.font="600 12px system-ui,sans-serif"; cx.textAlign=align||"left"; cx.fillStyle=color; cx.fillText(text,x,y); }
  const fx=X(P.findIndex(p=>p.d>='2020-02-10'));
  tag('sleeve → 100%',fx-6,Yw(100)-9,C.sleeve,"left");
  tag('index → 75%',fx-6,Yw(75)-9,C.index,"left");
  const mx=X(P.findIndex(p=>p.d>='2020-03-10'));
  tag('both cut to 35%',mx+4,Yw(35)-9,C.muted,"left");
}
draw();
let raf; const redraw=()=>{cancelAnimationFrame(raf);raf=requestAnimationFrame(draw);};
new ResizeObserver(redraw).observe(cv.parentElement);
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',redraw);
new MutationObserver(redraw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
</script>
"""

OUT.write_text(HTML.replace("__DATA__", json.dumps(DATA)), encoding="utf-8")
print("wrote", OUT)
