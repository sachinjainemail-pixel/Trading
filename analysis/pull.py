import csv, json, os, sys, time, threading, urllib.request, urllib.error, http.cookiejar
from concurrent.futures import ThreadPoolExecutor
D = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(D, "cache")
UA = {"User-Agent": "Mozilla/5.0"}
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(url, tries=6):
    for i in range(tries):
        try:
            r = op.open(urllib.request.Request(url, headers=UA), timeout=30)
            return r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404 and "fc.yahoo" in url: return ""
            if e.code in (429, 999, 502, 503): time.sleep(2 * (i + 1)); continue
            if e.code == 404: return None
            time.sleep(1)
        except Exception:
            time.sleep(1 + i)
    return None
try: get("https://fc.yahoo.com")
except Exception: pass
crumb = get("https://query1.finance.yahoo.com/v1/test/getcrumb")
print("crumb", crumb, flush=True)
syms = [r["Symbol"] for r in csv.DictReader(open(os.path.join(D, "nifty500.csv")))]
jobs = [("^CRSLDX", "px"), ("^NSEI", "px")] + [(s + ".NS", k) for s in syms for k in ("px", "eh")]
def do(j):
    t, k = j
    f = os.path.join(C, f"{t.replace('^','_')}_{k}.json")
    if os.path.exists(f) and os.path.getsize(f) > 20: return
    if k == "px":
        u = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=2y&interval=1d"
    else:
        u = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{t}?modules=earningsHistory&crumb={crumb}"
    s = get(u)
    open(f, "w").write(s if s else "")
with ThreadPoolExecutor(4) as ex:
    for n, _ in enumerate(ex.map(do, jobs)):
        if n % 100 == 0: print(n, len(jobs), flush=True)
print("done", flush=True)
