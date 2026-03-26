const storageKey = "platform_api_ui_state_v1";

const stateInputs = {
  adminKey: document.getElementById("platform_admin_key"),
  accountId: document.getElementById("account_id"),
  bearerToken: document.getElementById("bearer_token"),
  batchId: document.getElementById("current_batch_id"),
};

const forms = {
  createAccount: document.getElementById("create-account-form"),
  companyProfile: document.getElementById("company-profile-form"),
  twilio: document.getElementById("twilio-form"),
  openai: document.getElementById("openai-form"),
  email: document.getElementById("email-form"),
  token: document.getElementById("token-form"),
  batch: document.getElementById("batch-form"),
};

const buttons = {
  saveSession: document.getElementById("save-session"),
  clearSession: document.getElementById("clear-session"),
  checkHealth: document.getElementById("check-health"),
  fetchAccount: document.getElementById("fetch-account"),
  loadTwilioSample: document.getElementById("load-twilio-sample"),
  loadBatchSample: document.getElementById("load-batch-sample"),
  fetchBatch: document.getElementById("fetch-batch"),
  dispatchBatch: document.getElementById("dispatch-batch"),
};

const previews = {
  lastRequest: document.getElementById("last-request-preview"),
  lastResponse: document.getElementById("last-response-preview"),
  account: document.getElementById("account-preview"),
  batch: document.getElementById("batch-preview"),
  log: document.getElementById("event-log-preview"),
};

const twilioPhoneNumbersTextarea = document.getElementById("twilio_phone_numbers");
const batchRecordsTextarea = document.getElementById("batch_records_json");

const eventLog = [];

function nowIso() {
  return new Date().toISOString();
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function appendLog(stage, message, data = null) {
  eventLog.unshift({ timestamp: nowIso(), stage, message, data });
  previews.log.textContent = prettyJson(eventLog.slice(0, 60));
}

function setPreview(element, value) {
  element.textContent = prettyJson(value);
}

function loadState() {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return;
    }
    const value = JSON.parse(raw);
    stateInputs.adminKey.value = value.adminKey || "";
    stateInputs.accountId.value = value.accountId || "";
    stateInputs.bearerToken.value = value.bearerToken || "";
    stateInputs.batchId.value = value.batchId || "";
  } catch (error) {
    appendLog("state", "Falha ao carregar sessao local.", { error: String(error) });
  }
}

function persistState() {
  const state = {
    adminKey: stateInputs.adminKey.value.trim(),
    accountId: stateInputs.accountId.value.trim(),
    bearerToken: stateInputs.bearerToken.value.trim(),
    batchId: stateInputs.batchId.value.trim(),
  };
  window.localStorage.setItem(storageKey, JSON.stringify(state));
  appendLog("state", "Sessao local salva.", state);
}

function clearState() {
  window.localStorage.removeItem(storageKey);
  Object.values(stateInputs).forEach((input) => {
    input.value = "";
  });
  appendLog("state", "Sessao local limpa.");
}

function getAccountId() {
  const raw = stateInputs.accountId.value.trim();
  if (!raw) {
    throw new Error("Informe ou gere um account_id antes de continuar.");
  }
  return Number(raw);
}

function getBatchId() {
  const raw = stateInputs.batchId.value.trim();
  if (!raw) {
    throw new Error("Informe ou gere um batch_id antes de consultar o lote.");
  }
  return raw;
}

function buildAdminHeaders() {
  const adminKey = stateInputs.adminKey.value.trim();
  if (!adminKey) {
    throw new Error("Preencha a chave administrativa da plataforma.");
  }
  return { "X-Platform-Admin-Key": adminKey };
}

