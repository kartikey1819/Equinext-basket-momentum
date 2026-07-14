// Equinext — Groww-style frontend. Vanilla JS + Plotly, talks to the Flask API.
const $ = s => document.querySelector(s);
const fmt = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-IN", {maximumFractionDigits: d, minimumFractionDigits: d});
const rup = (v, d = 2) => v == null ? "—" : "₹" + fmt(v, d);
const pct = v => v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "") + fmt(v) + "%";
const cls = v => v == null ? "" : (v >= 0 ? "up" : "down");
const PLOT = {displayModeBar: false, responsive: true};
const LAY = {paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  font: {color: "#8a8fa6", size: 11, family: "-apple-system,Segoe UI,Roboto,sans-serif"},
  margin: {l: 46, r: 12, t: 10, b: 28}, xaxis: {gridcolor: "#eef1f7", zeroline: false},
  yaxis: {gridcolor: "#eef1f7", zeroline: false}, showlegend: false};
const GREEN = "#00b386", BLUE = "#5367ff", GRAY = "#98a0b3", VIOLET = "#7c5cff", AMBER = "#f7a233";

let STOCKS = [], CUR = null, RANGE = 252, _price = 0, CURINDEX = "n50", CURUNI = "standard", CURCAD = "";
const BASE = {n50:{standard:"vm_pe_only", pit:"vm_pit"}, n500:{standard:"vm500", pit:"vm500_pit"}};
const curKey = () => BASE[CURINDEX][CURUNI] + CURCAD;
const idxKeys = () => ["standard","pit"].flatMap(u => ["","_M","_2M"].map(c => BASE[CURINDEX][u] + c));
const setFromKey = k => { CURINDEX=k.includes("500")?"n500":"n50"; CURUNI=k.includes("pit")?"pit":"standard"; CURCAD=k.slice(BASE[CURINDEX][CURUNI].length); };
const ALLKEYS = ["vm_pe_only","vm_pe_only_M","vm_pe_only_2M","vm_pit","vm_pit_M","vm_pit_2M","vm500","vm500_M","vm500_2M","vm500_pit","vm500_pit_M","vm500_pit_2M"];

// session cache — API responses never change during a run, so fetch each URL once (kills toggle lag)
const _cache = {};
async function cachedJSON(url){ if(!(url in _cache)) _cache[url] = await (await fetch(url)).json(); return _cache[url]; }

async function boot() {
  const d = await (await fetch("/api/overview")).json();
  STOCKS = d.stocks;
  renderList(STOCKS);
  renderBasket();
  document.querySelectorAll(".navtab").forEach(b => b.onclick = () => switchView(b.dataset.view));
  $("#search").oninput = e => jumpSearch(e.target.value);
  $("#search2").oninput = e => renderList(filterStocks(e.target.value));
}
const filterStocks = q => STOCKS.filter(s => s.symbol.toLowerCase().includes(q.toLowerCase()) || (s.name || "").toLowerCase().includes(q.toLowerCase()));
function jumpSearch(q){ const m = filterStocks(q); if(q && m.length){ switchView("stocks"); renderList(m);} }

