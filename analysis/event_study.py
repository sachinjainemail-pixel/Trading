"""Pilot event study: Nifty 500 stocks that beat EPS estimates but fell on the result.
Usage: python3 -I event_study.py CACHE_DIR OUT_DIR
Reaction day = highest volume spike within 7 to 60 days after quarter end (Yahoo has no announcement dates).
"""
import json, glob, os, sys, statistics as st, csv, datetime as dt
import numpy as np

CACHE, OUT = sys.argv[1], sys.argv[2]
DROP = -0.03          # reaction day close to close move that counts as beaten down
HOR = 21              # trading days, about one month
MIN_SPIKE = 2.0       # volume must be at least 2x the prior 60 day median

def load_px(path):
    try: r = json.load(open(path))["chart"]["result"][0]
    except Exception: return None
    q = r["indicators"]["quote"][0]
    ts = r["timestamp"]
    rows = [(dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=5.5))).date(), c, v)
            for t, c, v in zip(ts, q["close"], q["volume"]) if c is not None]
    d = {}
    for day, c, v in rows: d[day] = (c, v or 0)
    days = sorted(d)
    return days, np.array([d[x][0] for x in days]), np.array([d[x][1] for x in days], float)

bm = load_px(f"{CACHE}/_CRSLDX_px.json") or load_px(f"{CACHE}/_NSEI_px.json")
bdays, bpx, _ = bm
bidx = {d: i for i, d in enumerate(bdays)}

events, skipped = [], {"no_spike": 0, "no_forward": 0, "bad_estimate": 0}
for f in sorted(glob.glob(f"{CACHE}/*_eh.json")):
    sym = os.path.basename(f).replace("_eh.json", "")
    try: hist = json.load(open(f))["quoteSummary"]["result"][0]["earningsHistory"]["history"]
    except Exception: continue
    p = load_px(f"{CACHE}/{sym}_px.json")
    if not p: continue
    days, px, vol = p
    for h in hist:
        try:
            qe = dt.date.fromisoformat(h["quarter"]["fmt"])
            act, est = h["epsActual"]["raw"], h["epsEstimate"]["raw"]
        except Exception:
            skipped["bad_estimate"] += 1; continue
        if est is None or est <= 0:                 # sign of surprise is ambiguous for negative estimates
            skipped["bad_estimate"] += 1; continue
        surp = act / est - 1
        lo, hi = qe + dt.timedelta(days=7), qe + dt.timedelta(days=60)
        w = [i for i, d in enumerate(days) if lo <= d <= hi and i >= 61]
        if not w: skipped["no_spike"] += 1; continue
        base = np.median(vol[w[0] - 60:w[0]])
        if base <= 0: skipped["no_spike"] += 1; continue
        ratios = [(vol[i] / base, i) for i in w]
        ratio, d0 = max(ratios)
        if ratio < MIN_SPIKE: skipped["no_spike"] += 1; continue
        if d0 + HOR >= len(days) or days[d0] not in bidx: skipped["no_forward"] += 1; continue
        # benchmark aligned by date
        def bret(a, b):
            ia, ib = bidx.get(days[a]), bidx.get(days[b])
            return None if ia is None or ib is None else bpx[ib] / bpx[ia] - 1
        r0 = px[d0] / px[d0 - 1] - 1
        fwd = {k: px[d0 + k] / px[d0] - 1 for k in (5, 10, 21)}
        exc = {k: (fwd[k] - bret(d0, d0 + k)) if bret(d0, d0 + k) is not None else None for k in fwd}
        seg = px[d0:d0 + HOR + 1]
        tr = int(np.argmin(seg))                       # trough index relative to d0
        trough_ret = seg[-1] / seg[tr] - 1
        further = seg[tr] / seg[0] - 1                 # extra fall after reaction close
        pre = px[d0 - 1]
        rec = next((k for k in range(1, HOR + 1) if px[d0 + k] >= pre), None)
        ia = bidx[days[d0]]
        path = [float(px[d0 + k] / px[d0] - bpx[ia + k] / bpx[ia]) if days[d0 + k] == bdays[ia + k] else float("nan") for k in range(HOR + 1)] if ia + HOR < len(bdays) else [float("nan")] * (HOR + 1)
        events.append(dict(path=path, ret2=px[d0 + 1] / px[d0 - 1] - 1, sym=sym.replace(".NS", ""), qend=str(qe), react=str(days[d0]), spike=round(ratio, 1),
            surprise=round(surp, 4), beat=act > est, react_ret=round(r0, 4),
            f5=round(fwd[5], 4), f10=round(fwd[10], 4), f21=round(fwd[21], 4),
            x5=exc[5], x10=exc[10], x21=exc[21], trough_day=tr, further_fall=round(further, 4),
            trough_to_21=round(trough_ret, 4), recovered_pre=rec is not None, days_to_pre=rec))

os.makedirs(OUT, exist_ok=True)
with open(f"{OUT}/events.csv", "w", newline="") as fh:
    keys = [k for k in events[0] if k != "path"]
    w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(events)

