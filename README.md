# TradingBot (Paper Trading)

Täglicher Paper-Trading-Bot für BTC und ETH. Er handelt **nur virtuelles Geld** (Start: 10.000 €).

- **Strategie:** Kauf, wenn der Tagesschlusskurs über dem 200-Tage-Durchschnitt liegt. Verkauf, wenn er darunter fällt oder der ATR-Stop (3 × ATR14, nachgezogen) erreicht wird.
- **Risiko:** höchstens 1 % des Kontos pro Trade, höchstens 50 % des Kontos pro Coin, Not-Aus bei −15 % vom Höchststand, Gebühr 0,26 % pro Order eingerechnet.
- **Daten:** öffentliche Tageskerzen von Kraken (kein Konto, kein API-Key).
- **Betrieb:** GitHub Actions, täglich 00:15 UTC (`.github/workflows/paper-bot.yml`). Manuell starten: Tab *Actions* → *Paper-Bot täglich* → *Run workflow*.

## Ergebnisse ansehen

- `data/equity.csv`: Kontostand pro Tag und Vergleich mit einfachem Halten
- `data/trades.csv`: alle Käufe und Verkäufe
- `data/state.json`: aktuelles Depot
- Zusammenfassung jedes Laufs: Tab *Actions* → Lauf anklicken

Einstellungen stehen in `config.json`. Test ohne Internet: `python tests/test_paper_bot.py`.

Hinweis: Ein Monat zeigt, ob der Bot zuverlässig läuft, aber nicht, ob die Strategie langfristig profitabel ist.
