import assert from "node:assert/strict";
import test from "node:test";

import { handleQueue, handleRequest } from "../src/index.js";

const MOCK_ENV = { SIDE_BRAIN_CAPTURE_TOKEN: "test-token", SIDE_BRAIN_CAPTURE_MOCK_QUEUE: "true" };

test("GET /health returns ok", async () => {
  const response = await handleRequest(new Request("https://capture.example.test/health"), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.deepEqual(body, { success: true, status: "ok" });
});

test("POST /capture queues a valid capture when CAPTURE_QUEUE is bound", async () => {
  const sentMessages = [];
  const env = {
    SIDE_BRAIN_CAPTURE_TOKEN: "test-token",
    CAPTURE_QUEUE: {
      async send(message) {
        sentMessages.push(message);
      },
    },
  };
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
    env,
  );
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(body.success, true);
  assert.equal(body.status, "queued");
  assert.match(body.message_id, /^cap_\d{8}_[0-9a-f]{16}$/);
  assert.equal(body.normalized, undefined);
  assert.equal(sentMessages.length, 1);
  assert.equal(sentMessages[0].message_id, body.message_id);
  assert.equal(sentMessages[0].source, "iphone_shortcut");
  assert.equal(sentMessages[0].input_type, "text");
  assert.equal(sentMessages[0].content, "Remind me tomorrow afternoon to update the cover letter.");
  assert.equal(sentMessages[0].created_at, "2026-06-30T10:15:00+02:00");
  assert.equal(sentMessages[0].timezone, "Europe/Berlin");
  assert.equal(sentMessages[0].locale, "en");
  assert.deepEqual(sentMessages[0].metadata, { shortcut_version: "v1" });
});

test("POST /capture accepts and normalizes a valid capture in mock mode", async () => {
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
    MOCK_ENV,
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

test("POST /capture uses mock mode before queue binding when explicitly enabled", async () => {
  const sentMessages = [];
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), {
    SIDE_BRAIN_CAPTURE_TOKEN: "test-token",
    SIDE_BRAIN_CAPTURE_MOCK_QUEUE: "true",
    CAPTURE_QUEUE: {
      async send(message) {
        sentMessages.push(message);
      },
    },
  });
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(body.status, "accepted_mock");
  assert.equal(sentMessages.length, 0);
});

test("POST /capture applies defaults for optional fields", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(body.normalized.source, "manual_api");
  assert.equal(body.normalized.input_type, "text");
  assert.equal(body.normalized.timezone, "UTC");
  assert.equal(body.normalized.locale, "und");
  assert.deepEqual(body.normalized.metadata, {});
});

test("POST /capture rejects missing or invalid bearer token", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }, "wrong-token"), MOCK_ENV);
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
    MOCK_ENV,
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
  const response = await handleRequest(jsonRequest({ content: "   " }), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "invalid_payload",
    message: "content cannot be empty.",
  });
});

test("POST /capture rejects oversized content", async () => {
  const response = await handleRequest(jsonRequest({ content: "x".repeat(20001) }), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 413);
  assert.deepEqual(body, {
    success: false,
    error: "payload_too_large",
    message: "content must be at most 20000 characters.",
  });
});

test("POST /capture rejects unsupported source", async () => {
  const response = await handleRequest(jsonRequest({ source: "sms", content: "Quick capture" }), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "unsupported_source",
    message: "source must be one of: iphone_shortcut, web_form, manual_api, n8n, codex.",
  });
});

test("POST /capture rejects unsupported input type", async () => {
  const response = await handleRequest(jsonRequest({ input_type: "audio", content: "Quick capture" }), MOCK_ENV);
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.deepEqual(body, {
    success: false,
    error: "unsupported_input_type",
    message: "input_type must be one of: text, voice_transcript, url, file_note.",
  });
});

test("POST /capture rejects non-object metadata", async () => {
  const response = await handleRequest(
    jsonRequest({ metadata: ["not", "object"], content: "Quick capture" }),
    MOCK_ENV,
  );
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

test("POST /capture returns server error when queue and mock mode are not configured", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), {
    SIDE_BRAIN_CAPTURE_TOKEN: "test-token",
  });
  const body = await response.json();

  assert.equal(response.status, 500);
  assert.deepEqual(body, {
    success: false,
    error: "server_misconfigured",
    message: "CAPTURE_QUEUE is not configured. Set SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true for local mock mode.",
  });
});

test("POST /capture returns queue error when queue send fails", async () => {
  const response = await handleRequest(jsonRequest({ content: "Quick capture" }), {
    SIDE_BRAIN_CAPTURE_TOKEN: "test-token",
    CAPTURE_QUEUE: {
      async send() {
        throw new Error("queue unavailable");
      },
    },
  });
  const body = await response.json();

  assert.equal(response.status, 503);
  assert.deepEqual(body, {
    success: false,
    error: "queue_unavailable",
    message: "Capture could not be queued. Try again later.",
  });
});