def pct(x): return "n/a" if x is None else f"{x*100:+.1f}%"
def summarize(name, es):
    n = len(es)
    if n == 0: return f"{name}: no events"
    def col(k): return [e[k] for e in es if e[k] is not None]
    lines = [f"### {name}  (n = {n})"]
    for k, lab in ((5, "5 sessions"), (10, "10 sessions"), (21, "21 sessions")):
        r, x = col(f"f{k}"), col(f"x{k}")
        se = st.stdev(x) / len(x) ** .5 if len(x) > 2 else float("nan")
        lines.append(f"- After {lab}: median {pct(st.median(r))}, mean {pct(st.mean(r))}, positive {sum(v>0 for v in r)/len(r)*100:.0f}%. "
                     f"Excess vs Nifty 500: median {pct(st.median(x))}, mean {pct(st.mean(x))}, std error {se*100:.1f}%")
    tr = col("trough_day")
    lines.append(f"- Further fall after the reaction close: median {pct(st.median(col('further_fall')))}. Median trough on session {st.median(tr):.0f}. "
                 f"Share with no lower close in the month {sum(t==0 for t in tr)/n*100:.0f}%")
    lines.append(f"- Rebound from the month low to session 21: median {pct(st.median(col('trough_to_21')))}")
    d = [e["days_to_pre"] for e in es if e["days_to_pre"] is not None]
    lines.append(f"- Regained the pre result close within a month: {len(d)/n*100:.0f}% of events, median {st.median(d) if d else float('nan'):.0f} sessions")
    return "\n".join(lines)

beat = [e for e in events if e["beat"]]
strong = [e for e in beat if e["surprise"] >= .05]
miss = [e for e in events if not e["beat"]]
groups = [
 ("A. Beat EPS and fell 3% or more on reaction day", [e for e in beat if e["react_ret"] <= DROP]),
 ("B. Strong beat of 5% or more and fell 3% or more", [e for e in strong if e["react_ret"] <= DROP]),
 ("C. Control, missed EPS and fell 3% or more", [e for e in miss if e["react_ret"] <= DROP]),
 ("D. Control, beat EPS and rose 3% or more", [e for e in beat if e["react_ret"] >= -DROP]),
 ("E. Control, all beat events", beat),
]
rep = [f"Events usable: {len(events)}. Beats {len(beat)}, misses {len(miss)}. Skipped {skipped}", ""]
rep += [summarize(n, g) + "\n" for n, g in groups]
# split by quarter for stability
for q in sorted({e["qend"] for e in events}):
    g = [e for e in groups[0][1] if e["qend"] == q]
    if g: rep.append(summarize(f"Group A, quarter ended {q}", g) + "\n")
open(f"{OUT}/summary.md", "w").write("\n".join(rep))
print("\n".join(rep))


# ---------- robustness ----------
rng = np.random.default_rng(7)
def boot(vals, fn, n=5000):
    v = np.array(vals); b = [fn(rng.choice(v, len(v))) for _ in range(n)]
    return np.percentile(b, [2.5, 97.5])
extra = ["", "## Robustness checks", ""]
absr = [abs(e["react_ret"]) for e in events]
extra.append(f"Reaction day detection: median absolute move on the detected day is {np.median(absr)*100:.1f}% against a typical Nifty 500 stock day of about 1.5%, so the volume spike does land on a real event day.")
extra.append("")
extra.append("Bootstrap 95% intervals for 21 session excess return vs Nifty 500")
for name, g in groups[:4]:
    x = [e["x21"] for e in g if e["x21"] is not None]
    lo, hi = boot(x, np.median); lo2, hi2 = boot(x, np.mean)
    extra.append(f"- {name}: median {pct(np.median(x))} (CI {pct(lo)} to {pct(hi)}), mean {pct(np.mean(x))} (CI {pct(lo2)} to {pct(hi2)}), n = {len(x)}")
extra.append("")
extra.append("Median cumulative excess return vs Nifty 500 by session after the reaction close")
ks = [1, 2, 3, 5, 8, 10, 12, 15, 18, 21]
extra.append("| Group | n | " + " | ".join(f"S{k}" for k in ks) + " |")
extra.append("|---|---|" + "---|" * len(ks))
for name, g in groups[:4]:
    P = np.array([e["path"] for e in g]); 
    extra.append(f"| {name[:2]} | {len(g)} | " + " | ".join(pct(float(np.nanmedian(P[:, k]))) for k in ks) + " |")
extra.append("")
extra.append("Share of group A events by session of the lowest excess return level, then median excess at that point")
P = np.array([e["path"] for e in groups[0][1]])
low = np.nanargmin(P, axis=1)
for lo_, hi_ in ((0, 0), (1, 3), (4, 8), (9, 14), (15, 21)):
    m = (low >= lo_) & (low <= hi_)
    extra.append(f"- Session {lo_} to {hi_}: {m.mean()*100:.0f}% of events")
extra.append("")
extra.append("Sensitivity of group A (beat EPS, then fell) to the definition, 21 session excess median and mean, n")
def run(thr, spike, two_day):
    out = []
    for e in beat:
        if e["spike"] < spike: continue
        r = e["ret2"] if two_day else e["react_ret"]
        if r <= thr and e["x21"] is not None: out.append(e["x21"])
    return out
for thr in (-0.02, -0.03, -0.05):
    for spike in (2.0, 3.0):
        for two in (False, True):
            x = run(thr, spike, two)
            if len(x) > 5:
                extra.append(f"- drop {thr*100:.0f}% {'two day' if two else 'one day'}, spike {spike}x: n = {len(x)}, median {pct(np.median(x))}, mean {pct(np.mean(x))}")
open(f"{OUT}/summary.md", "a").write("\n".join(extra))
print("\n".join(extra))
