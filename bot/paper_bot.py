"""Täglicher Paper-Trading-Bot: Trendfilter (200-Tage-Durchschnitt) mit ATR-Stop (Variante D).

Nach einem Stop wird erst wieder gekauft, wenn der Kurs einmal unter den
200-Tage-Schnitt gefallen ist (kein sofortiger Wiedereinstieg).

Handelt nur virtuelles Geld. Holt öffentliche Tageskerzen von Kraken
(kein Konto, kein API-Key) und speichert Depot, Trades und Kontoverlauf
im Ordner data/.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = json.loads((ROOT / "config.json").read_text())

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440"


# ---------- Marktdaten ----------

def fetch_daily_candles(pair: str) -> list[dict]:
    """Abgeschlossene Tageskerzen von Kraken (älteste zuerst)."""
    req = urllib.request.Request(KRAKEN_URL.format(pair=pair), headers={"User-Agent": "paper-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("error"):
        raise RuntimeError(f"Kraken-Fehler für {pair}: {payload['error']}")
    rows = next(v for k, v in payload["result"].items() if k != "last")
    candles = [
        {"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
         "low": float(r[3]), "close": float(r[4])}
        for r in rows
    ]
    return candles[:-1]  # letzte Kerze ist noch nicht abgeschlossen


# ---------- Indikatoren ----------

def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def atr(candles: list[dict], n: int) -> float | None:
    if len(candles) < n + 1:
        return None
    trs = []
    for prev, cur in zip(candles[-n - 1:-1], candles[-n:]):
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    return sum(trs) / n


# ---------- Depot ----------

def load_state() -> dict:
    path = DATA / "state.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"cash": CONFIG["start_capital_eur"], "positions": {},
            "peak_equity": CONFIG["start_capital_eur"], "halted": False,
            "benchmark_start": {}, "blocked": {}}


def save_state(state: dict) -> None:
    (DATA / "state.json").write_text(json.dumps(state, indent=2) + "\n")


def append_csv(name: str, header: list[str], row: list) -> None:
    path = DATA / name
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def equity(state: dict, prices: dict[str, float]) -> float:
    return state["cash"] + sum(p["qty"] * prices[s] for s, p in state["positions"].items())


# ---------- Strategie ----------

def decide(candles: list[dict], position: dict | None) -> tuple[str, dict]:
    """Gibt ("buy" | "sell" | "hold", Infos) zurück."""
    closes = [c["close"] for c in candles]
    price = closes[-1]
    trend = sma(closes, CONFIG["sma_days"])
    vol = atr(candles, CONFIG["atr_days"])
    info = {"price": price, "sma": trend, "atr": vol}
    if trend is None or vol is None:
        return "hold", info
    if position:
        new_stop = max(position["stop"], price - CONFIG["atr_stop_mult"] * vol)
        info["stop"] = new_stop
        if candles[-1]["low"] <= position["stop"]:
            info["reason"] = "stop"
            return "sell", info
        if price < trend:
            info["reason"] = "trend"
            return "sell", info
        return "hold", info
    if price > trend:
        info["stop"] = price - CONFIG["atr_stop_mult"] * vol
        return "buy", info
    return "hold", info


def position_size(eq: float, price: float, stop: float, cash: float) -> float:
    """Voll investiert (max_position_share pro Coin) oder risikobasiert."""
    if CONFIG.get("sizing") == "full":
        return max(0.0, min(cash, eq * CONFIG["max_position_share"]) / (price * (1 + CONFIG["fee_rate"])))
    risk_eur = eq * CONFIG["risk_per_trade"]
    per_unit = max(price - stop, price * 0.01)
    qty = risk_eur / per_unit
    max_qty = min(cash, eq * CONFIG["max_position_share"]) / (price * (1 + CONFIG["fee_rate"]))
    return max(0.0, min(qty, max_qty))


def run(market: dict[str, list[dict]] | None = None, today: str | None = None) -> dict:
    DATA.mkdir(exist_ok=True)
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = load_state()
    market = market or {s: fetch_daily_candles(s) for s in CONFIG["pairs"]}
    prices = {s: c[-1]["close"] for s, c in market.items()}
    for s, p in prices.items():
        state["benchmark_start"].setdefault(s, p)
    state.setdefault("blocked", {})

    fee = CONFIG["fee_rate"]
    log = []
    eq = equity(state, prices)

    # Not-Aus: maximaler Rückschlag vom Höchststand
    if eq < state["peak_equity"] * (1 - CONFIG["max_drawdown"]):
        state["halted"] = True

    for sym, candles in market.items():
        pos = state["positions"].get(sym)
        action, info = decide(candles, pos)
        price = info["price"]
        if info["sma"] is not None and price < info["sma"]:
            state["blocked"].pop(sym, None)  # Kurs fiel unter den Schnitt: Wiedereinstieg wieder erlaubt
        if action == "buy" and state["blocked"].get(sym):
            action = "hold"
            log.append(f"{sym}: nach Stop gesperrt, warte auf Rückfall unter den Schnitt")
        if action == "sell" and pos:
            proceeds = pos["qty"] * price * (1 - fee)
            state["cash"] += proceeds
            pnl = proceeds - pos["cost"]
            del state["positions"][sym]
            if info.get("reason") == "stop" and CONFIG.get("rearm_after_stop"):
                state["blocked"][sym] = True
            append_csv("trades.csv", ["date", "pair", "side", "qty", "price", "eur", "pnl_eur"],
                       [today, sym, "sell", f"{pos['qty']:.8f}", f"{price:.2f}", f"{proceeds:.2f}", f"{pnl:.2f}"])
            log.append(f"VERKAUF {sym} zu {price:.2f} €, Ergebnis {pnl:+.2f} €")
        elif action == "buy" and not state["halted"]:
            qty = position_size(eq, price, info["stop"], state["cash"])
            cost = qty * price * (1 + fee)
            if qty > 0 and cost >= 10:
                state["cash"] -= cost
                state["positions"][sym] = {"qty": qty, "entry": price, "stop": info["stop"], "cost": cost}
                append_csv("trades.csv", ["date", "pair", "side", "qty", "price", "eur", "pnl_eur"],
                           [today, sym, "buy", f"{qty:.8f}", f"{price:.2f}", f"{cost:.2f}", ""])
                log.append(f"KAUF {sym}: {qty:.6f} zu {price:.2f} €, Stop {info['stop']:.2f} €")
        elif action == "hold" and pos and "stop" in info:
            pos["stop"] = info["stop"]
        trend = f"{info['sma']:.2f}" if info["sma"] else "zu wenig Daten"
        log.append(f"{sym}: Kurs {price:.2f} €, 200-Tage-Schnitt {trend}, Aktion {action}")

    eq = equity(state, prices)
    state["peak_equity"] = max(state["peak_equity"], eq)
    bench = sum(prices[s] / state["benchmark_start"][s] for s in prices) / len(prices)
    bench_eq = CONFIG["start_capital_eur"] * bench
    append_csv("equity.csv", ["date", "equity_eur", "cash_eur", "benchmark_hold_eur"],
               [today, f"{eq:.2f}", f"{state['cash']:.2f}", f"{bench_eq:.2f}"])
    save_state(state)

    summary = (
        f"## Paper-Bot {today}\n\n"
        f"- Kontostand: **{eq:.2f} €** (Start {CONFIG['start_capital_eur']:.2f} €, "
        f"{(eq / CONFIG['start_capital_eur'] - 1) * 100:+.2f} %)\n"
        f"- Vergleich Halten von {', '.join(prices)}: {bench_eq:.2f} €\n"
        f"- Not-Aus aktiv: {'ja' if state['halted'] else 'nein'}\n\n"
        + "\n".join(f"- {line}" for line in log) + "\n"
    )
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)
    return state


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # Fehler sichtbar machen, Lauf als fehlgeschlagen markieren
        print(f"Fehler: {exc}", file=sys.stderr)
        sys.exit(1)
