# TradingBot (Paper Trading)

Täglicher Paper-Trading-Bot für BTC und ETH. Er handelt **nur virtuelles Geld** (Start: 10.000 €).

- **Strategie (Variante D, seit 26.11.2026):** Kauf, wenn der Tagesschlusskurs über dem 200-Tage-Durchschnitt liegt. Verkauf, wenn er darunter fällt oder der ATR-Stop (5 × ATR14, nachgezogen) erreicht wird. Nach einem Stop erst wieder Kauf, wenn der Kurs einmal unter den Schnitt gefallen ist.
- **Größe und Risiko:** je Coin voll investiert mit höchstens 50 % des Kontos, Not-Aus bei −45 % vom Höchststand (passend zum Backtest-Rückschlag von −39 %), Gebühr 0,26 % pro Order eingerechnet.
- **Backtest 2017–2026** (Branch `backtest-short`): +413 %, max. Rückschlag −39 %, 134 Trades. Halten: +224 %, −89 %.
- **Daten:** öffentliche Tageskerzen von Kraken (kein Konto, kein API-Key).
- **Betrieb:** GitHub Actions, täglich 00:15 UTC (`.github/workflows/paper-bot.yml`). Manuell starten: Tab *Actions* → *Paper-Bot täglich* → *Run workflow*.

## Ergebnisse ansehen

- `data/equity.csv`: Kontostand pro Tag und Vergleich mit einfachem Halten
- `data/trades.csv`: alle Käufe und Verkäufe
- `data/state.json`: aktuelles Depot
- Zusammenfassung jedes Laufs: Tab *Actions* → Lauf anklicken

Einstellungen stehen in `config.json`. Test ohne Internet: `python tests/test_paper_bot.py`.

Hinweis: Ein Monat zeigt, ob der Bot zuverlässig läuft, aber nicht, ob die Strategie langfristig profitabel ist.
