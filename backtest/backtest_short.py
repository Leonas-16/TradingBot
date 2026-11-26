"""Backtest: Long/Cash (wie der Paper-Bot) gegen Long/Short.

Regeln wie im Bot: 200-Tage-Durchschnitt, ATR(14)-Stop mit 3x Abstand, nachgezogen,
Risiko 1 % des Kontos pro Trade, max. 50 % des Kontos pro Coin.
Signal am Tagesschluss, Ausführung am nächsten Tag zum Eröffnungskurs.
Kosten: 0,26 % Gebühr + 0,05 % Slippage pro Order. Shorts zusätzlich mit
Finanzierungskosten in drei Szenarien.

Daten: Coinbase-Tageskerzen BTC-EUR und ETH-EUR (öffentlich, ohne Key).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

FEE = 0.0026 + 0.0005
SMA_N, ATR_N, STOP_MULT = 200, 14, 3.0
RISK, MAX_SHARE = 0.01, 0.5
START = 10_000.0
SCENARIOS = {  # jährliche Kosten fürs Shorten
    "Short, 0 % Kosten p.a. (optimistisch)": 0.0,
    "Short, 10 % Kosten p.a. (typ. Funding)": 0.10,
    "Short, 44 % Kosten p.a. (Margin-Rollover 0,02 %/4 h)": 0.44,
}


def fetch(product: str) -> list[dict]:
    out = {}
    end = int(time.time())
    while True:
        start = end - 300 * 86400
        url = (f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
               f"&start={datetime.fromtimestamp(start, timezone.utc).isoformat()}"
               f"&end={datetime.fromtimestamp(end, timezone.utc).isoformat()}")
        req = urllib.request.Request(url, headers={"User-Agent": "backtest"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    rows = json.load(r)
                break
            except Exception:
                time.sleep(2 + attempt * 2)
        else:
            raise RuntimeError("Coinbase nicht erreichbar")
        if not rows:
            break
        for t, low, high, op, cl, _v in rows:
            out[t] = {"t": t, "o": op, "h": high, "l": low, "c": cl}
        end = start
        time.sleep(0.4)
    candles = sorted(out.values(), key=lambda x: x["t"])
    return candles[:-1]  # laufender Tag raus


def simulate(candles, allow_short, short_cost, i0, i1, full=False):
    """Saubere Version mit Long/Short-Wechsel am selben Eröffnungskurs."""
    cash = START / 2
    pos = 0.0
    stop = 0.0
    trades = 0
    curve = []
    closes = [c["c"] for c in candles]
    trs = [0.0] + [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
                   for p, c in zip(candles, candles[1:])]
    orders = []  # Liste von ("close",) / ("open", side, risk_eur, stop_dist)
    daily_cost = (1 + short_cost) ** (1 / 365) - 1
    for i in range(i0, i1):
        c = candles[i]
        for od in orders:
            px = c["o"]
            if od[0] == "close" and pos:
                cash += pos * px - abs(pos) * px * FEE
                pos = 0.0; trades += 1
            elif od[0] == "open" and pos == 0:
                _, side, eq_ref, dist = od
                qty = eq_ref * MAX_SHARE / px if full else min(eq_ref * RISK / max(dist, px * 0.01), eq_ref * MAX_SHARE / px)
                pos = side * qty
                cash -= pos * px + qty * px * FEE
                stop = px - side * dist
                trades += 1
        orders = []
        if pos > 0 and c["l"] <= stop:
            px = min(stop, c["o"]); cash += pos * px - pos * px * FEE; pos = 0.0; trades += 1
        elif pos < 0 and c["h"] >= stop:
            px = max(stop, c["o"]); cash += pos * px + pos * px * FEE; pos = 0.0; trades += 1
        if pos < 0:
            cash -= abs(pos) * c["c"] * daily_cost
        eq = cash + pos * c["c"]
        curve.append(max(eq, 0.0))
        if eq <= 0:
            break
        if i < SMA_N:
            continue
        sma = sum(closes[i - SMA_N + 1:i + 1]) / SMA_N
        atr = sum(trs[i - ATR_N + 1:i + 1]) / ATR_N
        px = c["c"]
        want = 1 if px > sma else (-1 if allow_short else 0)
        cur = 1 if pos > 0 else (-1 if pos < 0 else 0)
        if cur == 1:
            stop = max(stop, px - STOP_MULT * atr)
        elif cur == -1:
            stop = min(stop, px + STOP_MULT * atr)
        if cur != 0 and want != cur:
            orders.append(("close",))
            cur = 0
        if cur == 0 and want != 0:
            # eq*2 ≈ Gesamtkonto: Risiko 1 % davon, Position max. 50 % (= Teilkonto)
            orders.append(("open", want, eq * 2, STOP_MULT * atr))
    return {"curve": curve, "trades": trades}


def stats(curve: list[float], days: int) -> dict:
    total = curve[-1] / curve[0] - 1 if curve[0] else -1
    years = days / 365
    cagr = (curve[-1] / curve[0]) ** (1 / years) - 1 if curve[-1] > 0 else -1
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1 if peak else 0)
    return {"total": total, "cagr": cagr, "mdd": mdd}


def main():
    data = {p: fetch(p) for p in ("BTC-EUR", "ETH-EUR")}
    # gemeinsame Tage
    common = sorted(set(c["t"] for c in data["BTC-EUR"]) & set(c["t"] for c in data["ETH-EUR"]))
    for p in data:
        idx = {c["t"]: c for c in data[p]}
        data[p] = [idx[t] for t in common]
    n = len(common)
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    first_trade = SMA_N + 1
    periods = [("Gesamt", first_trade, n)]
    for y0, y1 in ((2018, 2020), (2021, 2023), (2024, 2026)):
        a = next((i for i, t in enumerate(common) if day(t) >= f"{y0}-01-01" and i >= first_trade), None)
        b = next((i for i, t in enumerate(common) if day(t) > f"{y1}-12-31"), n)
        if a is not None and b - a > 200:
            periods.append((f"{y0}-{min(y1, int(day(common[-1])[:4]))}", a, b))

    base = [("Long/Cash", False, 0.0)] + [(k, True, v) for k, v in SCENARIOS.items()]
    variants = [(f"{n} · Bot-Größe (1 % Risiko)", sh, c, False) for n, sh, c in base] + \
               [(f"{n} · voll investiert (je 50 %)", sh, c, True) for n, sh, c in base]
    lines = [f"# Backtest Long/Cash vs. Long/Short\n",
             f"Daten: Coinbase BTC-EUR + ETH-EUR, {day(common[0])} bis {day(common[-1])} ({n} Tage). "
             f"Handel ab Tag {first_trade} (200-Tage-Schnitt braucht Vorlauf). Start 10.000 €, je 50 % pro Coin.\n"]
    result = {}
    for pname, a, b in periods:
        lines.append(f"\n## {pname}: {day(common[a])} bis {day(common[b-1])}\n")
        lines.append("| Variante | Rendite gesamt | pro Jahr | max. Drawdown | Trades |\n|---|---|---|---|---|")
        bh = [START / 2 * (data['BTC-EUR'][i]['c'] / data['BTC-EUR'][a]['c'] + data['ETH-EUR'][i]['c'] / data['ETH-EUR'][a]['c']) for i in range(a, b)]
        s = stats(bh, b - a)
        lines.append(f"| Halten BTC+ETH | {s['total']*100:+.0f} % | {s['cagr']*100:+.1f} % | {s['mdd']*100:.0f} % | 2 |")
        result[pname] = {"hold": s}
        for vname, short, cost, full in variants:
            curves, tr = [], 0
            for p in data:
                r = simulate(data[p], short, cost, a, b, full)
                curves.append(r["curve"] + [r["curve"][-1]] * (b - a - len(r["curve"])))
                tr += r["trades"]
            tot = [x + y for x, y in zip(*curves)]
            s = stats(tot, b - a)
            result[pname][vname] = dict(s, trades=tr)
            lines.append(f"| {vname} | {s['total']*100:+.0f} % | {s['cagr']*100:+.1f} % | {s['mdd']*100:.0f} % | {tr} |")
    text = "\n".join(lines) + "\n"
    print(text)
    os.makedirs("backtest/results", exist_ok=True)
    open("backtest/results/short_vs_long.md", "w").write(text)
    json.dump(result, open("backtest/results/short_vs_long.json", "w"), indent=2)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(text)


if __name__ == "__main__":
    main()
