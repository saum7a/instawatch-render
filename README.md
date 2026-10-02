# InstaWatch Bot V1

A Discord-based Instagram public-availability monitoring service.

## Important
This V1 does NOT use an Instagram username/password, session cookie, CAPTCHA solving, proxy rotation, or any bypass of access controls.

The monitor classifies observable public-page responses as:
- ACTIVE
- UNAVAILABLE
- UNKNOWN

A business event is generated only for:
- ACTIVE -> UNAVAILABLE: unavailable/ban-like event
- UNAVAILABLE -> ACTIVE: restored/unban-like event

UNKNOWN never triggers a ban/unban alert.

## Features in V1
- Discord slash commands
- Unlimited monitored accounts per plan
- Per-account service price in USD
- 15-second configurable scheduler
- Multi-client isolation by Discord user
- Active/unavailable/unknown state
- Transition history
- Daily/monthly revenue reports
- Manual subscriptions
- Subscription expiry checks
- Restoration screenshot attempt using Playwright
- Admin-only subscription controls
- SQLite for easy local development

## Install

Python 3.10+ recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
```

Fill `.env` with your Discord bot token and your Discord user ID.

Then:

```powershell
python main.py
```

## Commands

Client:
- `/monitor username price`
- `/unmonitor username`
- `/status username`
- `/list`
- `/history username`
- `/report period`

Admin:
- `/subscription_add user days plan`
- `/subscription_extend user days`
- `/subscription_status user`

## 15-second monitoring
`CHECK_INTERVAL_SECONDS=15` is the default.

Important: 15 seconds is a requested product setting, not a guarantee that Instagram will answer every check. The worker uses timeouts and an UNKNOWN state for ambiguous responses. At scale, checking every account every 15 seconds can produce very high traffic and may trigger Instagram rate limits or access restrictions. The architecture is therefore designed so the interval can later be changed without rewriting the bot.

## Screenshot behavior
Screenshots are attempted only on a confirmed UNAVAILABLE -> ACTIVE transition. They are not used to bypass login/challenges. If the public page cannot be safely rendered, the bot reports that screenshot verification was unavailable.

## Production roadmap
Move from SQLite to PostgreSQL, add Redis/queue workers, object storage for screenshots, metrics/health checks, and a web admin dashboard before large-scale commercial deployment.