function buildBearerHeaders() {
  const token = stateInputs.bearerToken.value.trim();
  if (!token) {
    throw new Error("Preencha o bearer token da conta.");
  }
  return { Authorization: `Bearer ${token}` };
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
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

function parseJsonTextarea(textarea, label) {
  try {
    return JSON.parse(textarea.value);
  } catch (error) {
    throw new Error(`JSON invalido em ${label}: ${error.message}`);
  }
}

function syncStateFromAccount(accountResponse) {
  if (!accountResponse) {
    return;
  }
  if (accountResponse.id) {
    stateInputs.accountId.value = String(accountResponse.id);
  }
  if (accountResponse.company_name) {
    forms.createAccount.elements.company_name.value = accountResponse.company_name;
    forms.companyProfile.elements.company_name.value = accountResponse.company_name;
  }
  if (accountResponse.spoken_company_name != null) {
    forms.createAccount.elements.spoken_company_name.value = accountResponse.spoken_company_name || "";
    forms.companyProfile.elements.spoken_company_name.value = accountResponse.spoken_company_name || "";
  }
  if (accountResponse.owner_name != null) {
    forms.createAccount.elements.owner_name.value = accountResponse.owner_name || "";
    forms.companyProfile.elements.owner_name.value = accountResponse.owner_name || "";
  }
  if (accountResponse.owner_email != null) {
    forms.createAccount.elements.owner_email.value = accountResponse.owner_email || "";
    forms.companyProfile.elements.owner_email.value = accountResponse.owner_email || "";
  }
}

function handleResult(stage, requestPayload, result, outputPreview = null) {
  setPreview(previews.lastRequest, requestPayload);
  setPreview(previews.lastResponse, {
    status: result.status,
    ok: result.ok,
    data: result.data,
  });
  if (outputPreview) {
    setPreview(outputPreview, result.data);
  }
  appendLog(stage, `${stage} concluido com status HTTP ${result.status}.`, result.data);
}

function handleFailure(stage, error) {
  const detail = { error: error instanceof Error ? error.message : String(error) };
  setPreview(previews.lastResponse, detail);
  appendLog(stage, `${stage} falhou.`, detail);
  window.alert(detail.error);
}

async function checkHealth() {
  const requestPayload = { method: "GET", url: "/health" };
  try {
    const result = await requestJson("/health", { method: "GET" });
    handleResult("health", requestPayload, result);
  } catch (error) {
    handleFailure("health", error);
  }
}

async function createAccount(event) {
  event.preventDefault();
  const form = new FormData(forms.createAccount);
  const payload = {
    external_account_id: form.get("external_account_id") || null,
    company_name: form.get("company_name"),
    spoken_company_name: form.get("spoken_company_name") || null,
    owner_name: form.get("owner_name") || null,
    owner_email: form.get("owner_email") || null,
  };
  const requestPayload = { method: "POST", url: "/platform/accounts", payload };

  try {
    const result = await requestJson("/platform/accounts", {
      method: "POST",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("create_account", requestPayload, result, previews.account);
    if (result.ok) {
      syncStateFromAccount(result.data);
      persistState();
    }
  } catch (error) {
    handleFailure("create_account", error);
  }
}

async function fetchAccount() {
  const accountId = getAccountId();
  const requestPayload = { method: "GET", url: `/platform/accounts/${accountId}` };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}`, {
      method: "GET",
      headers: buildAdminHeaders(),
    });
    handleResult("fetch_account", requestPayload, result, previews.account);
    if (result.ok) {
      syncStateFromAccount(result.data);
      persistState();
    }
  } catch (error) {
    handleFailure("fetch_account", error);
  }
}

async function updateCompanyProfile(event) {
  event.preventDefault();
  const accountId = getAccountId();
  const form = new FormData(forms.companyProfile);
  const payload = {
    company_name: form.get("company_name"),
    spoken_company_name: form.get("spoken_company_name") || null,
    owner_name: form.get("owner_name") || null,
    owner_email: form.get("owner_email") || null,
  };
  const requestPayload = { method: "PUT", url: `/platform/accounts/${accountId}/company-profile`, payload };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}/company-profile`, {
      method: "PUT",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("company_profile", requestPayload, result, previews.account);
    if (result.ok) {
      syncStateFromAccount(result.data);
      persistState();
    }
  } catch (error) {
    handleFailure("company_profile", error);
  }
}

async function updateTwilio(event) {
  event.preventDefault();
  const accountId = getAccountId();
  const form = new FormData(forms.twilio);
  const payload = {
    account_sid: form.get("account_sid"),
    auth_token: form.get("auth_token"),
    webhook_base_url: form.get("webhook_base_url") || null,
    phone_numbers: parseJsonTextarea(twilioPhoneNumbersTextarea, "phone_numbers"),
  };
  const requestPayload = { method: "PUT", url: `/platform/accounts/${accountId}/providers/twilio`, payload };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}/providers/twilio`, {
      method: "PUT",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("twilio", requestPayload, result, previews.account);
  } catch (error) {
    handleFailure("twilio", error);
  }
}

async function updateOpenAI(event) {
  event.preventDefault();
  const accountId = getAccountId();
  const form = new FormData(forms.openai);
  const outputSpeedRaw = form.get("realtime_output_speed");
  const payload = {
    api_key: form.get("api_key"),
    realtime_model: form.get("realtime_model"),
    realtime_voice: form.get("realtime_voice"),
    realtime_output_speed: outputSpeedRaw === "" ? null : Number(outputSpeedRaw),
    realtime_style_instructions: form.get("realtime_style_instructions") || null,
  };
  const requestPayload = { method: "PUT", url: `/platform/accounts/${accountId}/providers/openai`, payload };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}/providers/openai`, {
      method: "PUT",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("openai", requestPayload, result, previews.account);
  } catch (error) {
    handleFailure("openai", error);
  }
}

async function updateEmail(event) {
  event.preventDefault();
  const accountId = getAccountId();
  const form = new FormData(forms.email);
  const portRaw = form.get("smtp_port");
  const payload = {
    enabled: forms.email.elements.enabled.checked,
    smtp_host: form.get("smtp_host") || null,
    smtp_port: portRaw === "" ? 587 : Number(portRaw),
    smtp_username: form.get("smtp_username") || null,
    smtp_password: form.get("smtp_password") || null,
    smtp_use_tls: forms.email.elements.smtp_use_tls.checked,
    from_address: form.get("from_address") || null,
    from_name: form.get("from_name") || null,
  };
  const requestPayload = { method: "PUT", url: `/platform/accounts/${accountId}/providers/email`, payload };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}/providers/email`, {
      method: "PUT",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("email", requestPayload, result, previews.account);
  } catch (error) {
    handleFailure("email", error);
  }
}

async function createApiToken(event) {
  event.preventDefault();
  const accountId = getAccountId();
  const form = new FormData(forms.token);
  const expiresAtRaw = form.get("expires_at");
  const payload = {
    name: form.get("name"),
    expires_at: expiresAtRaw ? new Date(expiresAtRaw).toISOString() : null,
  };
  const requestPayload = { method: "POST", url: `/platform/accounts/${accountId}/api-tokens`, payload };

  try {
    const result = await requestJson(`/platform/accounts/${accountId}/api-tokens`, {
      method: "POST",
      headers: buildAdminHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("api_token", requestPayload, result);
    if (result.ok && result.data.raw_token) {
      stateInputs.bearerToken.value = result.data.raw_token;
      persistState();
    }
  } catch (error) {
    handleFailure("api_token", error);
  }
}

async function submitBatch(event) {
  event.preventDefault();
  const form = new FormData(forms.batch);
  const payload = {
    batch_id: form.get("batch_id"),
    source: form.get("source"),
    records: parseJsonTextarea(batchRecordsTextarea, "records"),
  };
  const requestPayload = { method: "POST", url: "/validations", payload };

  try {
    const result = await requestJson("/validations", {
      method: "POST",
      headers: buildBearerHeaders(),
      body: JSON.stringify(payload),
    });
    handleResult("submit_batch", requestPayload, result, previews.batch);
    if (result.ok && result.data.batch_id) {
      stateInputs.batchId.value = result.data.batch_id;
      persistState();
    }
  } catch (error) {
    handleFailure("submit_batch", error);
  }
}

async function fetchBatch() {
  const batchId = getBatchId();
  const requestPayload = { method: "GET", url: `/validations/${batchId}` };

  try {
    const result = await requestJson(`/validations/${batchId}`, {
      method: "GET",
      headers: buildBearerHeaders(),
    });
    handleResult("fetch_batch", requestPayload, result, previews.batch);
  } catch (error) {
    handleFailure("fetch_batch", error);
  }
}

async function dispatchBatch() {
  const batchId = getBatchId();
  const requestPayload = { method: "POST", url: `/validations/${batchId}/dispatch?twiml_mode=media_stream` };

  try {
    const result = await requestJson(`/validations/${batchId}/dispatch?twiml_mode=media_stream`, {
      method: "POST",
      headers: buildBearerHeaders(),
    });
    handleResult("dispatch_batch", requestPayload, result, previews.batch);
  } catch (error) {
    handleFailure("dispatch_batch", error);
  }
}

function loadTwilioSample() {
  twilioPhoneNumbersTextarea.value = prettyJson([
    {
      phone_number: "13527176703",
      friendly_name: "Linha principal",
      is_active: true,
      max_concurrent_calls: 1,
    },
    {
      phone_number: "13527176704",
      friendly_name: "Linha secundaria",
      is_active: true,
      max_concurrent_calls: 1,
    },
  ]);
}

function loadBatchSample() {
  batchRecordsTextarea.value = prettyJson([
    {
      external_id: "1",
      client_name: "Fornecedor Alfa LTDA",
      cnpj: "11.222.333/0001-81",
      phone: "5519994110571",
      email: "contato@fornecedoralfa.com.br",
    },
    {
      external_id: "2",
      client_name: "Fornecedor Beta LTDA",
      cnpj: "22.333.444/0001-55",
      phone: "5511999990001",
      email: null,
    },
  ]);
}

function attachEvents() {
  buttons.saveSession.addEventListener("click", persistState);
  buttons.clearSession.addEventListener("click", clearState);
  buttons.checkHealth.addEventListener("click", checkHealth);
  buttons.fetchAccount.addEventListener("click", fetchAccount);
  buttons.loadTwilioSample.addEventListener("click", loadTwilioSample);
  buttons.loadBatchSample.addEventListener("click", loadBatchSample);
  buttons.fetchBatch.addEventListener("click", fetchBatch);
  buttons.dispatchBatch.addEventListener("click", dispatchBatch);

  forms.createAccount.addEventListener("submit", createAccount);
  forms.companyProfile.addEventListener("submit", updateCompanyProfile);
  forms.twilio.addEventListener("submit", updateTwilio);
  forms.openai.addEventListener("submit", updateOpenAI);
  forms.email.addEventListener("submit", updateEmail);
  forms.token.addEventListener("submit", createApiToken);
  forms.batch.addEventListener("submit", submitBatch);

  Object.values(stateInputs).forEach((input) => {
    input.addEventListener("change", persistState);
  });
}

function bootstrap() {
  loadState();
  loadTwilioSample();
  loadBatchSample();
  attachEvents();
  appendLog("bootstrap", "Tela de homologacao carregada.");
}

bootstrap();
