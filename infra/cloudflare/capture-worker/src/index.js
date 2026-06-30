const MAX_CONTENT_LENGTH = 20000;
const SUPPORTED_SOURCES = new Set(["iphone_shortcut", "web_form", "manual_api", "n8n", "codex"]);
const SUPPORTED_INPUT_TYPES = new Set(["text", "voice_transcript", "url", "file_note"]);

export default {
  async fetch(request, env) {
    return handleRequest(request, env);
  },

  async queue(batch, env, ctx) {
    await handleQueue(batch, env, ctx);
  },
};

export async function handleQueue(batch, env = {}) {
  const messages = Array.isArray(batch?.messages) ? batch.messages : [];
  const processedMessageIds = [];
  const invalidMessages = [];

  for (const message of messages) {
    const validation = validateQueuedCapture(message.body);
    if (!validation.ok) {
      invalidMessages.push({
        id: message.id || message.body?.message_id || "unknown",
        reason: validation.message,
      });
      continue;
    }

    const capture = message.body;
    if (isQueueForwardEnabled(env)) {
      await forwardCaptureToLocalIngest(capture, env);
    }

    processedMessageIds.push(capture.message_id);
    console.log(
      "side-brain capture consumed",
      JSON.stringify({
        message_id: capture.message_id,
        source: capture.source,
        input_type: capture.input_type,
        content_length: capture.content.length,
        created_at: capture.created_at,
        received_at: capture.received_at,
      }),
    );
  }

  if (invalidMessages.length > 0) {
    console.error("side-brain invalid queued captures", JSON.stringify(invalidMessages));
    throw new Error(`Invalid queued capture message count: ${invalidMessages.length}`);
  }

  return {
    processed: processedMessageIds.length,
    message_ids: processedMessageIds,
  };
}

export async function handleRequest(request, env = {}) {
  const url = new URL(request.url);

  if (request.method === "GET" && url.pathname === "/health") {
    return jsonResponse({ success: true, status: "ok" });
  }

  if (url.pathname !== "/capture") {
    return jsonError(404, "not_found", "Route not found.");
  }

  if (request.method !== "POST") {
    return jsonError(405, "method_not_allowed", "Use POST /capture.", { Allow: "POST" });
  }

  const configuredToken = env.SIDE_BRAIN_CAPTURE_TOKEN;
  if (!configuredToken) {
    return jsonError(500, "server_misconfigured", "SIDE_BRAIN_CAPTURE_TOKEN is not configured.");
  }

  const authorization = request.headers.get("authorization") || "";
  if (authorization !== `Bearer ${configuredToken}`) {
    return jsonError(401, "unauthorized", "Missing or invalid bearer token.");
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return jsonError(400, "invalid_json", "Request body must be valid JSON.");
  }

  const validation = validateCapturePayload(payload);
  if (!validation.ok) {
    return jsonError(validation.status, validation.error, validation.message);
  }

  const receivedAt = new Date().toISOString();
  const normalized = normalizeCapturePayload(payload, receivedAt);

  if (isMockQueueEnabled(env)) {
    return jsonResponse(
      {
        success: true,
        message_id: normalized.message_id,
        status: "accepted_mock",
        normalized,
      },
      202,
    );
  }

  if (hasQueueBinding(env)) {
    try {
      await env.CAPTURE_QUEUE.send(normalized);
    } catch {
      return jsonError(503, "queue_unavailable", "Capture could not be queued. Try again later.");
    }

    return jsonResponse(
      {
        success: true,
        message_id: normalized.message_id,
        status: "queued",
      },
      202,
    );
  }

  return jsonError(
    500,
    "server_misconfigured",
    "CAPTURE_QUEUE is not configured. Set SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true for local mock mode.",
  );
}

function hasQueueBinding(env) {
  return Boolean(env.CAPTURE_QUEUE && typeof env.CAPTURE_QUEUE.send === "function");
}

function isMockQueueEnabled(env) {
  return ["1", "true", "yes"].includes(String(env.SIDE_BRAIN_CAPTURE_MOCK_QUEUE || "").toLowerCase());
}

function isQueueForwardEnabled(env) {
  return ["1", "true", "yes"].includes(String(env.SIDE_BRAIN_QUEUE_FORWARD_ENABLED || "").toLowerCase());
}

async function forwardCaptureToLocalIngest(capture, env) {
  const ingestUrl = String(env.SIDE_BRAIN_LOCAL_INGEST_URL || "").trim();
  const ingestToken = String(env.SIDE_BRAIN_LOCAL_INGEST_TOKEN || "").trim();

  if (!ingestUrl || !ingestToken) {
    throw new Error("Local ingest forwarding is enabled but URL or token is missing.");
  }

  let response;
  try {
    response = await fetch(ingestUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ingestToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(capture),
    });
  } catch (error) {
    throw new Error(`Local ingest request failed: ${error.message}`);
  }

  if (!response.ok) {
    let responseText = "";
    try {
      responseText = await response.text();
    } catch {
      responseText = "";
    }
    throw new Error(`Local ingest returned HTTP ${response.status}: ${responseText}`);
  }
}

function validateCapturePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return invalidPayload("Request body must be a JSON object.");
  }

  if (typeof payload.content !== "string") {
    return invalidPayload("content must be a string.");
  }

  const content = payload.content.trim();
  if (!content) {
    return invalidPayload("content cannot be empty.");
  }

  if (content.length > MAX_CONTENT_LENGTH) {
    return {
      ok: false,
      status: 413,
      error: "payload_too_large",
      message: `content must be at most ${MAX_CONTENT_LENGTH} characters.`,
    };
  }

  const source = typeof payload.source === "string" && payload.source.trim() ? payload.source.trim() : "manual_api";
  if (!SUPPORTED_SOURCES.has(source)) {
    return {
      ok: false,
      status: 400,
      error: "unsupported_source",
      message: `source must be one of: ${Array.from(SUPPORTED_SOURCES).join(", ")}.`,
    };
  }

  const inputType =
    typeof payload.input_type === "string" && payload.input_type.trim() ? payload.input_type.trim() : "text";
  if (!SUPPORTED_INPUT_TYPES.has(inputType)) {
    return {
      ok: false,
      status: 400,
      error: "unsupported_input_type",
      message: `input_type must be one of: ${Array.from(SUPPORTED_INPUT_TYPES).join(", ")}.`,
    };
  }

  if (
    payload.metadata !== undefined &&
    (payload.metadata === null || typeof payload.metadata !== "object" || Array.isArray(payload.metadata))
  ) {
    return invalidPayload("metadata must be a JSON object.");
  }

  return { ok: true };
}

function validateQueuedCapture(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return invalidQueuedPayload("Queued message body must be an object.");
  }

  if (typeof payload.message_id !== "string" || !payload.message_id.trim()) {
    return invalidQueuedPayload("message_id is required.");
  }

  if (!/^cap_\d{8}_[0-9a-f]{12,}$/i.test(payload.message_id)) {
    return invalidQueuedPayload("message_id has an invalid format.");
  }

  if (typeof payload.content !== "string" || !payload.content.trim()) {
    return invalidQueuedPayload("content is required.");
  }

  if (payload.content.length > MAX_CONTENT_LENGTH) {
    return invalidQueuedPayload(`content must be at most ${MAX_CONTENT_LENGTH} characters.`);
  }

  if (typeof payload.source !== "string" || !SUPPORTED_SOURCES.has(payload.source)) {
    return invalidQueuedPayload(`source must be one of: ${Array.from(SUPPORTED_SOURCES).join(", ")}.`);
  }

  if (typeof payload.input_type !== "string" || !SUPPORTED_INPUT_TYPES.has(payload.input_type)) {
    return invalidQueuedPayload(`input_type must be one of: ${Array.from(SUPPORTED_INPUT_TYPES).join(", ")}.`);
  }

  if (typeof payload.created_at !== "string" || !isValidDateTime(payload.created_at)) {
    return invalidQueuedPayload("created_at must be an ISO 8601 timestamp.");
  }

  if (typeof payload.received_at !== "string" || !isValidDateTime(payload.received_at)) {
    return invalidQueuedPayload("received_at must be an ISO 8601 timestamp.");
  }

  if (typeof payload.timezone !== "string" || !payload.timezone.trim()) {
    return invalidQueuedPayload("timezone is required.");
  }

  if (typeof payload.locale !== "string" || !payload.locale.trim()) {
    return invalidQueuedPayload("locale is required.");
  }

  if (payload.metadata === null || typeof payload.metadata !== "object" || Array.isArray(payload.metadata)) {
    return invalidQueuedPayload("metadata must be a JSON object.");
  }

  return { ok: true };
}

function normalizeCapturePayload(payload, receivedAt) {
  const source = typeof payload.source === "string" && payload.source.trim() ? payload.source.trim() : "manual_api";
  const inputType =
    typeof payload.input_type === "string" && payload.input_type.trim() ? payload.input_type.trim() : "text";
  const createdAt =
    typeof payload.created_at === "string" && isValidDateTime(payload.created_at) ? payload.created_at : receivedAt;

  return {
    message_id: makeMessageId(receivedAt),
    source,
    input_type: inputType,
    content: payload.content.trim(),
    created_at: createdAt,
    received_at: receivedAt,
    timezone: typeof payload.timezone === "string" && payload.timezone.trim() ? payload.timezone.trim() : "UTC",
    locale: typeof payload.locale === "string" && payload.locale.trim() ? payload.locale.trim() : "und",
    metadata: payload.metadata || {},
  };
}

function makeMessageId(receivedAt) {
  const day = receivedAt.slice(0, 10).replaceAll("-", "");
  return `cap_${day}_${randomSuffix()}`;
}

function randomSuffix() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isValidDateTime(value) {
  return !Number.isNaN(Date.parse(value));
}

function invalidPayload(message) {
  return {
    ok: false,
    status: 400,
    error: "invalid_payload",
    message,
  };
}

function invalidQueuedPayload(message) {
  return {
    ok: false,
    message,
  };
}

function jsonError(status, error, message, extraHeaders = {}) {
  return jsonResponse({ success: false, error, message }, status, extraHeaders);
}

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}
