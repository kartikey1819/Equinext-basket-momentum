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
const SECCOL = {
  "Financial Services":"#5367ff", "Industrials":"#f7a233", "Consumer Cyclical":"#ec4899",
  "Basic Materials":"#8b5cf6", "Healthcare":"#00b386", "Technology":"#06b6d4",
  "Consumer Defensive":"#84cc16", "Utilities":"#eab308", "Real Estate":"#a855f7",
  "Communication Services":"#14b8a6", "Energy":"#ef4444", "Unknown":"#98a0b3"};
const seccol = s => SECCOL[s] || "#c0c6d4";
const SECNAME = {"Financial Services":"Financials", "Communication Services":"Communication",
  "Consumer Defensive":"Consumer Staples", "Information Technology":"Technology",
  "Unknown":"Other / Unclassified"};
const secname = s => SECNAME[s] || s;

// Shared RupeeCase-style sector-rotation heat-map: rows = sectors (sorted by today's
// weight, not-held ones "OUT" at the bottom), columns = rebalances, blue intensity =
// % of book. Fills host with a summary header + the plot. Used by the dynamic baskets
// AND the 12 main baskets, so both read identically.
function renderSectorHeatmap(sa, hostId){
  const host = $("#"+hostId); if(!host) return;
  if(!sa || !sa.sectors || !sa.sectors.length){ host.innerHTML = '<div class="lead" style="color:var(--muted)">No sector data for this basket yet.</div>'; return; }
  const last = sa.dates.length - 1;
  const peak = s => Math.max.apply(null, sa.series[s]);
  const cur = {}; sa.sectors.forEach(s => cur[s] = sa.series[s][last]);
  const held = sa.sectors.filter(s => cur[s] > 0.05).sort((a,b) => cur[b] - cur[a]);
  const outs = sa.sectors.filter(s => cur[s] <= 0.05).sort((a,b) => peak(b) - peak(a));
  const display = [...held, ...outs];                 // top -> bottom
  const yOrder = display.slice().reverse();           // Plotly draws bottom -> top
  const z = yOrder.map(s => sa.series[s]);
  const ylab = yOrder.map(secname);
  const nTouched = sa.sectors.filter(s => peak(s) > 0.05).length;
  const anns = yOrder.map(s => ({xref:"paper", x:1.015, xanchor:"left", yref:"y", y:secname(s),
    text: cur[s] > 0.05 ? Math.round(cur[s])+"%" : "OUT", showarrow:false,
    font:{size:11, color: cur[s] > 0.05 ? "#5b6172" : "#b9bfcc"}}));
  const H = Math.max(300, display.length*24 + 56);
  host.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:8px">
      <div>
        <div style="letter-spacing:.09em;font-size:11px;font-weight:700;color:var(--muted)">SECTOR ROTATION</div>
        <div style="font-size:18px;font-weight:700;margin-top:3px">${sa.dates.length} rebalances · ${nTouched} sectors touched · ${held.length} live today</div>
      </div>
      <div style="color:var(--muted);font-size:11px;text-align:right;margin-top:6px;line-height:1.6">
        <span style="display:inline-block;width:36px;height:9px;border-radius:2px;vertical-align:middle;background:linear-gradient(90deg,#eef2ff,#1f3bd6)"></span> darker = higher weight<br>blank cell = sector not held that month
      </div>
    </div>
    <div id="${hostId}_plot" style="height:${H}px"></div>`;
  Plotly.newPlot(hostId+"_plot", [{
    type:"heatmap", x:sa.dates, y:ylab, z:z,
    colorscale:[[0,"#ffffff"],[0.001,"#eef2ff"],[0.25,"#aebfff"],[0.6,"#5f7bff"],[1,"#1f3bd6"]],
    zmin:0, zmax:35, xgap:1, ygap:2, showscale:false,
    hovertemplate:"<b>%{y}</b><br>%{x|%b %Y}<br>%{z:.0f}% of book<extra></extra>"
  }], {...LAY, height:H, margin:{l:150, r:52, t:6, b:26},
      xaxis:{...LAY.xaxis, type:"date", fixedrange:true},
      yaxis:{...LAY.yaxis, automargin:true, ticks:"", fixedrange:true},
      annotations:anns}, PLOT);
}

// The full "Sector allocation" card (stat cards + donut + peak-bars + rotation heat-map),
// shared by the Dynamic Allocator baskets AND the 12 main baskets. `prefix` namespaces the
// chart container ids so the two views never collide.
function sectorCardHTML(sa, prefix, label, capPct){
  if(!sa || !sa.peak) return "";
  const p = sa.peak, b = sa.biggest_stock;
  return `<div class="card">
    <h2>Sector allocation <span class="pill sec" style="font-size:10px">real backtest data</span></h2>
    <div class="lead">Momentum picks <i>stocks</i>, not sectors — so here's where the money actually lands. All weights are % of the equity book${label?` (${label})`:""}.</div>
    <div class="metrics">
      ${metric("Peak in one sector", fmt(p.weight,0)+"%", p.sector+" · "+p.date, p.weight>=40?"down":(capPct?"up":""))}
      ${metric("Typical top sector", fmt(sa.avg_top,0)+"%", "avg largest sector")}
      ${metric("Sectors held", fmt(sa.avg_sectors,1), "avg spread, out of 11")}
      ${metric("Biggest single stock", b.sym, fmt(b.weight,1)+"% · "+b.date)}
    </div>
    ${sa.infeasible_rebalances>0?`<div class="gapnote" style="text-align:left;margin-top:6px;font-size:11px">The 8% stock cap holds at every rebalance where it's mathematically achievable. At <b>${sa.infeasible_rebalances}</b> rebalance${sa.infeasible_rebalances>1?"s":""} the book was too concentrated (a couple of big sectors + single-stock sectors) for 8% to be possible — there the <b>25% sector cap was kept</b> and a few names ran slightly above 8%.</div>`:""}
    ${capPct
      ? `<div class="disclaimer good"><span class="ic">🛡️</span><div><b>Sector-controlled.</b> A hard <b>${capPct}% cap</b> is applied after weighting, so no sector exceeds ${capPct}% of the book — overflow is redistributed to other sectors. Flip to <b>Uncapped</b> above to see momentum's raw ${fmt(p.weight,0)>=40?"~50%+":""} tilt.</div></div>`
      : (p.weight>=40?`<div class="disclaimer"><span class="ic">⚠️</span><div><b>At its most concentrated, ${fmt(p.weight,0)}% of the equity book sat in ${p.sector}</b> (${p.date}). With no sector cap, momentum can let one sector dominate — switch to <b>Sector-controlled</b> above to hold this at ${25}%.</div></div>`:"")}

    <div class="two" style="margin-top:14px">
      <div>
        <h3 class="mini">Where the money sits today</h3>
        <div class="lead" style="margin-top:2px">The book's sector mix right now — small sectors grouped as “Other”.</div>
        <div id="${prefix}donut" style="height:300px"></div>
      </div>
      <div>
        <h3 class="mini">Most a single sector ever reached</h3>
        <div class="lead" style="margin-top:2px">Peak weight each sector ever hit at one rebalance — hover for the date.</div>
        <div id="${prefix}bars" style="height:300px"></div>
      </div>
    </div>

    <div id="${prefix}rotate" style="margin-top:22px"></div>
  </div>`;
}

function renderSectorCharts(sa, prefix){
  if(!sa || !sa.sectors || !sa.sectors.length) return;
  const last = sa.dates.length - 1;

  // DONUT — today's sector mix, tiny slices grouped into "Other"
  const cur = sa.sectors.map(sec=>({sec, w:sa.series[sec][last]})).filter(o=>o.w>0.05).sort((a,b)=>b.w-a.w);
  const big = cur.filter(o=>o.w>=4), small = cur.filter(o=>o.w<4);
  const dlab = big.map(o=>o.sec), dval = big.map(o=>+o.w.toFixed(1));
  if(small.length){ dlab.push("Other"); dval.push(+small.reduce((s,o)=>s+o.w,0).toFixed(1)); }
  Plotly.newPlot(prefix+"donut",[{
    type:"pie", hole:0.58, labels:dlab.map(secname), values:dval, sort:false, direction:"clockwise",
    marker:{colors:dlab.map(l=>l==="Other"?"#c0c6d4":seccol(l))},
    textinfo:"percent", textfont:{size:11},
    hovertemplate:"<b>%{label}</b><br>%{value}% of book<extra></extra>"
  }],{...LAY, height:300, showlegend:true, legend:{orientation:"h", y:-0.02, font:{size:10}},
      margin:{l:6,r:6,t:6,b:66},
      annotations:[{text:"today", showarrow:false, font:{size:13, color:"#8a8fa6"}}]},PLOT);

  // BARS — the most any single sector ever reached
  const mb = sa.max_by_sector.slice().reverse();
  Plotly.newPlot(prefix+"bars",[{
    type:"bar", orientation:"h",
    x: mb.map(x=>x.weight), y: mb.map(x=>secname(x.sector)),
    marker:{color: mb.map(x=>seccol(x.sector))},
    text: mb.map(x=>fmt(x.weight,0)+"%"), textposition:"auto",
    customdata: mb.map(x=>x.date),
    hovertemplate:"<b>%{y}</b><br>peaked at %{x:.1f}% on %{customdata}<extra></extra>"
  }],{...LAY, height:300, margin:{l:128,r:16,t:6,b:26},
      xaxis:{...LAY.xaxis, type:"linear", ticksuffix:"%", rangemode:"tozero"}, yaxis:{...LAY.yaxis, automargin:true}},PLOT);

  // ROTATION — RupeeCase-style heat-map
  renderSectorHeatmap(sa, prefix+"rotate");
}

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

    ${rbAll.sector?sectorCardHTML(rbAll.sector, "bsec", `${idxName} · ${cmp[bk].universe}`):""}

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

  renderSectorCharts(rbAll.sector, "bsec");

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

// ==================== EQUINEXT DYNAMIC (valuation-momentum + 3-asset switch) ====================
let DYNIDX="n750", DYNWIN="rc", DYNCAP="", DYNSTRAT="", DYNPER="1Y", DYNV=null;
// Resolve the variant key for a universe under the current strategy/cap toggles.
// DYNSTRAT is "" (base), "v2" (multi-layer) or "v2c" (Mode C).
const dynKey = (u, wk) => DYNSTRAT ? (u+DYNSTRAT+"_"+wk) : (u+DYNCAP+"_"+wk);
const PORDER=["1M","3M","6M","1Y","3Y","5Y","Max"];
const PLABEL={"1M":"1 month","3M":"3 months","6M":"6 months","1Y":"1 year","3Y":"3 years","5Y":"5 years","Max":"Since inception"};
// Trailing-window returns for the current dynamic variant, in the toggle+cards style.
function renderDynPeriod(){
  const out=$("#dynperiodout"); if(!out||!DYNV) return;
  const p=(DYNV.periods||[]).find(x=>x.label===PLABEL[DYNPER]);
  if(!p){ out.innerHTML='<div class="lead" style="color:var(--muted);margin-top:12px">Not enough backtest history for this window.</div>'; return; }
  const sgn=x=>(x>=0?"+":"")+fmt(x,1)+"%";
  const exc=p.s-p.n500;
  const note=p.ann
    ? `<div class="lead" style="margin-top:10px">A year or more, so the cards show the <b>total</b> gain over the window; <b>annualised</b> (CAGR per year) it's basket <b class="up">${fmt(p.s_cagr,1)}%</b> vs Nifty 500 <b>${fmt(p.n500_cagr,1)}%</b> vs Nifty 50 <b>${fmt(p.n50_cagr,1)}%</b>.</div>`
    : `<div class="lead" style="margin-top:10px">Window is under a year, so these are <b>total</b> returns for the period — not annualised (annualising a few months would be misleading).</div>`;
  out.innerHTML=`
    <div class="metrics" style="margin-top:12px">
      ${metric("Basket return", sgn(p.s), `${p.from} → ${p.to}`, p.s>=0?"up":"down")}
      ${metric("Nifty 500 return", sgn(p.n500), "same window", p.n500>=0?"up":"down")}
      ${metric("Nifty 50 return", sgn(p.n50), "same window", p.n50>=0?"up":"down")}
      ${metric("Excess vs Nifty 500", sgn(exc), "basket − index", exc>=0?"up":"down")}
    </div>${note}`;
}
async function renderDynamic(){
  const host=$("#dynamic");
  const d=await cachedJSON("/api/dynamic");
  if(!d||!d.ready){ host.innerHTML='<div class="loading">Backtest still computing — refresh in a minute.</div>'; return; }
  const s=d.strategy, rc=d.rupeecase, V=d.variants;
  let v=V[dynKey(DYNIDX, DYNWIN)];
  if(!v && DYNSTRAT){ DYNSTRAT=""; v=V[dynKey(DYNIDX, DYNWIN)]; }          // no V2/Mode C here -> base
  if(!v && DYNCAP){ DYNCAP=""; v=V[DYNIDX+"_"+DYNWIN]; }                    // capped missing -> uncapped
  if(!v){ DYNIDX="n750"; v=V[dynKey("n750", DYNWIN)] || V["n750_"+DYNWIN]; }
  const m=v.metrics;
  const mrow=(label,mm,ae,cls="")=>`<tr class="${cls}"><td>${label}</td>
    <td>${fmt(mm.cagr,1)}%</td><td>${fmt(mm.vol,1)}%</td><td>${fmt(mm.sharpe,2)}</td>
    <td>${fmt(mm.sortino,2)}</td><td class="down">${fmt(mm.maxdd,1)}%</td>
    <td>${fmt(mm.calmar,2)}</td><td>${ae!=null?fmt(ae,0)+"%":"—"}</td><td>₹${fmt(mm.final,0)}</td></tr>`;
  const wins=[["RupeeCase window","rc","Nov 2022 → now · their exact period"],
              ["Full window","full","Aug 2017 → now · incl. COVID crash"]];
  let tbl="";
  wins.forEach(([wname,wk,wsub])=>{
    const b=V["n500_"+wk].bench;
    tbl+=`<tr class="subrow"><td colspan="9" style="padding-top:14px"><b>${wname}</b> <span style="color:var(--muted);font-weight:500;font-size:12px">· ${wsub}</span></td></tr>`;
    const DV=u=>V[dynKey(u,wk)]||V[u+"_"+wk];                 // strategy + cap aware lookup
    const tag = DYNSTRAT==="v2c" ? ' <span class="pill" style="background:#fdeefb;color:#b23aa0;font-size:9px">🧭 Mode C</span>'
              : DYNSTRAT==="v2" ? ' <span class="pill" style="background:#eef0ff;color:#4a5ad8;font-size:9px">🧪 V2</span>'
              : DYNCAP ? ' <span class="pill" style="background:#e7f6ef;color:#0a8f5f;font-size:9px">🛡️ 25%</span>' : "";
    tbl+=mrow("Nifty 50 index", b.nifty50, null);
    tbl+=mrow("Nifty 500 index", b.nifty500, null);
    tbl+=mrow("<b>Dynamic · Nifty 500</b>"+tag, DV("n500").metrics, DV("n500").metrics.avg_eq, "selrow");
    tbl+=mrow("<b>Dynamic · Total Market</b>"+tag, DV("n750").metrics, DV("n750").metrics.avg_eq, "selrow");
    if(DV("rc")) tbl+=mrow('<b>RupeeCase Stocks</b> <span class="pill sec" style="font-size:9.5px">their picks</span>'+tag, DV("rc").metrics, DV("rc").metrics.avg_eq, "selrow");
    if(wk==="rc") tbl+=`<tr style="opacity:.7"><td>RupeeCase <span class="pill sec" style="font-size:9.5px">claimed</span></td>
      <td>${rc.cagr}%</td><td>${rc.vol}%</td><td>${rc.sharpe}</td><td>${rc.sortino}</td>
      <td class="down">${rc.maxdd}%</td><td>${rc.calmar}</td><td>—</td><td>₹${rc.final}</td></tr>`;
  });
  const step=st=>`<div class="step"><div class="top"><div class="num">${st.n}</div>
    <div><div class="ttl">${st.title}</div><div class="role">${st.role}</div></div></div>
    <div class="why">${st.why}</div><ul>${st.criteria.map(c=>`<li>${c}</li>`).join("")}</ul></div>`;
  // Momentum-only baskets skip the valuation & earnings gates — show the accurate recipe.
  const isMom=!!v.momentum_only;
  const vsteps=(isMom ? s.steps.filter(st=>!/valuation gate|earnings-backed/i.test(st.title)) : s.steps)
    .map((st,i)=>{ const o={...st,n:i+1};
      if(isMom && /momentum score/i.test(st.title)){
        o.role="Ranks (no filter first)";
        o.why="Rank the WHOLE universe by trend strength and take the top 50, inverse-vol weighted. No valuation or earnings gate is applied before this — momentum alone decides.";
      }
      return o; });
  // V2 / Mode C get their own accurate build recipe (the base steps don't describe the tiers/gates).
  const v2info = v.strategy_v2 ? [
    {n:1, title:"Universe", role:"Eligibility", why:`Start from ${v.label.replace(/ · (V2|Mode C)$/,"")}, liquid & free-float-eligible names.${v.momentum_only?" (Momentum-only — no valuation history for these names.)":""}`, criteria:["Liquidity & free-float gates"]},
    {n:2, title:"Cap-tiers", role:"Size split", why:"Split the universe by market-cap rank into Large (top 100), Mid (101–250) and Small (251–500).", criteria:["Large / Mid / Small buckets"]},
    {n:3, title:"Stock selection · per tier", role:"Rank + gate", why:`Inside each tier: rank by momentum (12-1, 52w-high, volume), then drop ${v.momentum_only?"":"frothy (P/E), non-earnings-backed, "}${v.no_dma?"":"below-200-DMA, "}rolling-over (3/6/12-mo) and blow-off-top (RSI(30)>80) names. Take top-N, inverse-vol weighted.`, criteria:[...(v.momentum_only?[]:["P/E froth + earnings gate"]),...(v.no_dma?[]:["200-DMA trend gate"]),"Multi-timeframe momentum","RSI(30)>80 exclude","Inverse-vol weighting"]},
    v.mode_c
      ? {n:4, title:"Tier allocation · Mode C", role:"Fixed anchor + rotation", why:`A FIXED ${v.anchor_pct||40}% large-cap anchor stays put; the rest rotates to whichever of mid- or small-cap has stronger 6-month momentum.`, criteria:[`Large-cap fixed at ${v.anchor_pct||40}%`,"Satellite → mid or small by relative momentum"]}
      : {n:4, title:"Tier allocation · regime dial", role:"Size risk-switch", why:"Scale the size mix by market regime: risk-on → tilt to mid/small; neutral → mostly large; risk-off → 100% large-cap.", criteria:["Risk-on 45/35/20","Neutral 70/20/10","Risk-off 100/0/0"]},
    {n:5, title:"Risk caps", role:"Concentration control", why:"On the combined book: no sector above 25%, no single stock above 8% (waterfall redistribution).", criteria:["25% sector cap","8% stock cap"]},
    {n:6, title:"3-Asset dial", role:"Risk dial", why:"Wrap the equity book in the dynamic switch — a 35% equity core, a 40% equity↔debt sleeve and a 25% equity↔gold sleeve by 3-mo momentum. Equity floats 35–100%.", criteria:["35% equity core","40% eq↔debt · 25% eq↔gold","Debt ~6.5%/yr · Gold = GoldBees"]},
  ] : null;
  const ddRow=r=>`<tr><td>${r.started}</td><td>${r.trough}</td><td>${r.recovered}</td>
    <td class="down"><b>${fmt(r.max_dd,1)}%</b></td><td>${r.duration_days} days</td></tr>`;
  const chips=(arr,cls)=>arr.map(x=>`<span class="tchip ${cls}">${x}</span>`).join("");
  const rebRow=r=>{
    const ch=(r.bought.length||r.sold.length)
      ? `${r.bought.length?'<span class="tlabel">In</span>'+chips(r.bought,"buy"):""}${r.sold.length?'<span class="tlabel">Out</span>'+chips(r.sold,"sell"):""}`
      : '<span style="color:var(--muted)">No change</span>';
    return `<div class="rev"><div class="date">${r.date}</div><div class="changes">${ch}</div>
      <div class="meta">${r.n} held · ${r.kept} kept · ${fmt(r.turnover,0)}% traded</div></div>`;
  };
  const holdRow=(h,i)=>`<tr><td style="color:var(--muted)">${i+1}</td><td><b>${h.sym}</b></td>
    <td style="color:var(--sub)">${h.name}</td><td>${fmt(h.w_book,1)}%</td><td>${fmt(h.w_port,1)}%</td></tr>`;

  host.innerHTML=`
    <div class="hero"><div><h1>${s.name}</h1><div class="tag">${s.tagline}</div></div>
      <div class="asof">${s.cadence} · real backtest data</div></div>

    <div class="card" style="margin-top:14px">
      <h2>Backtested results — dynamic monthly</h2>
      <div class="lead">Valuation-momentum equity wrapped in a monthly 3-asset switch, on <b>two universes</b> across <b>two windows</b>. Index benchmarks and RupeeCase's claimed figures shown for reference.</div>
      <table><thead><tr><th>Strategy</th><th>CAGR</th><th>Vol</th><th>Sharpe</th><th>Sortino</th><th>Max DD</th><th>Calmar</th><th>Avg Eq</th><th>₹100→</th></tr></thead>
      <tbody>${tbl}</tbody></table>
      <div class="gapnote" style="text-align:left;margin-top:14px">The <b>Full window</b> numbers (incl. the −38% COVID crash) are the trustworthy, crash-tested ones. RupeeCase's 45% is a <b>bull-only, small-cap-heavy</b> figure their backtest never stress-tested against a real bear market.</div>
    </div>

    <div class="toggles">
      <div class="btoggle" id="dynidx">
        <button data-i="n500" class="${DYNIDX==="n500"?"on":""}">Nifty 500<small>500 stocks</small></button>
        <button data-i="n750" class="${DYNIDX==="n750"?"on":""}">Total Market<small>~750 stocks</small></button>
        <button data-i="rc" class="${DYNIDX==="rc"?"on":""}">RupeeCase Stocks<small>their ~240</small></button>
      </div>
      <div class="btoggle" id="dynstrat">
        <button data-s="" class="${DYNSTRAT===""?"on":""}">Base strategy<small>momentum + dial</small></button>
        <button data-s="v2" class="${DYNSTRAT==="v2"?"on":""}">V2 multi-layer<small>tiers + signals</small></button>
        <button data-s="v2c" class="${DYNSTRAT==="v2c"?"on":""}">Mode C<small>anchor + rotation</small></button>
      </div>
      <div class="btoggle" id="dynwin">
        <button data-w="rc" class="${DYNWIN==="rc"?"on":""}">RupeeCase window<small>2022→now</small></button>
        <button data-w="full" class="${DYNWIN==="full"?"on":""}">Full window<small>2017→now</small></button>
      </div>
      <div class="btoggle" id="dyncap">
        <button data-c="" class="${DYNCAP===""?"on":""}">Uncapped<small>momentum's raw tilt</small></button>
        <button data-c="cap" class="${DYNCAP==="cap"?"on":""}">Sector-controlled<small>max 25% / sector</small></button>
      </div>
    </div>

    <div class="card">
      <h2>${v.label} ${v.mode_c?`<span class="pill" style="background:#fdeefb;color:#b23aa0;font-size:10px;vertical-align:middle">🧭 MODE C</span>`:(v.strategy_v2?`<span class="pill" style="background:#eef0ff;color:#4a5ad8;font-size:10px;vertical-align:middle">🧪 V2 MULTI-LAYER</span>`:(v.sector_capped?`<span class="pill" style="background:#e7f6ef;color:#0a8f5f;font-size:10px;vertical-align:middle">🛡️ SECTOR-CONTROLLED · ${v.cap_pct}% cap</span>`:""))} · ${DYNWIN==="rc"?"RupeeCase window":"Full window"} <span style="color:var(--muted);font-weight:500;font-size:14px">· ${v.start} → ${v.end}</span></h2>
      ${v.mode_c?`<div class="disclaimer${v.momentum_only?" good":""}"><span class="ic">🧭</span><div><b>Mode C — fixed anchor + size rotation.</b> The V2 multi-layer strategy, but the size mix uses a <b>fixed ${v.anchor_pct||40}% large-cap anchor</b> and a <b>satellite that rotates to whichever of mid- / small-cap has stronger 6-month momentum</b>. ${v.momentum_only?"On this volatile small-cap book Mode C <b>beats the simpler Base basket</b> on both windows — tuned to a "+(v.anchor_pct||40)+"% anchor.":"It beat the other tier designs (A/B) but still <b>trailed the simpler Base book</b> on this universe — shown for comparison."}</div></div>`
        : v.strategy_v2?`<div class="disclaimer"><span class="ic">🧪</span><div><b>Experimental multi-layer strategy (V2).</b> Momentum ranked, then run through cap-tiers (large/mid/small), a 200-DMA trend gate, multi-timeframe momentum, an RSI(30)&gt;80 blow-off filter, a regime-scaled satellite, and a 25% sector + 8% stock cap — all wrapped in the 3-asset dial. In our ablation this <b>under-performed</b> the simpler sector-capped Base book; it's here so you can compare directly.</div></div>`:""}
      ${v.momentum_only?`<div class="disclaimer"><span class="ic">⚠️</span><div><b>Momentum-only on RupeeCase's own published holdings</b> (no valuation gates). This universe is <b>survivorship-tilted</b> — it's the set their momentum eventually rode to winners — so treat the return as an <b>upper bound</b>, not a clean forward test.</div></div>`:""}
      <div class="metrics">
        ${metric("Return (CAGR)", fmt(m.cagr,1)+"%", `Nifty 500: ${fmt(v.bench.nifty500.cagr,1)}%`, "up")}
        ${metric("Volatility", fmt(m.vol,1)+"%", `annualised · Nifty 500: ${fmt(v.bench.nifty500.vol,1)}%`)}
        ${metric("Sharpe", fmt(m.sharpe,2), "return per unit of risk")}
        ${metric("Sortino", fmt(m.sortino,2), "return per unit of downside")}
        ${metric("Max Drawdown", fmt(m.maxdd,1)+"%", "worst peak-to-trough", "down")}
        ${metric("Calmar", fmt(m.calmar,2), "return ÷ drawdown")}
        ${metric("Avg equity", fmt(m.avg_eq,0)+"%", "in stocks (dial 35–100%)")}
        ${metric("Avg debt", fmt(m.avg_debt,0)+"%", "liquid ~6.5%/yr")}
        ${metric("Avg gold", fmt(m.avg_gold,0)+"%", "GoldBees ETF")}
        ${metric("₹100 grew to", "₹"+fmt(m.final,0), `Nifty 500: ₹${fmt(v.bench.nifty500.final,0)}`)}
      </div>
      <div class="legend" style="margin-top:16px"><span><b style="background:${GREEN}"></b>Equinext Dynamic</span><span><b style="background:${GRAY}"></b>Nifty 500</span><span><b style="background:${VIOLET}"></b>Nifty 50</span></div>
      <div id="dyncurve" style="height:320px"></div>
    </div>

    ${v.periods?`<div class="card">
      <h2>Returns by period <span class="pill sec" style="font-size:10px">real backtest data</span></h2>
      <div class="lead">The CAGR above covers the whole backtest. Pick a trailing window below to see how <b>${v.label}</b> did versus the Nifty indices over just that stretch — computed straight from the daily backtest curve.</div>
      <div class="btoggle" id="dynperiod" style="margin-top:6px">${PORDER.map(c=>`<button data-p="${c}" class="${c===DYNPER?"on":""}">${c}</button>`).join("")}</div>
      <div id="dynperiodout"></div>
    </div>`:""}

    ${v.current_holdings?`<div class="card">
      <h2>Current holdings <span style="color:var(--muted);font-weight:500;font-size:14px">· as of ${v.current_holdings.asof}</span></h2>
      <div class="lead">Where the money sits today under the monthly dial, then the stocks in the equity book right now (${v.label}), ranked by weight.</div>
      <div class="metrics">
        ${metric("Equity", fmt(v.current.eq,0)+"%", "in stocks now", "up")}
        ${metric("Debt", fmt(v.current.debt,0)+"%", "liquid ~6.5%/yr")}
        ${metric("Gold", fmt(v.current.gold,0)+"%", "GoldBees ETF")}
        ${metric("Stocks held", v.current_holdings.stocks.length, "in the equity book")}
      </div>
      <div style="max-height:460px;overflow:auto;margin-top:14px">
      <table><thead><tr><th>#</th><th>Stock</th><th>Name</th><th>% of book</th><th>% of portfolio</th></tr></thead>
      <tbody>${v.current_holdings.stocks.map(holdRow).join("")}</tbody></table>
      </div>
      <div class="gapnote" style="text-align:left;margin-top:12px"><b>% of book</b> = weight inside the ≤50-stock equity sleeve (sums to 100%). <b>% of portfolio</b> = effective weight after the dial — equity is ${fmt(v.current.eq,0)}% of the whole portfolio today, the rest sits in debt + gold.</div>
    </div>`:""}

    ${sectorCardHTML(v.sector, "sec", v.label, v.cap_pct)}

    <div class="card">
      <h2>Worst 5 drawdowns <span class="pill sec" style="font-size:10px">real backtest data</span></h2>
      <div class="lead">The five deepest peak-to-trough falls of this basket over ${DYNWIN==="rc"?"the RupeeCase window":"the full window"} — measured on the daily equity curve.</div>
      <table><thead><tr><th>Started (peak)</th><th>Trough</th><th>Recovered</th><th>Max Drawdown</th><th>Duration</th></tr></thead>
      <tbody>${v.drawdowns.map(ddRow).join("")}</tbody></table>
    </div>

    <div class="card">
      <h2>How this basket is built</h2>
      ${v2info
        ? `<div class="lead">${v.mode_c
              ? "<b>Mode C</b> — the multi-layer V2 engine, but the size mix uses a <b>fixed large-cap anchor</b> with a <b>mid↔small momentum rotation</b> (your design). Six steps, applied every rebalance."
              : "<b>V2 multi-layer</b> — momentum wrapped in cap-tiers, extra technical gates, a regime-scaled size dial and hard caps. Six steps, applied every rebalance."}
           </div>
           <div class="steps">${v2info.map(step).join("")}</div>`
        : `${isMom
              ? `<div class="disclaimer"><span class="ic">⚠️</span><div><b>Momentum only — no valuation or earnings gates.</b> This basket ranks purely by momentum and skips the P/E-froth and earnings-backed filters. Steps below reflect what this basket actually does.</div></div>`
              : `<div class="lead">Full <b>valuation-momentum</b> recipe: momentum <b>ranks</b>, valuation & earnings <b>gate</b> out the risky names — then the 3-asset dial.</div>`}
           <div class="lead">Weighting: ${s.weighting}</div>
           ${v.sector_capped?`<div class="lead">🛡️ <b>Sector cap:</b> after inverse-vol weighting, a hard <b>${v.cap_pct}% per-sector cap</b> is applied — overflow redistributed to sectors with room, so no single sector runs the book.</div>`:""}
           <div class="steps">${vsteps.map(step).join("")}</div>`}
    </div>

    ${v.rebalances?`<div class="card">
      <h2>Rebalance History <span style="color:var(--muted);font-weight:500;font-size:14px">· ${v.rebalances.length} monthly rebalances</span></h2>
      <div class="lead">Every month the equity book is re-ranked by momentum from the <b>${v.label}</b> universe — here's exactly what it bought and sold each time. Newest first.</div>
      <div class="rebal" style="max-height:540px;overflow:auto">${v.rebalances.map(rebRow).join("")}</div>
    </div>`:""}`;

  const cs=v.curve;
  const tr=[{x:cs.strategy.dates,y:cs.strategy.values,type:"scatter",mode:"lines",line:{color:GREEN,width:2.8},name:"Equinext Dynamic"},
    {x:cs.nifty500.dates,y:cs.nifty500.values,type:"scatter",mode:"lines",line:{color:GRAY,width:1.5},name:"Nifty 500"},
    {x:cs.nifty50.dates,y:cs.nifty50.values,type:"scatter",mode:"lines",line:{color:VIOLET,width:1.2},name:"Nifty 50"}];
  Plotly.newPlot("dyncurve",tr,{...LAY,height:320,yaxis:{...LAY.yaxis,tickprefix:"₹"}},PLOT);

  renderSectorCharts(v.sector, "sec");

  DYNV=v;
  document.querySelectorAll("#dynperiod button").forEach(b=>b.onclick=()=>{
    DYNPER=b.dataset.p;
    document.querySelectorAll("#dynperiod button").forEach(x=>x.classList.toggle("on", x===b));
    renderDynPeriod();
  });
  renderDynPeriod();

  document.querySelectorAll("#dynidx button").forEach(b=>b.onclick=()=>{ DYNIDX=b.dataset.i; renderDynamic(); });
  document.querySelectorAll("#dynstrat button").forEach(b=>b.onclick=()=>{ DYNSTRAT=b.dataset.s; renderDynamic(); });
  document.querySelectorAll("#dynwin button").forEach(b=>b.onclick=()=>{ DYNWIN=b.dataset.w; renderDynamic(); });
  document.querySelectorAll("#dyncap button").forEach(b=>b.onclick=()=>{ if(DYNSTRAT) return; DYNCAP=b.dataset.c; renderDynamic(); });
  if(DYNSTRAT) document.querySelectorAll("#dyncap button").forEach(b=>{ b.disabled=true; b.style.opacity=.4; b.title="V2 / Mode C already include the 25% sector + 8% stock cap"; });
}

// nav
function switchView(v){
  document.querySelectorAll(".navtab").forEach(b=>b.classList.toggle("active",b.dataset.view===v));
  $("#basket-view").hidden=v!=="basket"; $("#stocks-view").hidden=v!=="stocks";
  $("#compare-view").hidden=v!=="compare"; $("#dynamic-view").hidden=v!=="dynamic";
  if(v==="compare") renderCompareAll();
  if(v==="dynamic") renderDynamic();
}
boot();
