"""
Headless-browser (Selenium) fundamentals scraper for screener.in.

Screener now serves the financials of many mid/small companies only to LOGGED-IN
users (the plain requests scraper and even a logged-out browser get the page
skeleton with no numbers). This renders the authenticated page in headless Chrome,
then reuses the SAME parse_annual + build_series pipeline as scrape_screener.py.

AUTH — provide a logged-in screener session cookie (free account):
  1. Log in to https://www.screener.in in your normal browser.
  2. DevTools (F12) -> Application/Storage -> Cookies -> screener.in -> copy the
     value of the  sessionid  cookie.
  3. Run with it in the environment:

     SCREENER_SESSIONID=<value> python scripts/scrape_screener_js.py --missing
     SCREENER_SESSIONID=<value> python scripts/scrape_screener_js.py ABBOTINDIA PAGEIND

Without the cookie only ungated (large-cap) pages return data. Requires: pip
install selenium (done) + Chrome (present). Polite 2.5s between pages.
"""
from __future__ import annotations
import os
import re
import sys
import time
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scripts.scrape_screener import (                       # noqa: E402
    parse_annual, build_series, _write_snapshot, _f,
    PROJECT_DB, SOURCE_DB, CACHE, DELAY_S,
)

_NUM = re.compile(r"\b\d[\d,]{2,}\b")


def make_driver():
    o = Options()
    for a in ("--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1400,1000"):
        o.add_argument(a)
    o.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    d = webdriver.Chrome(options=o)
    d.set_page_load_timeout(45)
    return d


def authenticate(driver, sessionid: str):
    """Inject a logged-in screener session cookie (must be on the domain first)."""
    if not sessionid:
        return
    driver.get("https://www.screener.in/")
    time.sleep(1.0)
    driver.add_cookie({"name": "sessionid", "value": sessionid,
                       "domain": ".screener.in", "path": "/"})


def render(driver, sym: str) -> str | None:
    """Load the company page (consolidated, then standalone) and return the fully
    rendered HTML only if the P&L actually contains numbers (not the gated skeleton)."""
    for suffix in ("consolidated/", ""):
        try:
            driver.get(f"https://www.screener.in/company/{sym}/{suffix}")
        except Exception:
            continue
        time.sleep(3.0)
        html = driver.page_source
        if 'id="profit-loss"' not in html:
            continue
        pl = BeautifulSoup(html, "html.parser").find(id="profit-loss")
        if pl and _NUM.search(pl.get_text(" ", strip=True)):
            return html
    return None


def main(argv):
    sessionid = os.environ.get("SCREENER_SESSIONID", "").strip()
    prj = sqlite3.connect(str(PROJECT_DB))
    if "--missing" in argv:
        tm = {r[0] for r in prj.execute("SELECT symbol FROM pools WHERE pool='n500_pool'")}
        have = {r[0] for r in prj.execute("SELECT DISTINCT symbol FROM valuation_series")}
        syms = sorted(tm - have)
    else:
        syms = [a.upper() for a in argv if not a.startswith("--")]

    print(f"auth: {'session cookie SET' if sessionid else 'NO COOKIE (gated pages will fail)'} | "
          f"{len(syms)} symbols")
    src = sqlite3.connect(str(SOURCE_DB))
    fins = {r[0] for r in prj.execute("SELECT symbol FROM securities WHERE sector='Financial Services'")}
    driver = make_driver()
    authenticate(driver, sessionid)
    ok, fail = [], []
    try:
        for i, sym in enumerate(syms, 1):
            try:
                html = render(driver, sym)
                if not html:
                    print(f"  [{i:>2}/{len(syms)}] {sym:<12} GATED / no numbers"); fail.append(sym); continue
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / f"{sym}.html").write_text(html, encoding="utf-8")
                ann = parse_annual(html)
                if not ann:
                    print(f"  [{i:>2}/{len(syms)}] {sym:<12} PARSE FAILED"); fail.append(sym); continue
                df = build_series(sym, ann, sym in fins, src)
                if df.empty:
                    print(f"  [{i:>2}/{len(syms)}] {sym:<12} no series (no price?)"); fail.append(sym); continue
                prj.execute("DELETE FROM valuation_series WHERE symbol=?", (sym,))
                prj.executemany(
                    "INSERT OR REPLACE INTO valuation_series(symbol,date,pe,pb,ev_ebitda,fcf_yield,eps_ttm) "
                    "VALUES(?,?,?,?,?,?,?)",
                    [(sym, d.strftime("%Y-%m-%d"), _f(r["pe"]), _f(r["pb"]), _f(r["ev_ebitda"]),
                      _f(r["fcf_yield"]), _f(r["eps_ttm"])) for d, r in df.iterrows()])
                _write_snapshot(prj, sym, ann)
                prj.commit()
                avail = "+".join(c[:4].upper() for c in ("pe", "pb", "ev_ebitda", "fcf_yield") if df[c].notna().any())
                print(f"  [{i:>2}/{len(syms)}] {sym:<12} {len(df):>5} rows OK [{avail}]"); ok.append(sym)
            except Exception as e:
                print(f"  [{i:>2}/{len(syms)}] {sym:<12} ERROR {str(e)[:50]}"); fail.append(sym)
            time.sleep(DELAY_S)
    finally:
        driver.quit(); prj.close(); src.close()
    print(f"\nDONE  ok={len(ok)}  fail={len(fail)}")
    if fail:
        print("FAILED:", fail)


if __name__ == "__main__":
    main(sys.argv[1:])
