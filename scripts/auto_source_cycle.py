"""
Hourly safe source cycle.
The real fetcher should use the existing importer and enforce:
- robots.txt
- per-host rate limits
- timeouts/retries
- no auth/CAPTCHA bypass
- original source URL preservation
"""
from app.sources.auto_discovery import discover_sources

def plan_cycle():
    return {
        "sources": [s.__dict__ for s in discover_sources()],
        "interval_minutes": 60,
        "verification_days": 7,
        "safe_mode": True,
    }

if __name__ == "__main__":
    print(plan_cycle())
