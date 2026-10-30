# Prosti zdravniki

Daily static pages per Slovenian municipality listing doctors that accept new patients, plus the Telegram alert bot [@ZdravnikAlarmBot](https://t.me/ZdravnikAlarmBot).

Data: ZZZS via [sledilnik/zdravniki-data](https://github.com/sledilnik/zdravniki-data) (CC BY 4.0).

- `gen_site.py` builds `site/` (run daily by GitHub Actions, deployed to Pages).
- `zb.py` is the bot (needs `TG_TOKEN` in `.env`, never committed).