// ==================== BASKET LANDING ====================
async function renderBasket(){
  const bk = curKey();
  const q = "?basket=" + bk;
  const [s, b, rbAll, cmp] = await Promise.all([
    cachedJSON("/api/strategy" + q),
    cachedJSON("/api/basket" + q),
    cachedJSON("/api/rebalances" + q),
    cachedJSON("/api/compare"),
  ]);
  const REB = rbAll.rebalances || [];
  const m = b.metrics, excess = (m.cagr != null && m.cagr_nifty != null) ? m.cagr - m.cagr_nifty : null;
  const idxName = cmp[bk].index, cadName = cmp[bk].cadence;
  const stdK = BASE[CURINDEX].standard + CURCAD, pitK = BASE[CURINDEX].pit + CURCAD;
  const std = cmp[stdK].metrics, pit = cmp[pitK].metrics;
  const gap = (std.cagr != null && pit.cagr != null) ? std.cagr - pit.cagr : null;
  const keys = idxKeys();
  const pit500 = CURINDEX === "n500";
  const disc = s.survivorship
    ? `<div class="disclaimer"><span class="ic">⚠️</span><div><b>Why this number is optimistic.</b> The <b>Standard</b> universe is <b>today's</b> ${idxName} applied to the past — which leaves out companies later dropped from the index after falling (<b>survivorship bias</b>). Treat the CAGR as an upper bound; switch to <b>Point-in-Time</b> for the honest number.</div></div>`
    : `<div class="disclaimer good"><span class="ic">${pit500?"⚠️":"✅"}</span><div><b>${pit500?"Survivorship-free — but approximate for the Nifty 500.":"This is the survivorship-free result — the trustworthy one."}</b> The universe is whoever was <b>actually</b> a large-cap on each date, including companies later dropped after falling. ${pit500?"<b>Caveat:</b> many Nifty-500 dropouts delisted and can't be sourced, so meaningful residual bias remains here — treat it as a partial correction.":"No hindsight, no cherry-picking today's winners."}</div></div>`;

  $("#basket").innerHTML = `
    <div class="hero">
      <div><h1>${s.name}</h1><div class="tag">${s.tagline}</div></div>
      <div class="asof">Rebalanced ${cadName} · as of ${b.as_of || "—"}</div>
    </div>

    <div class="toggles">
      <div class="btoggle" id="idxtoggle">
        <button data-i="n50" class="${CURINDEX==="n50"?"on":""}">Nifty 50<small>50 stocks</small></button>
        <button data-i="n500" class="${CURINDEX==="n500"?"on":""}">Nifty 500<small>broad market</small></button>
      </div>
      <div class="btoggle" id="unitoggle">
        <button data-u="standard" class="${CURUNI==="standard"?"on":""}">Standard<small>today's list</small></button>
        <button data-u="pit" class="${CURUNI==="pit"?"on":""}">Point-in-Time<small>survivorship-free</small></button>
      </div>
      <div class="btoggle" id="cadtoggle">
        <button data-c="" class="${CURCAD===""?"on":""}">Quarterly</button>
        <button data-c="_M" class="${CURCAD==="_M"?"on":""}">Monthly</button>
        <button data-c="_2M" class="${CURCAD==="_2M"?"on":""}">Bi-monthly</button>
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>${idxName} — all 6 baskets compared</h2>
      <div class="lead">Two universes × three rebalance frequencies — same strategy throughout. Click a row to open it. (Use the toggle above to switch between Nifty 50 and Nifty 500.)</div>
      <table><thead><tr><th>Basket</th><th>CAGR</th><th>After-tax</th><th>Sharpe</th><th>Basket Max DD</th><th>${idxName} Max DD</th><th>Turnover/yr</th><th>₹100→</th></tr></thead>
      <tbody>${keys.map(k=>{const c=cmp[k]||{},mm=(c.metrics)||{};const rdy=c.ready;return `<tr data-k="${k}" class="${k===bk?"selrow":""}">
        <td><b>${c.universe||"—"}</b> <span class="cad">· ${c.cadence||""}</span></td>
        ${rdy?`<td>${fmt(mm.cagr,1)}%</td><td>${fmt(mm.cagr_after_tax,1)}%</td><td>${fmt(mm.sharpe,2)}</td>
        <td class="down">${fmt(mm.max_dd,1)}%</td><td class="down">${fmt(mm.max_dd_nifty,1)}%</td><td>${fmt(mm.turnover_yr,0)}%</td><td>₹${fmt(mm.final,0)}</td>`
        :`<td colspan="7" style="color:var(--muted)">not yet computed</td>`}</tr>`}).join("")}</tbody></table>
      <div class="gapnote" style="text-align:left">Nifty benchmark over the same window: <b>${fmt(std.cagr_nifty,1)}%/yr</b>. Where present, the <b>Standard</b> rows sit above the <b>Point-in-Time</b> rows — that gap is survivorship bias, not skill.</div>
    </div>

    <div class="card">
      <h3 class="mini">Survivorship gap · ${idxName} · ${cadName}</h3>
      <div class="cmp">
        <div class="cmpbox opt"><div class="lbl">Standard · optimistic</div><div class="big up">${fmt(std.cagr,1)}%</div><div class="d">CAGR · ₹100→₹${fmt(std.final,0)}</div></div>
        <div class="gap"><div class="n">−${fmt(gap,1)}%</div><div class="l">bias / yr</div></div>
        <div class="cmpbox real"><div class="lbl">Point-in-Time · real</div><div class="big up">${fmt(pit.cagr,1)}%</div><div class="d">CAGR · ₹100→₹${fmt(pit.final,0)}</div></div>
      </div>
      <div class="legend" style="margin-top:16px"><span><b style="background:${GREEN}"></b>Standard</span><span><b style="background:${VIOLET}"></b>Point-in-Time</span><span><b style="background:${GRAY}"></b>${idxName}</span></div>
      <div id="curve" style="height:300px"></div>
    </div>

    ${disc}

    <div class="metrics">
      ${metric("Return (CAGR)", fmt(m.cagr,1)+"%", `full period · ${idxName}: ${fmt(m.cagr_nifty,1)}%`, "up")}
      ${metric("Beats index by", (excess>=0?"+":"")+fmt(excess,1)+"% / yr", "annualised excess", excess>=0?"up":"down")}
      ${metric("Sharpe", fmt(m.sharpe,2), "return per unit of risk")}
      ${metric("Max Drawdown", fmt(m.max_dd,1)+"%", "worst peak-to-trough fall", "down")}
      ${metric("₹100 grew to", "₹"+fmt(m.final,0), `${idxName}: ₹${fmt(m.final_nifty,0)} · ${fmt(m.years,1)}y`)}
    </div>

    <div class="card">
      <h2>Returns by period</h2>
      <div class="lead">The CAGR above covers the whole backtest. Pick a trailing window below to see how the basket did versus ${idxName} over just that stretch — computed straight from the daily backtest curve.</div>
      <div class="btoggle" id="pertoggle">
        <button data-mo="1">1M</button>
        <button data-mo="3">3M</button>
        <button data-mo="6">6M</button>
        <button data-mo="12" class="on">1Y</button>
        <button data-mo="36">3Y</button>
        <button data-mo="60">5Y</button>
        <button data-mo="">Max</button>
      </div>
      <div id="periodout"></div>
    </div>

    <div class="card">
      <h2>How this basket is built</h2>
      <div class="lead">Four steps, applied fresh every rebalance. Momentum <b>ranks</b> the stocks; valuation & earnings <b>gate</b> out the risky ones.</div>
      <div class="steps">${s.steps.map(stepCard).join("")}</div>
    </div>

    <div class="card">
      <h2>${s.selection.title}</h2>
      <div class="selbox">
        <ol>${s.selection.points.map(p=>`<li>${boldFirst(p)}</li>`).join("")}</ol>
        <div class="flow">
          <div class="fbox"><b>Step 1</b>${s.n_universe} ${idxName} stocks</div>
          <div class="arrow">↓ &nbsp;filter</div>
          <div class="fbox"><b>Gates 2 & 3</b>Drop frothy & hype-driven</div>
          <div class="arrow">↓ &nbsp;rank</div>
          <div class="fbox"><b>Step 4</b>Rank survivors by momentum</div>
          <div class="arrow">↓ &nbsp;select & size</div>
          <div class="fbox final">Top ${s.n_hold} · inverse-vol weighted</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Current Holdings <span style="color:var(--muted);font-weight:500;font-size:14px">· ${b.holdings.length} stocks</span></h2>
      <div class="lead">Weighting: ${s.weighting}. Click any stock for full analysis.</div>
      <table><thead><tr><th>#</th><th>Stock</th><th>Sector</th><th>Weight</th><th>Momentum</th><th>Price</th><th>Day</th></tr></thead>
      <tbody>${b.holdings.map((h,i)=>`<tr data-sym="${h.symbol}">
        <td>${i+1}</td>
        <td><span class="sym">${h.symbol}</span><div class="nm">${h.name||""}</div></td>
        <td><span class="pill sec">${(h.sector||"—").replace("Financial Services","Financials")}</span></td>
        <td><span class="wbar"><span style="width:${Math.min(100,(h.weight||0)*8)}%"></span></span>${fmt(h.weight,1)}%</td>
        <td>${fmt(h.score,2)}</td>
        <td>${rup(h.price)}</td>
        <td class="${cls(h.change_pct)}">${pct(h.change_pct)}</td></tr>`).join("")}</tbody></table>
    </div>

    <div class="card">
      <h2>Rebalance History <span style="color:var(--muted);font-weight:500;font-size:14px">· ${REB.length} rebalances</span></h2>
      <div class="lead">Every rebalance the basket is rebuilt — here's exactly what it bought and sold each time.</div>
      <div class="rebal" id="rebal"></div>
      ${REB.length>8?`<button class="showall" id="showall">Show all ${REB.length} rebalances ↓</button>`:""}
    </div>`;

  const rebalRow = r => {
    const dt = new Date(r.date + "T00:00");
    const md = dt.toLocaleDateString("en-US", {month: "short", year: "numeric"});
    const chips = arr => arr.map(x=>`<span class="tchip ${arr===r.bought?"buy":"sell"}" data-sym="${x}">${x}</span>`).join("");
    const changes = (r.bought.length||r.sold.length)
      ? `${r.bought.length?'<span class="tlabel">In</span>'+chips(r.bought):""}${r.sold.length?'<span class="tlabel">Out</span>'+chips(r.sold):""}`
      : '<span style="color:var(--muted)">No change</span>';
    return `<div class="rev"><div class="date">${md}</div><div class="changes">${changes}</div>
      <div class="meta">${r.kept} kept · ${fmt(r.turnover,0)}% traded</div></div>`;
  };
  const wireChips = () => document.querySelectorAll(".tchip[data-sym]").forEach(c=>c.onclick=()=>{switchView("stocks");selectStock(c.dataset.sym);});
  const paint = list => { $("#rebal").innerHTML = list.map(rebalRow).join(""); wireChips(); };
  paint(REB.slice(0,8));
  if($("#showall")) $("#showall").onclick = e => { paint(REB); e.target.remove(); };

  // overlay Standard + Point-in-Time (this index & cadence) + Nifty; highlight selected universe
  const cs = (cmp[stdK]||{}).curve, cp = (cmp[pitK]||{}).curve;
  if(cs && cs.dates){
    const wS = CURUNI==="standard"?2.8:1.4, wP = CURUNI==="pit"?2.8:1.4;
    const tr = [{x:cs.dates,y:cs.nifty,type:"scatter",mode:"lines",line:{color:GRAY,width:1.5},name:idxName},
      {x:cs.dates,y:cs.basket,type:"scatter",mode:"lines",line:{color:GREEN,width:wS},name:"Standard"}];
    if(cp && cp.dates) tr.push({x:cp.dates,y:cp.basket,type:"scatter",mode:"lines",line:{color:VIOLET,width:wP},name:"Point-in-Time"});
    Plotly.newPlot("curve",tr,{...LAY,height:300,yaxis:{...LAY.yaxis,tickprefix:"₹"}},PLOT);
  } else { $("#curve").innerHTML = '<div class="loading">Not computed yet.</div>'; }

  // trailing-period returns, computed from the daily backtest curve
  PCURVE = b.curve; PIDX = idxName;
  document.querySelectorAll("#pertoggle button").forEach(bn=>bn.onclick=()=>{
    document.querySelectorAll("#pertoggle button").forEach(x=>x.classList.toggle("on", x===bn));
    renderPeriod(bn.dataset.mo===""?null:+bn.dataset.mo);
  });
  renderPeriod(12);

  document.querySelectorAll("#idxtoggle button").forEach(bn=>bn.onclick=()=>{ CURINDEX=bn.dataset.i; renderBasket(); });
  document.querySelectorAll("#unitoggle button").forEach(bn=>bn.onclick=()=>{ CURUNI=bn.dataset.u; renderBasket(); });
  document.querySelectorAll("#cadtoggle button").forEach(bn=>bn.onclick=()=>{ CURCAD=bn.dataset.c; renderBasket(); });
  document.querySelectorAll("#basket table tbody tr[data-k]").forEach(r=>r.onclick=()=>{ setFromKey(r.dataset.k); renderBasket(); });
  document.querySelectorAll("#basket tbody tr[data-sym]").forEach(r=>r.onclick=()=>{switchView("stocks");selectStock(r.dataset.sym);});
}
const metric = (k,v,sub,c="") => `<div class="metric"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="sub">${sub}</div></div>`;

