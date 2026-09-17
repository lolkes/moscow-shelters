# FINAL PROJECT RUNBOOK

## Local
1. Create venv.
2. Install `requirements.txt`.
3. Run `python scripts/seed_shelters.py`.
4. Start the app with the existing README command.
5. Open `/`, `/admin.html`, `/api/health`, `/api/metrics`, `/api/sources/health`.

## Automatic cycle
- Run hourly.
- Discover public source/catalog pages.
- Respect robots.txt, rate limits and timeouts.
- Import only explicitly published fields.
- Preserve source_url.
- Extract same-origin images only.
- Validate image responses before storing when the importer supports HTTP validation.
- Deduplicate conservatively.
- Do not archive on a temporary source outage.
- Verify shelters every 7 days.
- Keep import/history records for auditability.

## Before production
- Set DATABASE_URL to PostgreSQL.
- Put the app behind HTTPS/reverse proxy.
- Configure a persistent scheduler (cron/systemd/Celery/worker).
- Add backups and log rotation.
- Review robots/terms for every newly discovered source.
