const validationForm = document.getElementById("validation-form");
const sendWhatsAppButton = document.getElementById("send-whatsapp");
const clearLogsButton = document.getElementById("clear-logs");
const startRealCallButton = document.getElementById("start-real-call");
const startDiagnosticCallButton = document.getElementById("start-diagnostic-call");

const payloadPreview = document.getElementById("payload-preview");
const responsePreview = document.getElementById("response-preview");
const requestsPreview = document.getElementById("requests-preview");
const logsPreview = document.getElementById("logs-preview");
const sendsPreview = document.getElementById("sends-preview");
const webhookPreview = document.getElementById("webhook-preview");
const liveBatchPreview = document.getElementById("live-batch-preview");
const transcriptPreview = document.getElementById("transcript-preview");

const requestsCount = document.getElementById("requests-count");
const sendsCount = document.getElementById("sends-count");
const logsCount = document.getElementById("logs-count");
const webhookStatus = document.getElementById("webhook-status");

let liveBatchId = null;
let refreshIntervalId = null;

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function buildTranscriptView(batchData) {
  if (!batchData || !Array.isArray(batchData.records) || batchData.records.length === 0) {
    return { status: "Nenhuma transcricao disponivel ainda." };
  }

  const transcripts = batchData.records
    .map((record) => {
      const lastAttempt = Array.isArray(record.call_attempts)
        ? record.call_attempts[record.call_attempts.length - 1]
        : null;
      const summary = lastAttempt?.transcript_summary || record.transcript_summary || "";

      if (!summary) {
        return null;
      }

      const view = {
        external_id: record.external_id,
        call_result: record.call_result,
        business_status: record.business_status,
        raw: summary,
      };

      for (const segment of summary.split(" | ")) {
        if (segment.startsWith("cliente:")) {
          view.cliente = segment.slice("cliente:".length).trim();
        }
        if (segment.startsWith("agente:")) {
          view.agente = segment.slice("agente:".length).trim();
        }
      }

      return view;
    })
    .filter(Boolean);

  if (transcripts.length === 0) {
    return { status: "Nenhuma transcricao disponivel ainda." };
  }

  return transcripts;
}

function readFormPayload() {
  const formData = new FormData(validationForm);
  return {
    client_name: formData.get("client_name"),
    cnpj: formData.get("cnpj"),
    phone: formData.get("phone"),
    call_scenario: formData.get("call_scenario"),
    fallback_message: formData.get("fallback_message"),
  };
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const text = await response.text();
  let data = {};

  try {
    data = text ? JSON.parse(text) : {};
  } catch (_error) {
    data = { raw_text: text };
  }

  return { ok: response.ok, status: response.status, data };
}

async function loadState() {
  const { data } = await requestJson("/test/state", { method: "GET" });

  requestsCount.textContent = String(data.recent_requests?.length || 0);
  sendsCount.textContent = String(data.recent_whatsapp_sends?.length || 0);
  logsCount.textContent = String(data.logs?.length || 0);
  webhookStatus.textContent = data.last_webhook_event?.event_type || "Nenhum";

  requestsPreview.textContent = prettyJson(data.recent_requests || []);
  logsPreview.textContent = prettyJson(data.logs || []);
  sendsPreview.textContent = prettyJson(data.recent_whatsapp_sends || []);
  webhookPreview.textContent = prettyJson(data.last_webhook_payload || {});
}

function stopAutoRefresh() {
  if (refreshIntervalId !== null) {
    window.clearInterval(refreshIntervalId);
    refreshIntervalId = null;
  }
}

function startAutoRefresh() {
  if (refreshIntervalId !== null || !liveBatchId) {
    return;
  }

  refreshIntervalId = window.setInterval(async () => {
    await refreshDashboards();
  }, 3000);
}

async function loadLiveBatch() {
  if (!liveBatchId) {
    liveBatchPreview.textContent = "{}";
    transcriptPreview.textContent = "{}";
    return;
  }

  const result = await requestJson(`/validations/${liveBatchId}`, { method: "GET" });
  liveBatchPreview.textContent = prettyJson({
    batch_id: liveBatchId,
    status: result.status,
    body: result.data,
  });
  transcriptPreview.textContent = prettyJson(buildTranscriptView(result.data));

  if (result.ok && result.data.result_ready === true) {
    stopAutoRefresh();
  }
}

async function startVoiceCall(twimlMode) {
  const payload = readFormPayload();
  payloadPreview.textContent = prettyJson({ ...payload, twiml_mode: twimlMode });

  const result = await requestJson(`/test/voice-call/start?twiml_mode=${encodeURIComponent(twimlMode)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  responsePreview.textContent = prettyJson({
    status: result.status,
    body: result.data,
  });

  if (result.ok && result.data.batch_id) {
    liveBatchId = result.data.batch_id;
    startAutoRefresh();
  }

  await loadLiveBatch();
}

validationForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const payload = readFormPayload();
  payloadPreview.textContent = prettyJson(payload);

  const result = await requestJson("/test/validate", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  responsePreview.textContent = prettyJson({
    status: result.status,
    body: result.data,
  });

  await loadState();
});

startRealCallButton.addEventListener("click", async () => {
  await startVoiceCall("media_stream");
});

startDiagnosticCallButton.addEventListener("click", async () => {
  await startVoiceCall("diagnostic_say");
});

sendWhatsAppButton.addEventListener("click", async () => {
  const payload = {
    phone: document.getElementById("phone").value,
    message: document.getElementById("fallback_message").value,
  };

  payloadPreview.textContent = prettyJson(payload);

  const result = await requestJson("/test/whatsapp/send", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  responsePreview.textContent = prettyJson({
    status: result.status,
    body: result.data,
  });

  await loadState();
});

clearLogsButton.addEventListener("click", async () => {
  const result = await requestJson("/test/logs/clear", {
    method: "POST",
    body: JSON.stringify({}),
  });

  responsePreview.textContent = prettyJson({
    status: result.status,
    body: result.data,
  });
  payloadPreview.textContent = "{}";
  liveBatchId = null;
  stopAutoRefresh();

  await loadState();
  await loadLiveBatch();
});

async function refreshDashboards() {
  await loadState();
  await loadLiveBatch();
}

refreshDashboards();