// ---- trailing-period returns from the daily backtest curve ----
let PCURVE = null, PIDX = "";
const _iso = dt => dt.getFullYear()+"-"+String(dt.getMonth()+1).padStart(2,"0")+"-"+String(dt.getDate()).padStart(2,"0");
function trailingStats(curve, months){
  if(!curve || !curve.dates || curve.dates.length < 2) return null;
  const {dates, basket:bs, nifty:ns} = curve, n = dates.length;
  let i0 = 0;
  if(months != null){
    const end = new Date(dates[n-1] + "T00:00");
    const cut = new Date(end); cut.setMonth(cut.getMonth() - months);
    const cutStr = _iso(cut);
    const f = dates.findIndex(d => d >= cutStr);
    i0 = f < 0 ? n-1 : f;
    if(i0 >= n-1) return null;                 // window longer than the backtest
  }
  const yrs = (new Date(dates[n-1]+"T00:00") - new Date(dates[i0]+"T00:00")) / 3.15576e10;
  const bRet = bs[n-1]/bs[i0] - 1, nRet = ns[n-1]/ns[i0] - 1;
  const ann = yrs >= 1;
  return {from:dates[i0], to:dates[n-1], yrs,
          bRet:bRet*100, nRet:nRet*100,
          bCagr: ann ? (Math.pow(bs[n-1]/bs[i0], 1/yrs)-1)*100 : null,
          nCagr: ann ? (Math.pow(ns[n-1]/ns[i0], 1/yrs)-1)*100 : null};
}
function renderPeriod(months){
  const out = $("#periodout"); if(!out) return;
  const st = trailingStats(PCURVE, months);
  if(!st){ out.innerHTML = '<div class="lead" style="color:var(--muted)">Not enough backtest history for this window.</div>'; return; }
  const exc = st.bRet - st.nRet;
  const sgn = x => (x>=0?"+":"") + fmt(x,1) + "%";
  const annNote = st.bCagr!=null
    ? `<div class="lead" style="margin-top:10px">Annualised (CAGR) over this window — basket <b class="up">${fmt(st.bCagr,1)}%</b> vs ${PIDX} <b>${fmt(st.nCagr,1)}%</b>.</div>`
    : `<div class="lead" style="margin-top:10px">Window is under a year, so these are <b>total</b> returns for the period — not annualised (annualising a few months would be misleading).</div>`;
  out.innerHTML = `
    <div class="metrics" style="margin-top:12px">
      ${metric("Basket return", sgn(st.bRet), `${st.from} → ${st.to}`, st.bRet>=0?"up":"down")}
      ${metric(PIDX+" return", sgn(st.nRet), "same window", st.nRet>=0?"up":"down")}
      ${metric("Excess vs index", sgn(exc), "basket − index", exc>=0?"up":"down")}
    </div>${annNote}`;
}
const ROLE = {universe:"Eligibility",valuation:"Filter",momentum:"Ranks",earnings:"Filter"};
function stepCard(st){
  return `<div class="step"><div class="top"><div class="num">${st.n}</div>
    <div><div class="ttl">${st.title}</div><div class="role">${ROLE[st.key]||""}</div></div></div>
    <div class="why">${st.why}</div>
    <ul>${st.criteria.map(c=>`<li>${c}</li>`).join("")}</ul></div>`;
}
const boldFirst = p => { const i=p.indexOf(" "); return i>0 ? "<b>"+p.slice(0,i)+"</b>"+p.slice(i) : p; };

