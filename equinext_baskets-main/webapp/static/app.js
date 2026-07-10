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

let STOCKS = [], CUR = null, RANGE = 252, _price = 0;

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
  const [s, b, rbAll] = await Promise.all([
    (await fetch("/api/strategy")).json(),
    (await fetch("/api/basket")).json(),
    (await fetch("/api/rebalances")).json(),
  ]);
  const REB = rbAll.rebalances || [];
  const m = b.metrics, excess = (m.cagr != null && m.cagr_nifty != null) ? m.cagr - m.cagr_nifty : null;
  $("#basket").innerHTML = `
    <div class="hero">
      <div><h1>${s.name}</h1><div class="tag">${s.tagline}</div></div>
      <div class="asof">Rebalanced ${s.rebalance} · as of ${b.as_of || "—"}</div>
    </div>
    <div class="metrics">
      ${metric("Return (CAGR)", fmt(m.cagr,1)+"%", `Nifty 50: ${fmt(m.cagr_nifty,1)}%`, "up")}
      ${metric("Beats Nifty by", (excess>=0?"+":"")+fmt(excess,1)+"% / yr", "annualised excess", excess>=0?"up":"down")}
      ${metric("Sharpe", fmt(m.sharpe,2), "return per unit of risk")}
      ${metric("Max Drawdown", fmt(m.max_dd,1)+"%", "worst fall (Nifty −38%)", "down")}
      ${metric("₹100 grew to", "₹"+fmt(m.final,0), `Nifty: ₹${fmt(m.final_nifty,0)} · ${fmt(m.years,1)}y`)}
    </div>

    <div class="disclaimer">
      <span class="ic">⚠️</span>
      <div><b>Why this number is optimistic.</b> These results are backtested on <b>today's</b> Nifty 50 applied to the past — which quietly leaves out companies that were later dropped from the index after falling (this is called <b>survivorship bias</b>). It flatters the returns, so treat the CAGR as an <b>upper bound</b>, not the expected live result.
        <details><summary>Read more</summary>
          <p>By using the current 50 constituents backward, we keep the winners and erase the losers that dropped out over the years — so any backtest looks better than reality. The good news: this strategy also beat the Nifty on earlier, different stock sets, so the edge is genuine — just <b>smaller</b> than shown here. The honest fix is <b>point-in-time index membership</b> (testing whoever was actually in the index on each date, losers included), which is the next planned step.</p>
        </details>
      </div>
    </div>

    <div class="card">
      <h3 class="mini">Growth of ₹100 — Basket vs Nifty 50</h3>
      <div class="legend"><span><b style="background:${GREEN}"></b>Basket</span><span><b style="background:${GRAY}"></b>Nifty 50</span></div>
      <div id="curve" style="height:320px"></div>
    </div>

    <div class="card">
      <h2>How this basket is built</h2>
      <div class="lead">Four steps, applied fresh every quarter. Momentum <b>ranks</b> the stocks; valuation & earnings <b>gate</b> out the risky ones.</div>
      <div class="steps">${s.steps.map(stepCard).join("")}</div>
    </div>

    <div class="card">
      <h2>${s.selection.title}</h2>
      <div class="selbox">
        <ol>${s.selection.points.map(p=>`<li>${boldFirst(p)}</li>`).join("")}</ol>
        <div class="flow">
          <div class="fbox"><b>Step 1</b>${s.n_universe} Nifty 50 stocks</div>
          <div class="arrow">↓ &nbsp;filter</div>
          <div class="fbox"><b>Gates 2 & 4</b>Drop frothy & hype-driven</div>
          <div class="arrow">↓ &nbsp;rank</div>
          <div class="fbox"><b>Step 3</b>Rank survivors by momentum</div>
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
      <h2>Rebalance History <span style="color:var(--muted);font-weight:500;font-size:14px">· ${REB.length} quarters</span></h2>
      <div class="lead">Every quarter the basket is rebuilt — here's exactly what it bought and sold each time.</div>
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

  if(b.curve && b.curve.dates){
    Plotly.newPlot("curve",[
      {x:b.curve.dates,y:b.curve.nifty,type:"scatter",mode:"lines",line:{color:GRAY,width:1.6},name:"Nifty"},
      {x:b.curve.dates,y:b.curve.basket,type:"scatter",mode:"lines",line:{color:GREEN,width:2.4},
        fill:"tozeroy",fillcolor:"rgba(0,179,134,.07)",name:"Basket"}],
      {...LAY,height:320,yaxis:{...LAY.yaxis,tickprefix:"₹"}},PLOT);
  }
  document.querySelectorAll("#basket tbody tr").forEach(r=>r.onclick=()=>{switchView("stocks");selectStock(r.dataset.sym);});
}
const metric = (k,v,sub,c="") => `<div class="metric"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="sub">${sub}</div></div>`;
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
  const d=await (await fetch("/api/stock/"+sym)).json();
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

// nav
function switchView(v){
  document.querySelectorAll(".navtab").forEach(b=>b.classList.toggle("active",b.dataset.view===v));
  $("#basket-view").hidden=v!=="basket"; $("#stocks-view").hidden=v!=="stocks";
}
boot();
