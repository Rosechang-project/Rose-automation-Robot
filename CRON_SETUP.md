# Cron setup

This project has two different cron-related paths:

- `GET /` keeps the Render service awake.
- `GET or POST /cron/reminder` triggers the LINE reminder job.

## Render environment variable

Add this environment variable in the Render service settings:

```text
CRON_SECRET=your_private_random_secret
```

The value must match the `X-Cron-Secret` header used by cron-job.org.

## cron-job.org keep-alive job

Use this job to keep Render awake:

```text
URL: https://rose-automation-robot.onrender.com/
Method: GET
Schedule: every 10 minutes
```

Make sure `Enable job` is switched on.

## cron-job.org reminder job

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
  "scheduler_running": true,
  "next_internal_reminder": "...",
  "checked_at": "..."
}
```

If `cron_secret_configured` is `false`, add `CRON_SECRET` in Render and redeploy or restart the service.
