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
def closes(a):
    if a in COINS:
        raw=json.loads(_get(f"https://api.exchange.coinbase.com/products/{a}/candles?granularity=86400"))
        raw.sort(key=lambda r:r[0]); return [r[4] for r in raw]
    j=json.loads(_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{a}?range=1y&interval=1d"))
    c=j["chart"]["result"][0]["indicators"]["quote"][0]["close"]; return [x for x in c if x is not None]
def ema(v,n):
    k=2/(n+1); e=[v[0]]
    for x in v[1:]: e.append(x*k+e[-1]*(1-k))
    return e
def bull(cl):
    if len(cl)<SLOW+2: return None,None
    ef,es=ema(cl,FAST),ema(cl,SLOW); return ef[-1]>es[-1], cl[-1]

# ---------------- PORTFOLIO ----------------
def load_pf():
    if os.path.exists(STATE_FILE): return json.load(open(STATE_FILE))
    sl=PAPER_START/len(UNIVERSE)
    return {"start":PAPER_START,"realized":0.0,"trades":0,"liquidations":0,"history":[],
            "pos":{a:{"cash":sl,"units":0.0,"entry":None,"margin":0.0,"liq":None} for a in UNIVERSE}}
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
        try:
            b,price=bull(closes(a))
            if b is None: continue
        except Exception as e:
            print(f"  {a} ERR {e}"); continue
        p=pf["pos"][a]; inpos=p["units"]>0
        if inpos and price<=p["liq"]:
            pf["realized"]-=p["margin"]; pf["liquidations"]+=1
            actions.append(f"💀 LIQUIDATED {a} @ ${price:,.4f}")
            p.update({"cash":0.0,"units":0.0,"entry":None,"margin":0.0,"liq":None}); val=0.0
        elif inpos and not b:
            pnl=p["units"]*(price-p["entry"])-p["units"]*price*FEE
            cash=max(0.0,p["margin"]+pnl); pf["realized"]+=pnl
            actions.append(f"🔴 SELL {a} @ ${price:,.4f} (P&L ${pnl:+,.0f})")
            p.update({"cash":cash,"units":0.0,"entry":None,"margin":0.0,"liq":None}); val=cash
        elif inpos:
            val=max(0.0,p["margin"]+p["units"]*(price-p["entry"]))
        elif b and p["cash"]>0:
            m=p["cash"]; units=m*LEVERAGE*(1-FEE)/price
            p.update({"units":units,"entry":price,"margin":m,"cash":0.0,"liq":price*(1-0.95/LEVERAGE)})
            pf["trades"]+=1; actions.append(f"🟢 BUY {a} @ ${price:,.4f} ({LEVERAGE:g}x)")
            val=m
        else: val=p["cash"]
        equity+=val
        short=a.replace("-USD","")
        rows.append(f"{'🟢' if p['units']>0 else '⚪️'} {short} {'LONG' if p['units']>0 else 'cash'}")
    ret=(equity/pf["start"]-1)*100
    pf["last_equity"]=round(equity,2); pf["last_ret"]=round(ret,2)
    pf["history"].append({"t":dt.datetime.utcnow().isoformat(timespec='minutes'),"equity":round(equity,2)})
    save_pf(pf)
    body = (("👻 Ghost daily update:\n"+"\n".join(actions)+"\n\n") if actions else "👻 Ghost daily — no new trades\n\n")
    body += "  ".join(rows) + f"\n\n💰 ${equity:,.2f} ({ret:+.2f}%) | realized ${pf['realized']:+,.2f} | {pf['liquidations']} liq"
    send(body)

if __name__ == "__main__":
    run()
