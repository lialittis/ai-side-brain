import assert from "node:assert/strict";
import test from "node:test";

import { handleRequest } from "../src/index.js";

const ENV = { SIDE_BRAIN_CAPTURE_TOKEN: "test-token" };

test("GET /health returns ok", async () => {
  const response = await handleRequest(new Request("https://capture.example.test/health"), ENV);
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.deepEqual(body, { success: true, status: "ok" });
});

test("POST /capture accepts and normalizes a valid capture", async () => {
  const response = await handleRequest(
    jsonRequest({
      source: "iphone_shortcut",
      input_type: "text",
      content: "  Remind me tomorrow afternoon to update the cover letter.  ",
      created_at: "2026-06-30T10:15:00+02:00",
      timezone: "Europe/Berlin",
      locale: "en",
      metadata: { shortcut_version: "v1" },
    }),
    ENV,
  );
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(body.success, true);
  assert.equal(body.status, "accepted_mock");
  assert.match(body.message_id, /^cap_\d{8}_[0-9a-f]{16}$/);
  assert.equal(body.message_id, body.normalized.message_id);
  assert.equal(body.normalized.source, "iphone_shortcut");
  assert.equal(body.normalized.input_type, "text");
  assert.equal(body.normalized.content, "Remind me tomorrow afternoon to update the cover letter.");
  assert.equal(body.normalized.created_at, "2026-06-30T10:15:00+02:00");
  assert.equal(body.normalized.timezone, "Europe/Berlin");
  assert.equal(body.normalized.locale, "en");
  assert.deepEqual(body.normalized.metadata, { shortcut_version: "v1" });
});

test("POST /capture applies defaults for optional fields", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), ENV);
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(body.normalized.source, "manual_api");
  assert.equal(body.normalized.input_type, "text");
  assert.equal(body.normalized.timezone, "UTC");
  assert.equal(body.normalized.locale, "und");
  assert.deepEqual(body.normalized.metadata, {});
});

test("POST /capture rejects missing or invalid bearer token", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }, "wrong-token"), ENV);
  const body = await response.json();

  assert.equal(response.status, 401);
  assert.deepEqual(body, {
    success: false,
    error: "unauthorized",
    message: "Missing or invalid bearer token.",
  });
});

test("POST /capture rejects invalid JSON", async () => {
  const response = await handleRequest(
    new Request("https://capture.example.test/capture", {
      method: "POST",
      headers: {
        Authorization: "Bearer test-token",
        "Content-Type": "application/json",
      },
      body: "{",
    }),
    ENV,
  );
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "invalid_json",
    message: "Request body must be valid JSON.",
  });
});

test("POST /capture rejects empty content", async () => {
  const response = await handleRequest(jsonRequest({ content: "   " }), ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "invalid_payload",
    message: "content cannot be empty.",
  });
});

test("POST /capture rejects oversized content", async () => {
  const response = await handleRequest(jsonRequest({ content: "x".repeat(20001) }), ENV);
  const body = await response.json();

  assert.equal(response.status, 413);
  assert.deepEqual(body, {
    success: false,
    error: "payload_too_large",
    message: "content must be at most 20000 characters.",
  });
});

test("POST /capture rejects unsupported source", async () => {
  const response = await handleRequest(jsonRequest({ source: "sms", content: "Quick capture" }), ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "unsupported_source",
    message: "source must be one of: iphone_shortcut, web_form, manual_api, n8n, codex.",
  });
});

test("POST /capture rejects unsupported input type", async () => {
  const response = await handleRequest(jsonRequest({ input_type: "audio", content: "Quick capture" }), ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "unsupported_input_type",
    message: "input_type must be one of: text, voice_transcript, url, file_note.",
  });
});

test("POST /capture rejects non-object metadata", async () => {
  const response = await handleRequest(jsonRequest({ metadata: ["not", "object"], content: "Quick capture" }), ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "invalid_payload",
    message: "metadata must be a JSON object.",
  });
});

test("POST /capture returns server error when token is not configured", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), {});
  const body = await response.json();

  assert.equal(response.status, 500);
  assert.deepEqual(body, {
    success: false,
    error: "server_misconfigured",
    message: "SIDE_BRAIN_CAPTURE_TOKEN is not configured.",
  });
});

test("unknown routes return not found", async () => {
  const response = await handleRequest(new Request("https://capture.example.test/unknown"), ENV);
  const body = await response.json();

  assert.equal(response.status, 404);
  assert.deepEqual(body, {
    success: false,
    error: "not_found",
    message: "Route not found.",
  });
});

function jsonRequest(payload, token = "test-token") {
  return new Request("https://capture.example.test/capture", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

