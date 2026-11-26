"""Offline-Test mit künstlichen Kursen: Kauf, Stop-Verkauf, Sperre und Wiedereinstieg (Variante D)."""
import importlib
import shutil
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent


def make_candles(closes):
    return [{"time": i, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
            for i, c in enumerate(closes)]


def test_variante_d():
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
    # Variante D: voll investiert, max. 50 % des Kontos pro Coin
    assert 4900 < pos["qty"] * pos["entry"] <= 5000

    # Rücksetzer bis unter den Stop, Kurs bleibt aber über dem Schnitt -> Stop-Verkauf
    dip = up + [340]
    dip_c = make_candles(dip)
    dip_c[-1]["low"] = 300
    state = bot.run({"XBTEUR": dip_c}, today="2026-01-02")
    assert "XBTEUR" not in state["positions"] and state["blocked"].get("XBTEUR")

    # Am nächsten Tag wieder über dem Schnitt: kein sofortiger Wiedereinstieg
    state = bot.run({"XBTEUR": make_candles(dip + [345])}, today="2026-01-03")
    assert "XBTEUR" not in state["positions"]

    # Erst unter den Schnitt, dann wieder darüber -> Kauf erlaubt
    state = bot.run({"XBTEUR": make_candles(dip + [345, 200])}, today="2026-01-04")
    assert not state["blocked"].get("XBTEUR")
    state = bot.run({"XBTEUR": make_candles(dip + [345, 200, 400])}, today="2026-01-05")
    assert "XBTEUR" in state["positions"]
    print("OK Variante D")


if __name__ == "__main__":
    test_variante_d()
