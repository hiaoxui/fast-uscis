# fast-uscis

Small Python CLI for logging into `myUSCIS` and fetching case status events for all receipt numbers across every configured account.

## What It Does

The tool:

1. Loads account credentials from `config.toml` in the selected data directory.
2. Logs into every configured account with its TOTP secret.
3. Uses a real Firefox browser session through Playwright.
4. Completes the `myaccount.uscis.gov` to `my.uscis.gov` handoff.
5. Fetches every configured receipt from `/account/case-service/api/cases/<receipt_number>`.
6. Caches each case's latest `updatedAt` value in `case-cache.json`.
7. Prints full events on first observation, changed cases on later runs, or an unchanged summary.

## Environment Setup

This repo assumes Python 3.12+ and a local virtual environment at `.venv`.

Create the environment:

```bash
python -m venv .venv
```

Install Python dependencies:

```bash
.venv/bin/pip install -r requirements.txt
```

Install the Playwright browser runtime:

```bash
.venv/bin/python -m playwright install firefox
```

## Configuration

Create a `config.toml` in the data directory. The current directory is used by default.

Example:

```toml
[accounts]

[accounts.example]
email = "user@example.com"
password = "your-password"
totp_secret = "BASE32_TOTP_SECRET"

[accounts.example.receipts]
I-485 = "IOE1234567890"
I-765 = "IOE1234567891"
I-131 = "IOE1234567892"

[telegram]
api = "123456789:your-bot-token"
update_chat_id = "123456789"
no_update_chat_id = "987654321"
```

Notes:

- Each account must define `email`, `password`, and `totp_secret`.
- Each account must define at least one receipt under `receipts`.
- Every run checks every account and receipt configured in `config.toml`.
- First-run results, case updates, and failures are sent to `update_chat_id`.
- The `all cases are not updated` summary is sent only to `no_update_chat_id`.
- Send the bot a message first, then obtain your chat ID from the bot's `getUpdates` response.
- Do not commit `config.toml`.

## Usage

Show help:

```bash
.venv/bin/python -m fusi --help
```

Fetch all configured receipts across all accounts:

```bash
.venv/bin/python -m fusi
```

Use another directory for both `config.toml` and `case-cache.json`:

```bash
.venv/bin/python -m fusi /var/lib/fusi
```

Run with a visible browser:

```bash
.venv/bin/python -m fusi --headed
```

## Docker

Keep the runtime configuration and cache together under the repository's ignored `data/` directory:

```bash
mkdir -p data
cp config.toml data/config.toml
chmod 700 data
chmod 600 data/config.toml
docker compose build
docker compose run --rm fusi
```

The container mounts `./data` at `/data`. It reads `/data/config.toml`, atomically maintains `/data/case-cache.json`, and records failed runs in `/data/failure-log.jsonl`. The directory is excluded from both Git and the Docker build context because it contains credentials.

### Crontab

Open the current user's crontab with `crontab -e`, then add this entry to run every six hours:

```cron
0 */6 * * * cd /path/to/fast-uscis && /usr/sbin/flock -n data/fast-uscis.lock /usr/sbin/docker compose run --rm fusi >> data/cron.log 2>&1
```

The lock prevents overlapping checks if one run takes longer than expected. Build the image manually with `docker compose build` after pulling code or dependency changes; scheduled runs reuse that image.

### Failure Guard

Failed runs are appended to `data/failure-log.jsonl` with a UTC timestamp and error message. When Telegram configuration was loaded successfully, the failure is also sent to the configured chat.

After two failures occur within any 24-hour period, future runs stop before opening a browser or attempting a USCIS login. This block remains in place until the failure log is manually cleared, even after 24 hours have passed. Blocked cron runs print an error to `data/cron.log` but do not append another failure or send repeated Telegram alerts.

Inspect and clear the guard after resolving the underlying problem:

```bash
cat data/failure-log.jsonl
rm data/failure-log.jsonl
```

The next scheduled or manual run can then attempt USCIS again.

## AWS WAF / Captcha Note

USCIS currently protects the sign-in flow with AWS WAF. In some sessions, the sign-in request is challenged before credentials are accepted.

When that happens:

- headless runs will fail with a clear message telling you USCIS returned an AWS WAF challenge
- `--headed` gives you a visible Firefox window so you can complete the challenge manually if USCIS presents one

Example:

```bash
.venv/bin/python -m fusi --headed
```

## Implementation Summary

The code is split into three small modules:

- [fusi/config.py](fusi/config.py): parses `config.toml` and validates account fields
- [fusi/cli.py](fusi/cli.py): argument parsing, all-account scanning, update detection, and output formatting
- [fusi/cache.py](fusi/cache.py): JSON timestamp cache loading and atomic persistence
- [fusi/failures.py](fusi/failures.py): persistent failure history and login-attempt guard
- [fusi/uscis.py](fusi/uscis.py): browser automation, TOTP submission, WAF challenge detection, SAML handoff, and case fetch

The login flow is implemented with Playwright instead of raw HTTP requests because USCIS now challenges simple HTTP clients during sign-in. Using a real browser session is the practical way to reach the authenticated case API.

## Output

On the first run, the CLI prints each case's raw `events` array as formatted JSON and caches its latest `updatedAt` value. Later runs print only changed cases in this form:

```text
example I-485 got an update at 2026-06-24
[
  ...
]
```

When no timestamps changed, it prints:

```text
all cases are not updated
```

Example shape:

```json
[
  {
    "created_at": "2026-04-01T12:34:56.000Z",
    "event_name": "Case Was Received"
  }
]
```
