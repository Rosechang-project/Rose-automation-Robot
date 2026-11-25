import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import worker from "../src/index.js";

const env = { ROSE_BASE_URL: "https://example.invalid", CRON_SECRET: "test-secret" };
const cron = { cron: "*/10 * * * *" };
const healthy = () => Response.json({ status: "Rose scheduler bot is running" });
let originalFetch;
let originalTimeout;
let originalConsole;
let calls;
let logs;

beforeEach(() => {
  originalFetch = globalThis.fetch;
  originalTimeout = globalThis.setTimeout;
  originalConsole = { log: console.log, warn: console.warn, error: console.error };
  calls = [];
  logs = [];
  globalThis.setTimeout = (callback) => { callback(); return 0; };
  for (const level of ["log", "warn", "error"]) {
    console[level] = (entry) => logs.push({ level, ...JSON.parse(entry) });
  }
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.setTimeout = originalTimeout;
  Object.assign(console, originalConsole);
});

function respondWith(responses) {
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    const response = responses.shift();
    if (response instanceof Error) throw response;
    assert.ok(response, "Unexpected retry");
    return response;
  };
}

test("keep-alive retries a cold-start page and a server failure before succeeding", async () => {
  respondWith([new Response("<html>Starting</html>"), new Response("", { status: 503 }), healthy()]);
  await worker.scheduled(cron, env);
  assert.equal(calls.length, 3);
  assert.equal(calls[0].init.cache, "no-store");
  assert.ok(calls.every(({ init }) => init.signal instanceof AbortSignal));
  assert.deepEqual(logs.map(({ outcome }) => outcome), ["failure", "failure", "success"]);
});

test("timeouts stop after three attempts and record a final error", async () => {
  respondWith(Array.from({ length: 3 }, () => new DOMException("Request timed out", "TimeoutError")));
  await assert.rejects(worker.scheduled(cron, env), { name: "TimeoutError" });
  assert.equal(calls.length, 3);
  assert.equal(logs.at(-1).level, "error");
  assert.equal(logs.at(-1).retry, false);
});

test("client errors stop immediately and response content and secrets stay out of logs", async () => {
  respondWith([new Response("test-secret private response", { status: 403 })]);
  await assert.rejects(worker.scheduled(cron, env), /403/);
  assert.equal(calls.length, 1);
  assert.ok(!JSON.stringify(logs).includes("test-secret"));
});

test("reminder retries preserve the method and authentication header", async () => {
  respondWith([new Response("", { status: 503 }), Response.json({ status: "completed" })]);
  await worker.scheduled({ cron: "5 0,13 * * *" }, env);
  assert.equal(calls.length, 2);
  for (const { url, init } of calls) {
    assert.equal(url, "https://example.invalid/cron/reminder");
    assert.equal(init.method, "POST");
    assert.equal(init.headers["X-Cron-Secret"], "test-secret");
  }
});
