const KEEP_ALIVE_CRON = "*/10 * * * *";
const REMINDER_CRON = "5 0,13 * * *";
const RELEASE = "2026-11-25-keepalive-retry";
const REQUEST_TIMEOUT_MS = 75_000;

export default {
  async scheduled(controller, env) {
    const baseUrl = getBaseUrl(env);

    switch (controller.cron) {
      case KEEP_ALIVE_CRON:
        await fetchWithRetries(`${baseUrl}/`, { cache: "no-store" }, "keep_alive");
        break;
      case REMINDER_CRON:
        await triggerReminder(baseUrl, env);
        break;
      default:
        throw new Error(`Unhandled cron trigger: ${controller.cron}`);
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({
        status: "ok",
        base_url: getBaseUrl(env),
        keep_alive_cron: KEEP_ALIVE_CRON,
        reminder_cron: REMINDER_CRON,
        release: RELEASE,
      });
    }

    return new Response("Not found", { status: 404 });
  },
};

function getBaseUrl(env) {
  return (env.ROSE_BASE_URL || "https://rose-automation-robot.onrender.com").replace(new RegExp("/+$"), "");
}

async function triggerReminder(baseUrl, env) {
  if (!env.CRON_SECRET) {
    throw new Error("CRON_SECRET is not configured in Cloudflare Worker secrets.");
  }

  const url = `${baseUrl}/cron/reminder`;
  const init = {
    method: "POST",
    headers: {
      "X-Cron-Secret": env.CRON_SECRET,
    },
  };

  await fetchWithRetries(url, init, "reminder");
}

async function fetchWithRetries(url, init, job) {
  const delays = [5_000, 15_000];
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const started = Date.now();
    try {
      const status = await checkedFetch(url, init, job);
      console.log(JSON.stringify({
        job, attempt, outcome: "success", status, duration_ms: Date.now() - started,
      }));
      return;
    } catch (error) {
      const retry = attempt < 3 && (!error.status || error.status >= 500);
      const detail = {
        job, attempt, outcome: "failure", status: error.status ?? null,
        error: error.name, message: error.message, duration_ms: Date.now() - started,
        retry,
      };
      if (!retry) {
        console.error(JSON.stringify(detail));
        throw error;
      }
      console.warn(JSON.stringify(detail));
      await new Promise((resolve) => setTimeout(resolve, delays[attempt - 1]));
    }
  }
}

async function checkedFetch(url, init, job) {
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  // Consume each response before retrying so connections can be released.
  const body = await response.text();

  if (!response.ok) {
    const error = Object.assign(new Error(`Render returned HTTP ${response.status}`), {
      status: response.status,
    });
    throw error;
  }

  if (job === "keep_alive") {
    let health;
    try {
      health = JSON.parse(body);
    } catch {
      health = null;
    }
    if (health?.status !== "Rose scheduler bot is running") {
      const error = Object.assign(new Error("Render has not returned the bot health response"), {
        status: 502,
      });
      throw error;
    }
  }

  return response.status;
}
