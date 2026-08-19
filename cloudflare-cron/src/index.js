const KEEP_ALIVE_CRON = "*/10 * * * *";
const REMINDER_CRON = "5 0,13 * * *";

export default {
  async scheduled(controller, env) {
    const baseUrl = getBaseUrl(env);

    switch (controller.cron) {
      case KEEP_ALIVE_CRON:
        await checkedFetch(`${baseUrl}/`);
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
      });
    }

    return new Response("Not found", { status: 404 });
  },
};

function getBaseUrl(env) {
  return (env.ROSE_BASE_URL || "https://rose-automation-robot.onrender.com").replace(/\/+$/, "");
}

async function triggerReminder(baseUrl, env) {
  if (!env.CRON_SECRET) {
    throw new Error("CRON_SECRET is not configured in Cloudflare Worker secrets.");
  }

  await checkedFetch(`${baseUrl}/cron/reminder`, {
    headers: {
      "X-Cron-Secret": env.CRON_SECRET,
    },
  });
}

async function checkedFetch(url, init = {}) {
  const response = await fetch(url, init);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${url} failed: ${response.status} ${body}`);
  }

  return response;
}
