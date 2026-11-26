"""Backtest: Varianten des Long/Cash-Bots mit weniger Trades.

Gleiche Daten, Kosten und Ausführung wie backtest_short.py (Signal am Schluss,
Ausführung am nächsten Eröffnungskurs, 0,31 % Kosten pro Order).
Parameter sind bewusst runde Standardwerte, nicht optimiert.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from backtest_short import FEE, START, fetch, stats  # noqa: E402

SMA_N, ATR_N, RISK = 200, 14, 0.01

VARIANTS = [
    # name, stop_mult, rearm, buffer, weekly, sizing
    ("A Bot wie jetzt (3 ATR, sofort wieder rein, 1 % Risiko)", 3, False, 0.0, False, "risk"),
    ("B Wie jetzt, aber voll investiert", 3, False, 0.0, False, "full"),
    ("C Kein sofortiger Wiedereinstieg nach Stop", 3, True, 0.0, False, "full"),
    ("D Breiterer Stop (5 ATR) + kein sofortiger Wiedereinstieg", 5, True, 0.0, False, "full"),
    ("E Ohne Stop, nur 200-Tage-Schnitt", None, False, 0.0, False, "full"),
    ("F Ohne Stop, Puffer ±3 % um den Schnitt", None, False, 0.03, False, "full"),
    ("G Ohne Stop, nur einmal pro Woche prüfen", None, False, 0.0, True, "full"),
    ("H Wie F, aber Größe nach Volatilität (Ziel 40 %/Jahr)", None, False, 0.03, False, "vol"),
]


def simulate(candles, i0, i1, stop_mult, rearm, buffer, weekly, sizing):
    cash, pos, stop, trades = START / 2, 0.0, 0.0, 0
    armed = True
    curve, orders = [], []
    closes = [c["c"] for c in candles]
    trs = [0.0] + [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
                   for p, c in zip(candles, candles[1:])]
    for i in range(i0, i1):
        c = candles[i]
        for od in orders:
            px = c["o"]
            if od[0] == "close" and pos:
                cash += pos * px * (1 - FEE); pos = 0.0; trades += 1
            elif od[0] == "open" and pos == 0:
                qty = min(od[1] / px, cash / (px * (1 + FEE)))
                if qty > 0:
                    cash -= qty * px * (1 + FEE); pos = qty; trades += 1
                    stop = px - od[2] if od[2] else 0.0
        orders = []
        if pos and stop_mult and c["l"] <= stop:
            px = min(stop, c["o"]); cash += pos * px * (1 - FEE); pos = 0.0; trades += 1
            armed = not rearm
        eq = cash + pos * c["c"]
        curve.append(eq)
        if i < SMA_N:
            continue
        sma = sum(closes[i - SMA_N + 1:i + 1]) / SMA_N
        atr = sum(trs[i - ATR_N + 1:i + 1]) / ATR_N
        px = c["c"]
        if px < sma:
            armed = True  # nach Stop erst wieder rein, wenn der Kurs einmal unter den Schnitt fiel
        is_check_day = (not weekly) or datetime.fromtimestamp(c["t"], timezone.utc).weekday() == 6
        if pos:
            if stop_mult:
                stop = max(stop, px - stop_mult * atr)
            if is_check_day and px < sma * (1 - buffer):
                orders.append(("close",))
        elif is_check_day and armed and px > sma * (1 + buffer):
            if sizing == "risk":
                dist = stop_mult * atr
                notional = min(eq * 2 * RISK / max(dist, px * 0.01) * px, eq)
            elif sizing == "vol":
                rets = [closes[k] / closes[k - 1] - 1 for k in range(i - 59, i + 1)]
                m = sum(rets) / len(rets)
                vol = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 365 ** 0.5
                notional = eq * min(1.0, 0.40 / max(vol, 1e-9))
            else:
                notional = eq
            orders.append(("open", notional, stop_mult * atr if stop_mult else 0.0))
    return curve, trades


def main():
    data = {p: fetch(p) for p in ("BTC-EUR", "ETH-EUR")}
    common = sorted(set(c["t"] for c in data["BTC-EUR"]) & set(c["t"] for c in data["ETH-EUR"]))
    for p in data:
        idx = {c["t"]: c for c in data[p]}
        data[p] = [idx[t] for t in common]
    n = len(common)
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    first = SMA_N + 1
    periods = [("Gesamt", first, n)]
    for y0, y1 in ((2018, 2020), (2021, 2023), (2024, 2026)):
        a = next(i for i, t in enumerate(common) if day(t) >= f"{y0}-01-01" and i >= first)
        b = next((i for i, t in enumerate(common) if day(t) > f"{y1}-12-31"), n)
        periods.append((f"{y0}-{y1}", a, b))
    lines = ["# Backtest: Bot-Varianten mit weniger Trades\n",
             f"Daten: Coinbase BTC-EUR + ETH-EUR bis {day(common[-1])}. Start 10.000 €, je 50 % pro Coin, 0,31 % Kosten pro Order.\n"]
    out = {}
    for pname, a, b in periods:
        lines.append(f"\n## {pname}: {day(common[a])} bis {day(common[b-1])}\n")
        lines.append("| Variante | Rendite gesamt | pro Jahr | max. Drawdown | Trades | Rendite/Drawdown |\n|---|---|---|---|---|---|")
        bh = [START / 2 * (data['BTC-EUR'][i]['c'] / data['BTC-EUR'][a]['c'] + data['ETH-EUR'][i]['c'] / data['ETH-EUR'][a]['c']) for i in range(a, b)]
        s = stats(bh, b - a)
        lines.append(f"| Halten BTC+ETH | {s['total']*100:+.0f} % | {s['cagr']*100:+.1f} % | {s['mdd']*100:.0f} % | 2 | {s['cagr']/abs(s['mdd']):.2f} |")
        out[pname] = {"Halten": s}
        for v in VARIANTS:
            curves, tr = [], 0
            for p in data:
                cv, t = simulate(data[p], a, b, *v[1:])
                curves.append(cv); tr += t
            tot = [x + y for x, y in zip(*curves)]
            s = stats(tot, b - a)
            out[pname][v[0]] = dict(s, trades=tr)
            ratio = s['cagr'] / abs(s['mdd']) if s['mdd'] else 0
            lines.append(f"| {v[0]} | {s['total']*100:+.0f} % | {s['cagr']*100:+.1f} % | {s['mdd']*100:.0f} % | {tr} | {ratio:.2f} |")
    text = "\n".join(lines) + "\n"
    print(text)
    os.makedirs("backtest/results", exist_ok=True)
    open("backtest/results/variants.md", "w").write(text)
    json.dump(out, open("backtest/results/variants.json", "w"), indent=2)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(text)


if __name__ == "__main__":
    main()
