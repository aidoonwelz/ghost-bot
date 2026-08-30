#!/usr/bin/env python3
"""
Ghost — EMA 9x21 daily multi-asset trend bot (paper). Runs once per invocation.
Hosted free on GitHub Actions (daily). Coins via Coinbase, stocks via Yahoo.
Long/flat with leverage + liquidation. Texts a daily summary via Telegram.
Secrets (TELEGRAM_TOKEN / TELEGRAM_CHAT) come from env (GitHub Actions secrets).
"""
import json, os, urllib.request, urllib.parse, datetime as dt, time

# ---------------- CONFIG ----------------
LEVERAGE   = 3.0
COINS      = ["BTC-USD","ETH-USD","SOL-USD","XRP-USD","DOGE-USD","LINK-USD"]
STOCKS     = ["AAPL","TSLA","NVDA","SPY"]
UNIVERSE   = COINS + STOCKS
FAST, SLOW = 9, 21
PAPER_START= 10000.0
FEE        = 0.001
BASE       = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "portfolio.json")     # committed back by the workflow
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT", "")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# ---------------- DATA ----------------
def _get(url):
    last=None
    for _ in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read()
        except Exception as e: last=e; time.sleep(2)
    raise last
def market_series(a):
    if a in COINS:
        raw=json.loads(_get(f"https://api.exchange.coinbase.com/products/{a}/candles?granularity=86400"))
        raw.sort(key=lambda r:r[0])
        return [r[4] for r in raw], dt.datetime.fromtimestamp(raw[-1][0], dt.timezone.utc).date().isoformat()
    j=json.loads(_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{a}?range=1y&interval=1d"))
    result=j["chart"]["result"][0]
    rows=[(t,c) for t,c in zip(result["timestamp"],result["indicators"]["quote"][0]["close"]) if c is not None]
    return [c for _,c in rows], dt.datetime.fromtimestamp(rows[-1][0], dt.timezone.utc).date().isoformat()
def ema(v,n):
    k=2/(n+1); e=[v[0]]
    for x in v[1:]: e.append(x*k+e[-1]*(1-k))
    return e
def bull(cl):
    if len(cl)<SLOW+2: return None,None
    ef,es=ema(cl,FAST),ema(cl,SLOW); return ef[-1]>es[-1], cl[-1]

# ---------------- PORTFOLIO ----------------
def load_pf():
    if os.path.exists(STATE_FILE):
        pf=json.load(open(STATE_FILE))
    else:
        sl=PAPER_START/len(UNIVERSE)
        pf={"start":PAPER_START,"realized":0.0,"trades":0,"liquidations":0,"history":[],
            "pos":{a:{"cash":sl,"units":0.0,"entry":None,"margin":0.0,"liq":None} for a in UNIVERSE}}
    pf.setdefault("history",[]); pf.setdefault("last_bars",{}); pf["leverage"]=LEVERAGE
    missing=[a for a in UNIVERSE if a not in pf["pos"]]
    if missing and all(p.get("units",0)<=0 for p in pf["pos"].values()):
        # Older state files contained only crypto. Rebalance idle paper cash once
        # so newly added stock symbols can participate without changing equity.
        pool=sum(p.get("cash",0) for p in pf["pos"].values())
        share=pool/len(UNIVERSE)
        for p in pf["pos"].values(): p["cash"]=share
        for a in missing: pf["pos"][a]={"cash":share,"units":0.0,"entry":None,"margin":0.0,"liq":None}
    else:
        for a in missing: pf["pos"][a]={"cash":0.0,"units":0.0,"entry":None,"margin":0.0,"liq":None}
    for p in pf["pos"].values():
        p.setdefault("cash",0.0); p.setdefault("units",0.0); p.setdefault("entry",None)
        p.setdefault("margin",0.0); p.setdefault("liq",None); p.setdefault("last_price",p.get("entry"))
    return pf
def save_pf(pf): json.dump(pf, open(STATE_FILE,"w"), indent=2)
def send(msg):
    print(msg)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            data=urllib.parse.urlencode({"chat_id":TELEGRAM_CHAT,"text":msg}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data=data,timeout=10)
        except Exception as e: print(f"  (telegram failed: {e})")

# ---------------- RUN ONCE ----------------
def run():
    pf=load_pf(); actions=[]; equity=0.0; rows=[]
    for a in UNIVERSE:
        p=pf["pos"][a]
        try:
            close_values,bar_date=market_series(a)
            b,price=bull(close_values)
            if b is None: continue
        except Exception as e:
            print(f"  {a} ERR {e}")
            price=p.get("last_price") or p.get("entry")
            val=max(0.0,p["margin"]+p["units"]*(price-p["entry"])) if p["units"]>0 and price else p["cash"]
            equity+=val; rows.append(f"⚠️ {a.replace('-USD','')} stale"); continue
        p["last_price"]=price; inpos=p["units"]>0
        is_new_bar=pf["last_bars"].get(a)!=bar_date
        if is_new_bar and inpos and price<=p["liq"]:
            pf["realized"]-=p["margin"]; pf["liquidations"]+=1
            actions.append(f"💀 LIQUIDATED {a} @ ${price:,.4f}")
            p.update({"cash":0.0,"units":0.0,"entry":None,"margin":0.0,"liq":None}); val=0.0
        elif is_new_bar and inpos and not b:
            pnl=p["units"]*(price-p["entry"])-p["units"]*price*FEE
            cash=max(0.0,p["margin"]+pnl); pf["realized"]+=pnl
            actions.append(f"🔴 SELL {a} @ ${price:,.4f} (P&L ${pnl:+,.0f})")
            p.update({"cash":cash,"units":0.0,"entry":None,"margin":0.0,"liq":None}); val=cash
        elif inpos:
            val=max(0.0,p["margin"]+p["units"]*(price-p["entry"]))
        elif is_new_bar and b and p["cash"]>0:
            m=p["cash"]; units=m*LEVERAGE*(1-FEE)/price
            p.update({"units":units,"entry":price,"margin":m,"cash":0.0,"liq":price*(1-0.95/LEVERAGE)})
            pf["trades"]+=1; actions.append(f"🟢 BUY {a} @ ${price:,.4f} ({LEVERAGE:g}x)")
            val=m
        else: val=p["cash"]
        pf["last_bars"][a]=bar_date
        equity+=val
        short=a.replace("-USD","")
        rows.append(f"{'🟢' if p['units']>0 else '⚪️'} {short} {'LONG' if p['units']>0 else 'cash'}")
    ret=(equity/pf["start"]-1)*100
    pf["last_equity"]=round(equity,2); pf["last_ret"]=round(ret,2)
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    pf["updated_at"]=now; pf["last_ts"]=now
    pf["history"].append({"t":now,"equity":round(equity,2)})
    pf["history"]=pf["history"][-365:]
    save_pf(pf)
    body = (("👻 Ghost daily update:\n"+"\n".join(actions)+"\n\n") if actions else "👻 Ghost daily — no new trades\n\n")
    body += "  ".join(rows) + f"\n\n💰 ${equity:,.2f} ({ret:+.2f}%) | realized ${pf['realized']:+,.2f} | {pf['liquidations']} liq"
    send(body)

if __name__ == "__main__":
    run()
