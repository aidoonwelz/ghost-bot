# 👻 Ghost — daily EMA 9×21 trend bot (paper)

Runs once a day on **GitHub Actions** (free), trades a $10k **paper** portfolio across
crypto + stocks on an EMA 9×21 crossover, and texts a daily summary via Telegram.

- **Strategy:** long when EMA9 > EMA21, flat otherwise. 3× leverage w/ liquidation.
- **State:** `portfolio.json` (updated + committed each run).
- **Secrets:** `TELEGRAM_TOKEN`, `TELEGRAM_CHAT` (repo Settings → Secrets).
- **Schedule:** `.github/workflows/daily.yml` (13:05 UTC daily). Run manually via the
  Actions tab → "Ghost daily" → "Run workflow".

Paper money only. Not financial advice.
