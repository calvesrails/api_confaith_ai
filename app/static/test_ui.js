const validationForm = document.getElementById("validation-form");
const batchValidationForm = document.getElementById("batch-validation-form");
const sendWhatsAppButton = document.getElementById("send-whatsapp");
const clearLogsButton = document.getElementById("clear-logs");
const startRealCallButton = document.getElementById("start-real-call");
const startDiagnosticCallButton = document.getElementById("start-diagnostic-call");
const startRealBatchCallButton = document.getElementById("start-real-batch-call");
const stopRealBatchCallButton = document.getElementById("stop-real-batch-call");
const downloadBatchResultsButton = document.getElementById("download-batch-results");

const payloadPreview = document.getElementById("payload-preview");
const responsePreview = document.getElementById("response-preview");
const requestsPreview = document.getElementById("requests-preview");
const logsPreview = document.getElementById("logs-preview");
const sendsPreview = document.getElementById("sends-preview");
const webhookPreview = document.getElementById("webhook-preview");
const liveBatchPreview = document.getElementById("live-batch-preview");
const transcriptPreview = document.getElementById("transcript-preview");
const batchRecordsPreview = document.getElementById("batch-records-preview");
const batchCallLogPreview = document.getElementById("batch-call-log-preview");

const requestsCount = document.getElementById("requests-count");
const sendsCount = document.getElementById("sends-count");
const logsCount = document.getElementById("logs-count");
const webhookStatus = document.getElementById("webhook-status");

let liveBatchId = null;
let refreshIntervalId = null;

function readRealtimeProfile() {
  const model = document.getElementById("realtime_model").value;
  const voice = document.getElementById("realtime_voice").value;
  const outputSpeedRaw = document.getElementById("realtime_output_speed").value;
  const styleProfile = document.getElementById("realtime_style_profile").value;

  return {
    realtime_model: model || null,
    realtime_voice: voice || null,
    realtime_output_speed: outputSpeedRaw === "" ? null : Number(outputSpeedRaw),
    realtime_style_profile: styleProfile || null,
  };
}

