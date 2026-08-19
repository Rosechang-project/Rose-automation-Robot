# Cron setup

This project has two different cron-related paths:

- `GET /` keeps the Render service awake.
- `GET or POST /cron/reminder` triggers the LINE reminder job.

## Render environment variable

Add this environment variable in the Render service settings:

```text
CRON_SECRET=your_private_random_secret
ENABLE_INTERNAL_SCHEDULER=false
```

The value must match the `X-Cron-Secret` header used by the external cron service.
`ENABLE_INTERNAL_SCHEDULER=false` keeps Cloudflare as the only reminder scheduler, which avoids duplicate LINE reminders.

## Recommended: Cloudflare Workers Cron Triggers

This repo includes a small Cloudflare Worker in `cloudflare-cron/`.

The Worker replaces cron-job.org by calling Render on a schedule:

- `*/10 * * * *` keeps Render awake every 10 minutes.
- `5 0,13 * * *` triggers reminders at 08:05 and 21:05 Asia/Taipei.

Cloudflare cron expressions use UTC, so the reminder schedule is converted from Taiwan time:

- 08:05 Asia/Taipei = 00:05 UTC
- 21:05 Asia/Taipei = 13:05 UTC

### Deploy to Cloudflare

Install dependencies:

```bash
cd cloudflare-cron
npm install
```

Log in to Cloudflare:

```bash
npx wrangler login
```

Set the same secret value that Render uses for `CRON_SECRET`:

```bash
npx wrangler secret put CRON_SECRET
```

Deploy:

```bash
npx wrangler deploy
```

After the deploy finishes, disable the old cron-job.org jobs to avoid duplicate reminders.

## Legacy option: cron-job.org keep-alive job

Use this job to keep Render awake:

```text
URL: https://rose-automation-robot.onrender.com/
Method: GET
Schedule: every 10 minutes
```

Make sure `Enable job` is switched on.

## Legacy option: cron-job.org reminder job

Use this job to trigger actual reminders:

```text
URL: https://rose-automation-robot.onrender.com/cron/reminder
Method: GET
Header: X-Cron-Secret: your_private_random_secret
Schedule: 08:05 and 21:05 Asia/Taipei
```

`POST` also works, but `GET` is supported so the job still works with cron-job.org's common default method.

## Check status

Open this URL to check whether Render can see the cron secret and whether the internal scheduler is running:

```text
https://rose-automation-robot.onrender.com/cron/status
```

Expected healthy response:

```json
{
  "status": "ok",
  "cron_secret_configured": true,
  "internal_scheduler_enabled": false,
  "scheduler_running": false,
  "next_internal_reminder": null,
  "checked_at": "..."
}
```

If `cron_secret_configured` is `false`, add `CRON_SECRET` in Render and redeploy or restart the service.