// ==================== STOCKS LIST ====================
function renderList(items){
  $("#stocklist").innerHTML = items.map(s=>`
    <div class="srow ${s.symbol===CUR?"sel":""}" data-sym="${s.symbol}">
      <div><div class="sym">${s.symbol} ${s.in_basket?'<span class="bdot" title="in basket"></span>':""}</div>
        <div class="nm">${s.name}</div></div>
      <div class="r"><div class="px">${rup(s.price)}</div><div class="${cls(s.change_pct)}" style="font-size:12px">${pct(s.change_pct)}</div></div>
    </div>`).join("");
  document.querySelectorAll(".srow").forEach(r=>r.onclick=()=>selectStock(r.dataset.sym));
}

// ==================== STOCK DETAIL ====================
async function selectStock(sym){
  CUR=sym;
  document.querySelectorAll(".srow").forEach(r=>r.classList.toggle("sel",r.dataset.sym===sym));
  $("#detail").innerHTML='<div class="loading">Loading '+sym+'…</div>';
  const d=await cachedJSON("/api/stock/"+sym);
  renderDetail(d);
}
function renderDetail(d){
  _price=d.price; const t=d.technicals, v=d.valuation.current, vp=d.valuation.percentile;
  $("#detail").innerHTML=`
    <div class="shead">
      <div><h1>${d.symbol} ${d.basket.in_basket?`<span class="badge">In Basket · ${fmt(d.basket.weight*100,1)}%</span>`:""}</h1>
        <div class="sec">${d.name} · ${d.sector}</div></div>
      <div class="rt"><div class="price">${rup(d.price)}</div><div class="chg ${cls(d.change_pct)}">${pct(d.change_pct)}</div></div>
    </div>
    <div class="chips">
      ${chip("P/E",fmt(v.pe,1))}${chip("P/B",fmt(v.pb,1))}${chip("EV/EBITDA",v.ev_ebitda==null?"—":fmt(v.ev_ebitda,1))}
      ${chip("52W High",rup(t.high_52w,0))}${chip("52W Low",rup(t.low_52w,0))}${chip("1Y Return",pct(t.ret_1y),cls(t.ret_1y))}
    </div>
    <div class="card">
      <div class="range">${[["1M",21],["6M",126],["1Y",252],["3Y",756],["Max",99999]].map(([l,n])=>`<button data-n="${n}" class="${n===RANGE?"on":""}">${l}</button>`).join("")}</div>
      <div id="pxchart" style="height:340px"></div>
    </div>
    <div class="tabbar">${["Overview","Technicals","Fundamentals","Valuation"].map((x,i)=>`<button class="tab ${i===0?"active":""}" data-tab="${i}">${x}</button>`).join("")}</div>
    <div class="panel active" data-panel="0">${overviewPanel(d)}</div>
    <div class="panel" data-panel="1">${technicalsPanel(t)}</div>
    <div class="panel" data-panel="2"><div class="two">
      <div class="card"><h3 class="mini">EPS (₹)</h3><div id="f_eps" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">Net Profit (₹ Cr)</h3><div id="f_pat" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">Book Value / Share (₹)</h3><div id="f_bv" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">Return on Equity (%)</h3><div id="f_roe" style="height:210px"></div></div></div></div>
    <div class="panel" data-panel="3">${valuationPanel(v,vp)}<div class="two">
      <div class="card"><h3 class="mini">P/E history</h3><div id="v_pe" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">P/B history</h3><div id="v_pb" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">EV/EBITDA history</h3><div id="v_ev" style="height:210px"></div></div>
      <div class="card"><h3 class="mini">FCF yield history (%)</h3><div id="v_fcf" style="height:210px"></div></div></div></div>`;
  drawPrice(d);
  document.querySelectorAll(".range button").forEach(bn=>bn.onclick=()=>{RANGE=+bn.dataset.n;document.querySelectorAll(".range button").forEach(x=>x.classList.toggle("on",x===bn));drawPrice(d);});
  document.querySelectorAll(".tab").forEach(bn=>bn.onclick=()=>{
    document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));bn.classList.add("active");
    document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active",p.dataset.panel===bn.dataset.tab));
    if(bn.dataset.tab==="2")drawFund(d.fundamentals); if(bn.dataset.tab==="3")drawVal(d.valuation);
  });
}
const chip=(k,v,c="")=>`<div class="chip"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
const stat=(k,v,sig="")=>`<div class="stat"><div class="k">${k}</div><div class="v">${v}${sig}</div></div>`;
const S=(t,c)=>`<span class="sig ${c}">${t}</span>`;
const rsiSig=r=>r==null?"":(r>70?S("overbought","r"):r<30?S("oversold","g"):S("neutral","n"));
function overviewPanel(d){const t=d.technicals;return `<div class="grid">
  ${stat("1M",pct(t.ret_1m))}${stat("3M",pct(t.ret_3m))}${stat("6M",pct(t.ret_6m))}${stat("1Y",pct(t.ret_1y))}
  ${stat("Momentum 12-1",pct(t.mom_12_1))}${stat("From 52W High",pct(t.pct_from_high))}
  ${stat("Volatility (ann)",fmt(t.vol_annual,1)+"%")}${stat("RSI (14)",fmt(t.rsi14,0),rsiSig(t.rsi14))}
  ${d.basket.in_basket?stat("Basket momentum score",fmt(d.basket.score,2)):""}</div>`;}
function technicalsPanel(t){const ab=m=>m==null?"":(_price>m?S("above","g"):S("below","r"));
  return `<div class="grid">
  ${stat("SMA 20",rup(t.sma20,0),ab(t.sma20))}${stat("SMA 50",rup(t.sma50,0),ab(t.sma50))}${stat("SMA 200",rup(t.sma200,0),ab(t.sma200))}
  ${stat("RSI (14)",fmt(t.rsi14,0),rsiSig(t.rsi14))}${stat("Momentum 12-1",pct(t.mom_12_1),t.mom_12_1>0?S("positive","g"):S("negative","r"))}
  ${stat("From 52W High",pct(t.pct_from_high))}${stat("Volume trend",pct(t.vol_trend),t.vol_trend>0?S("rising","g"):S("falling","n"))}
  ${stat("Volatility (ann)",fmt(t.vol_annual,1)+"%")}${stat("Trend",t.sma50>t.sma200?"Uptrend":"Downtrend",t.sma50>t.sma200?S("50>200","g"):S("50<200","r"))}</div>`;}
function valuationPanel(v,vp){const pc=(k,val,p,dec=1)=>stat(k,val==null?"—":fmt(val,dec),p==null?"":S(fmt(p,0)+"%ile",p>70?"r":p<30?"g":"n"));
  return `<div class="grid">${pc("P/E",v.pe,vp.pe)}${pc("P/B",v.pb,vp.pb)}${pc("EV/EBITDA",v.ev_ebitda,vp.ev_ebitda)}${pc("FCF yield %",v.fcf_yield==null?null:v.fcf_yield*100,vp.fcf_yield,2)}</div>
  <div class="note">Percentile = where today sits vs the stock's own 5-year history. Low = cheap for itself (good), high = frothy. Above the 80th percentile, the basket drops the stock — that's the valuation gate.</div>`;}

// charts
const slice=(a,n)=>n>=a.length?a:a.slice(a.length-n);
function drawPrice(d){
  _price=d.price; const o=slice(d.ohlcv,RANGE), x=o.map(r=>r.t);
  const up=o.length&&o[o.length-1].c>=o[0].c; const col=up?GREEN:"#eb5b3c";
  const area={x,y:o.map(r=>r.c),type:"scatter",mode:"lines",line:{color:col,width:2},fill:"tozeroy",
    fillcolor:up?"rgba(0,179,134,.08)":"rgba(235,91,60,.08)",yaxis:"y"};
  const sma=(n,c)=>({x,y:slice(d.sma[n],RANGE),type:"scatter",mode:"lines",line:{color:c,width:1.1,dash:"dot"},hoverinfo:"skip",yaxis:"y"});
  const vol={x,y:o.map(r=>r.v),type:"bar",marker:{color:"rgba(83,103,255,.18)"},yaxis:"y2",hoverinfo:"skip"};
  Plotly.newPlot("pxchart",[area,sma(50,BLUE),sma(200,VIOLET),vol],
    {...LAY,height:340,xaxis:{...LAY.xaxis,type:"date"},yaxis:{...LAY.yaxis,domain:[.26,1],tickprefix:"₹"},yaxis2:{...LAY.yaxis,domain:[0,.17]}},PLOT);
}
const barC=(id,x,y,c)=>Plotly.newPlot(id,[{x,y,type:"bar",marker:{color:c,line:{width:0}}}],{...LAY,height:210,margin:{l:44,r:8,t:6,b:24}},PLOT);
const lineC=(id,x,y,c)=>Plotly.newPlot(id,[{x,y,type:"scatter",mode:"lines",line:{color:c,width:2},fill:"tozeroy",fillcolor:c+"14"}],{...LAY,height:210,margin:{l:44,r:8,t:6,b:24}},PLOT);
function drawFund(f){const y=f.map(r=>r.year);barC("f_eps",y,f.map(r=>r.eps),BLUE);barC("f_pat",y,f.map(r=>r.pat),GREEN);barC("f_bv",y,f.map(r=>r.book_value),VIOLET);barC("f_roe",y,f.map(r=>r.roe),AMBER);}
function drawVal(v){lineC("v_pe",v.dates,v.pe,BLUE);lineC("v_pb",v.dates,v.pb,GREEN);lineC("v_ev",v.dates,v.ev_ebitda,VIOLET);lineC("v_fcf",v.dates,v.fcf_yield.map(x=>x==null?null:x*100),AMBER);}

// ==================== COMPARE ALL 12 ====================
async function renderCompareAll(){
  const cmp = await cachedJSON("/api/compare");
  const rows = ALLKEYS.map(k=>cmp[k]).filter(c=>c&&c.ready);
  const bestC = Math.max(...rows.map(c=>c.metrics.cagr));
  const bestS = Math.max(...rows.map(c=>c.metrics.sharpe));
  const bestDD = Math.max(...rows.map(c=>c.metrics.max_dd));   // least-negative = best
  const hi = on => on ? ' style="font-weight:800;color:var(--brand-d)"' : '';
  $("#compareall").innerHTML = `
    <h1 style="margin:0 0 4px">All 12 baskets — master comparison</h1>
    <div style="color:var(--sub);margin-bottom:16px">Same strategy across <b>2 indices × 2 universes × 3 rebalance cadences</b>. Click any row to open that basket.</div>
    <div class="card">
      <table><thead><tr><th>Index</th><th>Universe</th><th>Cadence</th><th>CAGR</th><th>vs index</th><th>After-tax</th><th>Sharpe</th><th>Basket Max DD</th><th>Index Max DD</th><th>Turn/yr</th><th>₹100→</th></tr></thead>
      <tbody>${ALLKEYS.map(k=>{const c=cmp[k];if(!c||!c.ready)return "";const m=c.metrics;const exc=m.cagr-m.cagr_nifty;
        return `<tr data-k="${k}" class="${k===curKey()?"selrow":""}">
          <td><b>${c.index}</b></td>
          <td>${c.universe}${c.survivorship?"":' <span class="pill sec" style="font-size:9.5px">honest</span>'}</td>
          <td>${c.cadence}</td>
          <td${hi(m.cagr===bestC)}>${fmt(m.cagr,1)}%</td>
          <td class="${exc>=0?'up':'down'}">${exc>=0?'+':''}${fmt(exc,1)}%</td>
          <td>${fmt(m.cagr_after_tax,1)}%</td>
          <td${hi(m.sharpe===bestS)}>${fmt(m.sharpe,2)}</td>
          <td class="down">${fmt(m.max_dd,1)}%</td>
          <td class="down">${fmt(m.max_dd_nifty,1)}%</td>
          <td>${fmt(m.turnover_yr,0)}%</td>
          <td${hi(m.final===Math.max(...rows.map(x=>x.metrics.final)))}>₹${fmt(m.final,0)}</td></tr>`}).join("")}</tbody></table>
      <div class="gapnote" style="text-align:left;margin-top:14px">⚠️ <b>Read honestly.</b> <b>Point-in-Time</b> removes survivorship bias by including companies that later dropped out. The <b>Nifty 50 · Point-in-Time</b> rows (~13%) are the one <b>fully-trustworthy</b> result. Nifty-500 numbers stay inflated — even PIT-500 can't include delisted losers (the biggest broad-market survivorship source), so treat them as optimistic upper bounds. Higher headline returns on the Nifty 500 also come with deeper drawdowns (−40%) and far higher turnover.</div>
    </div>`;
  document.querySelectorAll("#compareall tbody tr[data-k]").forEach(r=>r.onclick=()=>{ setFromKey(r.dataset.k); switchView("basket"); renderBasket(); });
}

// nav
function switchView(v){
  document.querySelectorAll(".navtab").forEach(b=>b.classList.toggle("active",b.dataset.view===v));
  $("#basket-view").hidden=v!=="basket"; $("#stocks-view").hidden=v!=="stocks"; $("#compare-view").hidden=v!=="compare";
  if(v==="compare") renderCompareAll();
}
boot();
