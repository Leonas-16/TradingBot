"""Offline-Test mit künstlichen Kursen: Aufwärtstrend kauft, Absturz verkauft."""
import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent


def make_candles(closes):
    return [{"time": i, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
            for i, c in enumerate(closes)]


def test_buy_then_sell():
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(SRC / "bot", tmp / "bot")
    shutil.copy(SRC / "config.json", tmp / "config.json")
    sys.path.insert(0, str(tmp / "bot"))
    bot = importlib.import_module("paper_bot")
    importlib.reload(bot)

    up = [100 + i for i in range(260)]
    state = bot.run({"XBTEUR": make_candles(up)}, today="2026-01-01")
    assert "XBTEUR" in state["positions"]
    pos = state["positions"]["XBTEUR"]
    # Risiko pro Trade höchstens 1 % des Kontos
    assert (pos["entry"] - pos["stop"]) * pos["qty"] <= 10000 * 0.01 + 1e-6

    crash = up + [150]
    state = bot.run({"XBTEUR": make_candles(crash)}, today="2026-01-02")
    assert "XBTEUR" not in state["positions"]
    trades = (tmp / "data" / "trades.csv").read_text().splitlines()
    assert len(trades) == 3  # Kopfzeile, Kauf, Verkauf
    eq = (tmp / "data" / "equity.csv").read_text().splitlines()
    assert len(eq) == 3
    print("OK", json.dumps(state)[:200])


if __name__ == "__main__":
    test_buy_then_sell()