test("queue consumer validates and logs queued captures without logging content", async () => {
  const logs = [];
  const originalLog = console.log;
  console.log = (...args) => logs.push(args);

  try {
    const result = await handleQueue({
      messages: [
        {
          id: "msg-1",
          body: normalizedCapture({
            message_id: "cap_20260630_abcdef123456",
            content: "Private capture content",
          }),
        },
      ],
    });

    assert.deepEqual(result, {
      processed: 1,
      message_ids: ["cap_20260630_abcdef123456"],
    });
    assert.equal(logs.length, 1);
    assert.equal(logs[0][0], "side-brain capture consumed");

    const loggedPayload = JSON.parse(logs[0][1]);
    assert.equal(loggedPayload.message_id, "cap_20260630_abcdef123456");
    assert.equal(loggedPayload.content_length, "Private capture content".length);
    assert.equal(loggedPayload.content, undefined);
  } finally {
    console.log = originalLog;
  }
});

test("queue consumer forwards queued captures to local ingest when enabled", async () => {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ success: true, status: "ingested" }), { status: 201 });
  };

  try {
    const result = await handleQueue(
      {
        messages: [
          {
            id: "msg-1",
            body: normalizedCapture({
              message_id: "cap_20260630_abcdef123456",
              content: "Private capture content",
            }),
          },
        ],
      },
      {
        SIDE_BRAIN_QUEUE_FORWARD_ENABLED: "true",
        SIDE_BRAIN_LOCAL_INGEST_URL: "http://127.0.0.1:8765/ingest/capture",
        SIDE_BRAIN_LOCAL_INGEST_TOKEN: "local-token",
      },
    );

    assert.equal(result.processed, 1);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "http://127.0.0.1:8765/ingest/capture");
    assert.equal(requests[0].options.method, "POST");
    assert.equal(requests[0].options.headers.Authorization, "Bearer local-token");
    assert.deepEqual(JSON.parse(requests[0].options.body), normalizedCapture({
      message_id: "cap_20260630_abcdef123456",
      content: "Private capture content",
    }));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("queue consumer does not forward when forwarding is disabled", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("fetch should not be called");
  };

  try {
    const result = await handleQueue({
      messages: [
        {
          id: "msg-1",
          body: normalizedCapture(),
        },
      ],
    });

    assert.equal(result.processed, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("queue consumer throws when forwarding is enabled without ingest config", async () => {
  await assert.rejects(
    () =>
      handleQueue(
        {
          messages: [
            {
              id: "msg-1",
              body: normalizedCapture(),
            },
          ],
        },
        {
          SIDE_BRAIN_QUEUE_FORWARD_ENABLED: "true",
        },
      ),
    /Local ingest forwarding is enabled but URL or token is missing/,
  );
});

test("queue consumer throws when local ingest returns an error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ success: false, error: "unauthorized" }), {
      status: 401,
    });

  try {
    await assert.rejects(
      () =>
        handleQueue(
          {
            messages: [
              {
                id: "msg-1",
                body: normalizedCapture(),
              },
            ],
          },
          {
            SIDE_BRAIN_QUEUE_FORWARD_ENABLED: "true",
            SIDE_BRAIN_LOCAL_INGEST_URL: "http://127.0.0.1:8765/ingest/capture",
            SIDE_BRAIN_LOCAL_INGEST_TOKEN: "bad-token",
          },
        ),
      /Local ingest returned HTTP 401/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("queue consumer throws for invalid queued captures", async () => {
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args);

  try {
    await assert.rejects(
      () =>
        handleQueue({
          messages: [
            {
              id: "msg-1",
              body: {
                message_id: "bad-id",
                content: "Quick capture",
              },
            },
          ],
        }),
      /Invalid queued capture message count: 1/,
    );

    assert.equal(errors.length, 1);
    assert.equal(errors[0][0], "side-brain invalid queued captures");
    assert.match(errors[0][1], /message_id has an invalid format/);
  } finally {
    console.error = originalError;
  }
});

test("unknown routes return not found", async () => {
  const response = await handleRequest(new Request("https://capture.example.test/unknown"), MOCK_ENV);
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

function normalizedCapture(overrides = {}) {
  return {
    message_id: "cap_20260630_abcdef123456",
    source: "iphone_shortcut",
    input_type: "text",
    content: "Quick capture",
    created_at: "2026-06-30T10:15:00+02:00",
    received_at: "2026-06-30T10:15:01+02:00",
    timezone: "Europe/Berlin",
    locale: "en",
    metadata: {},
    ...overrides,
  };
}