function buildRealtimeQueryString() {
  const realtimeProfile = readRealtimeProfile();
  const params = new URLSearchParams();

  if (realtimeProfile.realtime_model) {
    params.set("realtime_model", realtimeProfile.realtime_model);
  }
  if (realtimeProfile.realtime_voice) {
    params.set("realtime_voice", realtimeProfile.realtime_voice);
  }
  if (realtimeProfile.realtime_output_speed != null && !Number.isNaN(realtimeProfile.realtime_output_speed)) {
    params.set("realtime_output_speed", String(realtimeProfile.realtime_output_speed));
  }
  if (realtimeProfile.realtime_style_profile) {
    params.set("realtime_style_profile", realtimeProfile.realtime_style_profile);
  }

  return params.toString();
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatLogTimestamp(value) {
  if (!value) {
    return null;
  }

  return String(value).replace("T", " ").replace(/\.\d+/, "").replace("Z", " UTC");
}

function buildBatchCallLog(batchData) {
  if (!batchData || !Array.isArray(batchData.records) || batchData.records.length === 0) {
    return "Nenhum lote carregado ainda.";
  }

  const historyEntries = [];
  const activeEntries = [];
  const queuedEntries = [];

  for (const record of batchData.records) {
    const attempts = Array.isArray(record.call_attempts) ? record.call_attempts : [];

    for (const attempt of attempts) {
      const phone = attempt.phone_dialed || record.phone_normalized || record.phone_original || "-";
      const source = attempt.phone_source || "-";
      const providerCallId = attempt.provider_call_id || "-";
      const baseLabel = `registro ${record.external_id} | tentativa ${attempt.attempt_number} | telefone ${phone}`;

      if (attempt.started_at) {
        historyEntries.push({
          timestamp: attempt.started_at,
          order: 1,
          text: `${formatLogTimestamp(attempt.started_at)} | chamada iniciada | ${baseLabel} | origem=${source} | provider_call_id=${providerCallId}`,
        });
      }

      if (attempt.finished_at) {
        const observation = attempt.observation ? ` | observacao=${attempt.observation}` : "";
        historyEntries.push({
          timestamp: attempt.finished_at,
          order: 2,
          text: `${formatLogTimestamp(attempt.finished_at)} | retorno final | ${baseLabel} | status=${attempt.status} | resultado=${attempt.result}${observation}`,
        });
        continue;
      }

      if (attempt.started_at) {
        activeEntries.push(
          `[em andamento] | ${baseLabel} | status=${attempt.status} | resultado=${attempt.result} | origem=${source} | provider_call_id=${providerCallId}`,
        );
        continue;
      }

      if (attempt.status === "queued" || attempt.result === "pending_dispatch") {
        queuedEntries.push(
          `[na fila] | ${baseLabel} | status=${attempt.status} | resultado=${attempt.result} | origem=${source}`,
        );
      }
    }
  }

  historyEntries.sort((left, right) => {
    const leftTs = new Date(left.timestamp).getTime();
    const rightTs = new Date(right.timestamp).getTime();
    if (leftTs === rightTs) {
      return left.order - right.order;
    }
    return leftTs - rightTs;
  });

  const lines = [
    `lote ${batchData.batch_id} | batch_status=${batchData.batch_status} | technical_status=${batchData.technical_status} | result_ready=${batchData.result_ready}`,
    ...historyEntries.map((entry) => entry.text),
    ...activeEntries,
    ...queuedEntries,
  ];

  return lines.join("\n");
}



function buildBatchRecordsTable(batchData) {
  if (!batchData || !Array.isArray(batchData.records) || batchData.records.length === 0) {
    return '<div class="empty-state">Nenhum lote carregado ainda.</div>';
  }

  const summaryEntries = Object.entries(batchData.summary || {})
    .map(([key, value]) => `<span class="summary-chip"><strong>${escapeHtml(key)}</strong>: ${escapeHtml(value)}</span>`)
    .join("");

  const rows = batchData.records
    .map((record) => {
      const lastAttempt = Array.isArray(record.call_attempts) && record.call_attempts.length > 0
        ? record.call_attempts[record.call_attempts.length - 1]
        : null;

      return `
        <tr>
          <td>${escapeHtml(record.external_id)}</td>
          <td>${escapeHtml(record.client_name)}</td>
          <td>${escapeHtml(record.phone_normalized || record.phone_original)}</td>
          <td>${escapeHtml((lastAttempt && lastAttempt.phone_source) || "-")}</td>
          <td>${escapeHtml(record.call_status)}</td>
          <td>${escapeHtml(record.call_result)}</td>
          <td>${escapeHtml(record.business_status)}</td>
          <td>${escapeHtml(record.final_status)}</td>
          <td>${escapeHtml((record.call_attempts ? record.call_attempts.length : 0))}</td>
        </tr>
      `;
    })
    .join("");

  return `
    <div class="batch-summary">${summaryEntries}</div>
    <table class="batch-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Empresa</th>
          <th>Telefone</th>
          <th>Origem do telefone</th>
          <th>Status da ligacao</th>
          <th>Resultado</th>
          <th>Status de negocio</th>
          <th>Status final</th>
          <th>Tentativas</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
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
      const summary = ((lastAttempt && lastAttempt.transcript_summary) || record.transcript_summary || "");

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

async function requestFormData(url, formData) {
  const response = await fetch(url, {
    method: "POST",
    body: formData,
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



async function downloadBatchResultsFile() {
  if (!liveBatchId) {
    return;
  }

  const downloadUrl = `/test/voice-call/batch/${encodeURIComponent(liveBatchId)}/results.xlsx`;
  if (downloadBatchResultsButton) {
    downloadBatchResultsButton.disabled = true;
  }

  try {
    const response = await fetch(downloadUrl, { method: "GET" });
    if (!response.ok) {
      const text = await response.text();
      let errorBody = { raw_text: text };
      try {
        errorBody = text ? JSON.parse(text) : {};
      } catch (_error) {
        // noop
      }
      responsePreview.textContent = prettyJson({
        status: response.status,
        body: errorBody,
      });
      return;
    }

    const blob = await response.blob();
    const objectUrl = window.URL.createObjectURL(blob);
    const downloadLink = document.createElement("a");
    downloadLink.href = objectUrl;
    downloadLink.download = `${liveBatchId}_resultado_validacao.xlsx`;
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
    window.URL.revokeObjectURL(objectUrl);

    responsePreview.textContent = prettyJson({
      status: response.status,
      body: {
        detail: "Planilha de retorno gerada a partir do response atual do lote de teste.",
        batch_id: liveBatchId,
      },
    });
  } finally {
    updateBatchControls();
  }
}

async function loadState() {
  const { data } = await requestJson("/test/state", { method: "GET" });

  requestsCount.textContent = String((data.recent_requests ? data.recent_requests.length : 0));
  sendsCount.textContent = String((data.recent_whatsapp_sends ? data.recent_whatsapp_sends.length : 0));
  logsCount.textContent = String((data.logs ? data.logs.length : 0));
  webhookStatus.textContent = ((data.last_webhook_event && data.last_webhook_event.event_type) || "Nenhum");

  requestsPreview.textContent = prettyJson(data.recent_requests || []);
  logsPreview.textContent = prettyJson(data.logs || []);
  sendsPreview.textContent = prettyJson(data.recent_whatsapp_sends || []);
  webhookPreview.textContent = prettyJson(data.last_webhook_payload || {});
}

function updateBatchControls(batchData = null) {
  const hasLiveBatch = Boolean(liveBatchId);
  const batchFinished = Boolean(batchData && batchData.result_ready === true);

  if (stopRealBatchCallButton) {
    stopRealBatchCallButton.disabled = !hasLiveBatch || batchFinished;
  }

  if (downloadBatchResultsButton) {
    downloadBatchResultsButton.disabled = !hasLiveBatch;
  }
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
    batchRecordsPreview.innerHTML = '<div class="empty-state">Nenhum lote carregado ainda.</div>';
    batchCallLogPreview.textContent = "Nenhum lote carregado ainda.";
    updateBatchControls();
    return;
  }

  const result = await requestJson(`/validations/${liveBatchId}`, { method: "GET" });
  liveBatchPreview.textContent = prettyJson({
    batch_id: liveBatchId,
    status: result.status,
    body: result.data,
  });
  transcriptPreview.textContent = prettyJson(buildTranscriptView(result.data));
  batchRecordsPreview.innerHTML = buildBatchRecordsTable(result.data);
  batchCallLogPreview.textContent = buildBatchCallLog(result.data);
  updateBatchControls(result.data);

  if (result.ok && result.data.result_ready === true) {
    stopAutoRefresh();
  }
}

async function startVoiceCall(twimlMode) {
  const payload = readFormPayload();
  const realtimeProfile = readRealtimeProfile();
  payloadPreview.textContent = prettyJson({ ...payload, twiml_mode: twimlMode, ...realtimeProfile });

  const realtimeQuery = buildRealtimeQueryString();
  const result = await requestJson(`/test/voice-call/start?twiml_mode=${encodeURIComponent(twimlMode)}${realtimeQuery ? `&${realtimeQuery}` : ""}`, {
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

batchValidationForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const fileInput = document.getElementById("batch_file");
  const file = (fileInput.files && fileInput.files[0]);
  if (!file) {
    responsePreview.textContent = prettyJson({
      status: 400,
      body: { detail: "Selecione uma planilha .xlsx ou .csv para iniciar o lote." },
    });
    return;
  }

  const realtimeProfile = readRealtimeProfile();
  payloadPreview.textContent = prettyJson({
    filename: file.name,
    size_bytes: file.size,
    mode: "batch_real_voice_call",
    skip_registry_validation: true,
    ...realtimeProfile,
  });

  const formData = new FormData();
  formData.append("file", file);

  startRealBatchCallButton.disabled = true;
  try {
    const realtimeQuery = buildRealtimeQueryString();
    const result = await requestFormData(`/test/voice-call/batch/start?skip_registry_validation=true${realtimeQuery ? `&${realtimeQuery}` : ""}`, formData);
    responsePreview.textContent = prettyJson({
      status: result.status,
      body: result.data,
    });

    if (result.ok && result.data.batch_id) {
      liveBatchId = result.data.batch_id;
      updateBatchControls(result.data);
      startAutoRefresh();
    }

    await loadLiveBatch();
  } finally {
    startRealBatchCallButton.disabled = false;
  }
});

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

if (downloadBatchResultsButton) {
  downloadBatchResultsButton.addEventListener("click", async () => {
    await downloadBatchResultsFile();
  });
}

if (stopRealBatchCallButton) {
  stopRealBatchCallButton.addEventListener("click", async () => {
    if (!liveBatchId) {
      return;
    }

    stopRealBatchCallButton.disabled = true;
    const result = await requestJson(`/test/voice-call/batch/${encodeURIComponent(liveBatchId)}/stop`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    responsePreview.textContent = prettyJson({
      status: result.status,
      body: result.data,
    });

    await loadLiveBatch();
    await loadState();
  });
}

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
  updateBatchControls();

  await loadState();
  await loadLiveBatch();
});

async function refreshDashboards() {
  await loadState();
  await loadLiveBatch();
}

refreshDashboards();
