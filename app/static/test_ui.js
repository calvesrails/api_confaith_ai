const validationForm = document.getElementById("validation-form");
    const batchValidationForm = document.getElementById("batch-validation-form");
    const supplierDiscoveryForm = document.getElementById("supplier-discovery-form");
    const sendWhatsAppButton = document.getElementById("send-whatsapp");
    const clearLogsButton = document.getElementById("clear-logs");
    const startRealCallButton = document.getElementById("start-real-call");
    const startDiagnosticCallButton = document.getElementById("start-diagnostic-call");
    const startRealBatchCallButton = document.getElementById("start-real-batch-call");
    const stopRealBatchCallButton = document.getElementById("stop-real-batch-call");
    const downloadBatchResultsButton = document.getElementById("download-batch-results");
    const startSupplierDiscoveryButton = document.getElementById("start-supplier-discovery");
    const downloadSupplierDiscoveryResultsButton = document.getElementById("download-supplier-discovery-results");
    const batchCallerCompanyNameInput = document.getElementById("batch_caller_company_name");
    const batchWorkflowKindSelect = document.getElementById("batch_workflow_kind");
    const supplierSegmentNameInput = document.getElementById("supplier_segment_name");
    const supplierCallbackPhoneInput = document.getElementById("supplier_callback_phone");
    const supplierCallbackContactNameInput = document.getElementById("supplier_callback_contact_name");
    const supplierSegmentNameWrapper = document.getElementById("supplier_segment_name_wrapper");
    const supplierCallbackPhoneWrapper = document.getElementById("supplier_callback_phone_wrapper");
    const supplierCallbackContactNameWrapper = document.getElementById("supplier_callback_contact_name_wrapper");
    const batchWorkflowHelp = document.getElementById("batch_workflow_help");

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
    const supplierDiscoveryResultsPreview = document.getElementById("supplier-discovery-results-preview");

    const requestsCount = document.getElementById("requests-count");
    const sendsCount = document.getElementById("sends-count");
    const logsCount = document.getElementById("logs-count");
    const webhookStatus = document.getElementById("webhook-status");

    let liveBatchId = null;
    let liveBatchWorkflowKind = "cadastral_validation";
    let liveSupplierDiscoveryId = null;
    let refreshIntervalId = null;

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

    function getSelectedBatchWorkflowKind() {
      return (batchWorkflowKindSelect && batchWorkflowKindSelect.value) || "cadastral_validation";
    }

    function isSupplierBatchWorkflow() {
      return getSelectedBatchWorkflowKind() === "supplier_validation";
    }

    function updateBatchWorkflowUi() {
      const supplierMode = isSupplierBatchWorkflow();
      if (supplierSegmentNameWrapper) supplierSegmentNameWrapper.hidden = !supplierMode;
      if (supplierCallbackPhoneWrapper) supplierCallbackPhoneWrapper.hidden = !supplierMode;
      if (supplierCallbackContactNameWrapper) supplierCallbackContactNameWrapper.hidden = !supplierMode;
      if (supplierSegmentNameInput) supplierSegmentNameInput.required = supplierMode;
      if (supplierCallbackPhoneInput) supplierCallbackPhoneInput.required = supplierMode;
      if (batchWorkflowHelp) {
        batchWorkflowHelp.textContent = supplierMode
          ? "No lote de fornecedor com ligacao, a planilha deve ter nome do fornecedor e telefone. Informe tambem o segmento e o telefone de retorno comercial."
          : "No lote cadastral, a planilha precisa de nome do cliente, CNPJ e telefone. O modo de homologacao ignora a consulta inicial da base oficial.";
      }
      if (startRealBatchCallButton) {
        startRealBatchCallButton.textContent = supplierMode ? "Validar fornecedores da planilha" : "Iniciar lote real";
      }
      if (!liveBatchId) {
        liveBatchWorkflowKind = getSelectedBatchWorkflowKind();
      }
    }

    function readRealtimeProfile() {
      const realtimeModelField = document.getElementById("realtime_model");
      const model = realtimeModelField ? realtimeModelField.value : null;
      const realtimeVoiceField = document.getElementById("realtime_voice");
      const voice = realtimeVoiceField ? realtimeVoiceField.value : null;
      const realtimeOutputSpeedField = document.getElementById("realtime_output_speed");
      const outputSpeedRaw = realtimeOutputSpeedField ? realtimeOutputSpeedField.value : null;
      const realtimeStyleProfileField = document.getElementById("realtime_style_profile");
      const styleProfile = realtimeStyleProfileField ? realtimeStyleProfileField.value : null;

      return {
        realtime_model: model || null,
        realtime_voice: voice || null,
        realtime_output_speed: outputSpeedRaw === "" || outputSpeedRaw == null ? null : Number(outputSpeedRaw),
        realtime_style_profile: styleProfile || null,
      };
    }

    function buildRealtimeQueryString() {
      const realtimeProfile = readRealtimeProfile();
      const params = new URLSearchParams();
      if (realtimeProfile.realtime_model) params.set("realtime_model", realtimeProfile.realtime_model);
      if (realtimeProfile.realtime_voice) params.set("realtime_voice", realtimeProfile.realtime_voice);
      if (realtimeProfile.realtime_output_speed != null && !Number.isNaN(realtimeProfile.realtime_output_speed)) {
        params.set("realtime_output_speed", String(realtimeProfile.realtime_output_speed));
      }
      if (realtimeProfile.realtime_style_profile) params.set("realtime_style_profile", realtimeProfile.realtime_style_profile);
      return params.toString();
    }

    function getBatchDetailsEndpoint() {
      if (!liveBatchId) return null;
      const prefix = liveBatchWorkflowKind === "supplier_validation" ? "/supplier-validations" : "/validations";
      return `${prefix}/${encodeURIComponent(liveBatchId)}`;
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

    function buildTranscriptView(batchData) {
      if (!batchData || !Array.isArray(batchData.records) || batchData.records.length === 0) {
        return { status: "Nenhuma transcricao disponivel ainda." };
      }

      const transcripts = batchData.records
        .map((record) => {
          const lastAttempt = Array.isArray(record.call_attempts) ? record.call_attempts[record.call_attempts.length - 1] : null;
          const summary = ((lastAttempt && lastAttempt.transcript_summary) || record.transcript_summary || "");
          if (!summary) return null;

          const view = {
            external_id: record.external_id,
            call_result: record.call_result,
            business_status: record.business_status,
            raw: summary,
          };

          for (const segment of summary.split(" | ")) {
            if (segment.startsWith("cliente:")) view.cliente = segment.slice("cliente:".length).trim();
            if (segment.startsWith("agente:")) view.agente = segment.slice("agente:".length).trim();
          }
          return view;
        })
        .filter(Boolean);

      return transcripts.length === 0 ? { status: "Nenhuma transcricao disponivel ainda." } : transcripts;
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
            activeEntries.push(`[em andamento] | ${baseLabel} | status=${attempt.status} | resultado=${attempt.result} | origem=${source} | provider_call_id=${providerCallId}`);
            continue;
          }

          if (attempt.status === "queued" || attempt.result === "pending_dispatch") {
            queuedEntries.push(`[na fila] | ${baseLabel} | status=${attempt.status} | resultado=${attempt.result} | origem=${source}`);
          }
        }
      }

      historyEntries.sort((left, right) => {
        const leftTs = new Date(left.timestamp).getTime();
        const rightTs = new Date(right.timestamp).getTime();
        if (leftTs === rightTs) return left.order - right.order;
        return leftTs - rightTs;
      });

      return [
        `lote ${batchData.batch_id} | batch_status=${batchData.batch_status} | technical_status=${batchData.technical_status} | result_ready=${batchData.result_ready}`,
        ...historyEntries.map((entry) => entry.text),
        ...activeEntries,
        ...queuedEntries,
      ].join("\n");
    }

    function buildBatchRecordsTable(batchData) {
      if (!batchData || !Array.isArray(batchData.records) || batchData.records.length === 0) {
        return '<div class="empty-state">Nenhum lote carregado ainda.</div>';
      }

      const isSupplierBatch = batchData.workflow_kind === "supplier_validation";
      const summaryEntries = Object.entries(batchData.summary || {})
        .map(([key, value]) => `<span class="summary-chip"><strong>${escapeHtml(key)}</strong>: ${escapeHtml(value)}</span>`)
        .join("");

      const rows = batchData.records
        .map((record) => {
          const lastAttempt = Array.isArray(record.call_attempts) && record.call_attempts.length > 0
            ? record.call_attempts[record.call_attempts.length - 1]
            : null;
          const supplierValidation = record.supplier_validation || {};

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
              ${isSupplierBatch ? `<td>${escapeHtml(supplierValidation.segment_name || batchData.segment_name || "-")}</td>` : ""}
              ${isSupplierBatch ? `<td>${escapeHtml(supplierValidation.phone_belongs_to_company == null ? "-" : String(supplierValidation.phone_belongs_to_company))}</td>` : ""}
              ${isSupplierBatch ? `<td>${escapeHtml(supplierValidation.supplies_segment == null ? "-" : String(supplierValidation.supplies_segment))}</td>` : ""}
              ${isSupplierBatch ? `<td>${escapeHtml(supplierValidation.commercial_interest == null ? "-" : String(supplierValidation.commercial_interest))}</td>` : ""}
              ${isSupplierBatch ? `<td>${escapeHtml(supplierValidation.outcome || "-")}</td>` : ""}
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
              <th>${isSupplierBatch ? "Fornecedor" : "Empresa"}</th>
              <th>Telefone</th>
              <th>Origem do telefone</th>
              <th>Status da ligacao</th>
              <th>Resultado</th>
              <th>Status de negocio</th>
              <th>Status final</th>
              <th>Tentativas</th>
              ${isSupplierBatch ? '<th>Segmento</th><th>Telefone pertence</th><th>Fornece segmento</th><th>Interesse comercial</th><th>Outcome fornecedor</th>' : ''}
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function buildSupplierDiscoveryTable(searchResult) {
      if (!searchResult || !Array.isArray(searchResult.suppliers) || searchResult.suppliers.length === 0) {
        return '<div class="empty-state">Nenhum fornecedor encontrado ainda.</div>';
      }

      const chips = [
        `<span class="summary-chip"><strong>modo</strong>: ${escapeHtml(searchResult.mode)}</span>`,
        `<span class="summary-chip"><strong>segmento</strong>: ${escapeHtml(searchResult.segment_name)}</span>`,
        `<span class="summary-chip"><strong>regiao</strong>: ${escapeHtml(searchResult.region || "Brasil")}</span>`,
        `<span class="summary-chip"><strong>fornecedores</strong>: ${escapeHtml(searchResult.total_suppliers)}</span>`,
      ].join("");

      const rows = searchResult.suppliers.map((supplier, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${escapeHtml(supplier.supplier_name)}</td>
          <td>${escapeHtml(supplier.phone || "-")}</td>
          <td>${escapeHtml(supplier.website || "-")}</td>
          <td>${escapeHtml([supplier.city, supplier.state].filter(Boolean).join("/") || "-")}</td>
          <td>${escapeHtml(String(supplier.discovery_confidence == null ? "-" : supplier.discovery_confidence))}</td>
          <td>${escapeHtml((supplier.source_urls || []).join(" | ") || "-")}</td>
          <td>${escapeHtml(supplier.notes || "-")}</td>
        </tr>
      `).join("");

      const message = searchResult.message ? `<p class="section-hint">${escapeHtml(searchResult.message)}</p>` : "";
      return `
        <div class="batch-summary">${chips}</div>
        ${message}
        <table class="batch-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Fornecedor</th>
              <th>Telefone</th>
              <th>Site</th>
              <th>Cidade / UF</th>
              <th>Confianca</th>
              <th>Fontes</th>
              <th>Observacao</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function updateBatchControls(batchData = null) {
      const hasLiveBatch = Boolean(liveBatchId);
      const batchFinished = Boolean(batchData && batchData.result_ready === true);
      if (stopRealBatchCallButton) stopRealBatchCallButton.disabled = !hasLiveBatch || batchFinished;
      if (downloadBatchResultsButton) downloadBatchResultsButton.disabled = !hasLiveBatch;
    }

    function updateSupplierDiscoveryControls() {
      if (downloadSupplierDiscoveryResultsButton) {
        downloadSupplierDiscoveryResultsButton.disabled = !liveSupplierDiscoveryId;
      }
    }

    function stopAutoRefresh() {
      if (refreshIntervalId !== null) {
        window.clearInterval(refreshIntervalId);
        refreshIntervalId = null;
      }
    }

    function startAutoRefresh() {
      if (refreshIntervalId !== null || !liveBatchId) return;
      refreshIntervalId = window.setInterval(async () => {
        await refreshDashboards();
      }, 3000);
    }

    async function loadState() {
      const { data } = await requestJson("/test/state", { method: "GET" });
      if (requestsCount) requestsCount.textContent = String((data.recent_requests ? data.recent_requests.length : 0));
      if (sendsCount) sendsCount.textContent = String((data.recent_whatsapp_sends ? data.recent_whatsapp_sends.length : 0));
      if (logsCount) logsCount.textContent = String((data.logs ? data.logs.length : 0));
      if (webhookStatus) webhookStatus.textContent = ((data.last_webhook_event && data.last_webhook_event.event_type) || "Nenhum");
      if (requestsPreview) requestsPreview.textContent = prettyJson(data.recent_requests || []);
      if (logsPreview) logsPreview.textContent = prettyJson(data.logs || []);
      if (sendsPreview) sendsPreview.textContent = prettyJson(data.recent_whatsapp_sends || []);
      if (webhookPreview) webhookPreview.textContent = prettyJson(data.last_webhook_payload || {});
    }

    async function loadLiveBatch() {
      if (!liveBatchId) {
        if (liveBatchPreview) liveBatchPreview.textContent = "{}";
        if (transcriptPreview) transcriptPreview.textContent = "{}";
        if (batchRecordsPreview) batchRecordsPreview.innerHTML = '<div class="empty-state">Nenhum lote carregado ainda.</div>';
        if (batchCallLogPreview) batchCallLogPreview.textContent = "Nenhum lote carregado ainda.";
        updateBatchControls();
        return;
      }

      const batchDetailsEndpoint = getBatchDetailsEndpoint();
      const result = await requestJson(batchDetailsEndpoint, { method: "GET" });
      if (result.ok && result.data.workflow_kind) {
        liveBatchWorkflowKind = result.data.workflow_kind;
      }

      if (liveBatchPreview) {
        liveBatchPreview.textContent = prettyJson({
          batch_id: liveBatchId,
          workflow_kind: liveBatchWorkflowKind,
          status: result.status,
          body: result.data,
        });
      }
      if (transcriptPreview) transcriptPreview.textContent = prettyJson(buildTranscriptView(result.data));
      if (batchRecordsPreview) batchRecordsPreview.innerHTML = buildBatchRecordsTable(result.data);
      if (batchCallLogPreview) batchCallLogPreview.textContent = buildBatchCallLog(result.data);
      updateBatchControls(result.data);

      if (result.ok && result.data.result_ready === true) {
        stopAutoRefresh();
      }
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

    async function downloadBatchResultsFile() {
      if (!liveBatchId) return;
      const downloadUrl = `/test/voice-call/batch/${encodeURIComponent(liveBatchId)}/results.xlsx`;
      if (downloadBatchResultsButton) downloadBatchResultsButton.disabled = true;
      try {
        const response = await fetch(downloadUrl, { method: "GET" });
        if (!response.ok) {
          const text = await response.text();
          let errorBody = { raw_text: text };
          try { errorBody = text ? JSON.parse(text) : {}; } catch (_error) {}
          responsePreview.textContent = prettyJson({ status: response.status, body: errorBody });
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
          body: { detail: "Planilha de retorno gerada a partir do response atual do lote de teste.", batch_id: liveBatchId },
        });
      } finally {
        updateBatchControls();
      }
    }

    async function downloadSupplierDiscoveryFile() {
      if (!liveSupplierDiscoveryId) return;
      const downloadUrl = `/test/supplier-discovery/${encodeURIComponent(liveSupplierDiscoveryId)}/results.xlsx`;
      if (downloadSupplierDiscoveryResultsButton) downloadSupplierDiscoveryResultsButton.disabled = true;
      try {
        const response = await fetch(downloadUrl, { method: "GET" });
        if (!response.ok) {
          const text = await response.text();
          let errorBody = { raw_text: text };
          try { errorBody = text ? JSON.parse(text) : {}; } catch (_error) {}
          responsePreview.textContent = prettyJson({ status: response.status, body: errorBody });
          return;
        }

        const blob = await response.blob();
        const objectUrl = window.URL.createObjectURL(blob);
        const downloadLink = document.createElement("a");
        downloadLink.href = objectUrl;
        downloadLink.download = `${liveSupplierDiscoveryId}_fornecedores_encontrados.xlsx`;
        document.body.appendChild(downloadLink);
        downloadLink.click();
        downloadLink.remove();
        window.URL.revokeObjectURL(objectUrl);
        responsePreview.textContent = prettyJson({
          status: response.status,
          body: { detail: "Planilha da busca de fornecedores gerada com sucesso.", search_id: liveSupplierDiscoveryId },
        });
      } finally {
        updateSupplierDiscoveryControls();
      }
    }

    async function startVoiceCall(twimlMode) {
      const payload = readFormPayload();
      const realtimeProfile = readRealtimeProfile();
      if (payloadPreview) payloadPreview.textContent = prettyJson({ ...payload, twiml_mode: twimlMode, ...realtimeProfile });
      const realtimeQuery = buildRealtimeQueryString();
      const result = await requestJson(`/test/voice-call/start?twiml_mode=${encodeURIComponent(twimlMode)}${realtimeQuery ? `&${realtimeQuery}` : ""}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
      if (result.ok && result.data.batch_id) {
        liveBatchId = result.data.batch_id;
        startAutoRefresh();
      }
      await loadLiveBatch();
    }

    if (supplierDiscoveryForm) {
      supplierDiscoveryForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = {
          segment_name: (((document.getElementById("supplier_discovery_segment_name") || {}).value) || "").trim(),
          region: ((((document.getElementById("supplier_discovery_region") || {}).value) || "").trim()) || null,
          callback_phone: ((((document.getElementById("supplier_discovery_callback_phone") || {}).value) || "").trim()) || null,
          callback_contact_name: ((((document.getElementById("supplier_discovery_callback_contact_name") || {}).value) || "").trim()) || null,
          max_suppliers: Number((((document.getElementById("supplier_discovery_max_suppliers") || {}).value) || 10)),
        };

        if (!payload.segment_name) {
          if (responsePreview) responsePreview.textContent = prettyJson({ status: 400, body: { detail: "Informe o segmento para pesquisar fornecedores." } });
          return;
        }

        if (payloadPreview) payloadPreview.textContent = prettyJson(payload);
        if (startSupplierDiscoveryButton) startSupplierDiscoveryButton.disabled = true;
        try {
          const result = await requestJson("/test/supplier-discovery/search", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
          if (result.ok && result.data.search_id) {
            liveSupplierDiscoveryId = result.data.search_id;
            if (supplierDiscoveryResultsPreview) supplierDiscoveryResultsPreview.innerHTML = buildSupplierDiscoveryTable(result.data);
            updateSupplierDiscoveryControls();
          }
          await loadState();
        } finally {
          if (startSupplierDiscoveryButton) startSupplierDiscoveryButton.disabled = false;
        }
      });
    }

    if (batchValidationForm) {
      batchValidationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const fileInput = document.getElementById("batch_file");
        const file = fileInput && fileInput.files ? fileInput.files[0] : null;
        if (!file) {
          if (responsePreview) responsePreview.textContent = prettyJson({ status: 400, body: { detail: "Selecione uma planilha .xlsx ou .csv para iniciar o lote." } });
          return;
        }

        const workflowKind = getSelectedBatchWorkflowKind();
        const supplierMode = workflowKind === "supplier_validation";
        const callerCompanyName = batchCallerCompanyNameInput ? batchCallerCompanyNameInput.value.trim() : "";
        const segmentName = supplierSegmentNameInput ? supplierSegmentNameInput.value.trim() : "";
        const callbackPhone = supplierCallbackPhoneInput ? supplierCallbackPhoneInput.value.trim() : "";
        const callbackContactName = supplierCallbackContactNameInput ? supplierCallbackContactNameInput.value.trim() : "";

        if (supplierMode && (!segmentName || !callbackPhone)) {
          if (responsePreview) responsePreview.textContent = prettyJson({ status: 400, body: { detail: "Informe o segmento e o telefone de retorno comercial para o lote de fornecedor." } });
          return;
        }

        const realtimeProfile = readRealtimeProfile();
        if (payloadPreview) {
          payloadPreview.textContent = prettyJson({
            filename: file.name,
            size_bytes: file.size,
            workflow_kind: workflowKind,
            caller_company_name: callerCompanyName || null,
            skip_registry_validation: !supplierMode,
            segment_name: supplierMode ? segmentName : null,
            callback_phone: supplierMode ? callbackPhone : null,
            callback_contact_name: supplierMode ? callbackContactName || null : null,
            ...realtimeProfile,
          });
        }

        const formData = new FormData();
        formData.append("file", file);
        const params = new URLSearchParams();
        if (callerCompanyName) params.set("caller_company_name", callerCompanyName);
        if (supplierMode) {
          params.set("segment_name", segmentName);
          params.set("callback_phone", callbackPhone);
          if (callbackContactName) params.set("callback_contact_name", callbackContactName);
        } else {
          params.set("skip_registry_validation", "true");
        }

        const realtimeQuery = buildRealtimeQueryString();
        if (realtimeQuery) {
          for (const [key, value] of new URLSearchParams(realtimeQuery).entries()) {
            params.set(key, value);
          }
        }

        const endpoint = supplierMode
          ? `/test/voice-call/supplier-batch/start?${params.toString()}`
          : `/test/voice-call/batch/start?${params.toString()}`;

        if (startRealBatchCallButton) startRealBatchCallButton.disabled = true;
        try {
          const result = await requestFormData(endpoint, formData);
          if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
          if (result.ok && result.data.batch_id) {
            liveBatchId = result.data.batch_id;
            liveBatchWorkflowKind = result.data.workflow_kind || workflowKind;
            updateBatchControls(result.data);
            startAutoRefresh();
          }
          await loadLiveBatch();
          await loadState();
        } finally {
          if (startRealBatchCallButton) startRealBatchCallButton.disabled = false;
        }
      });
    }

    if (validationForm) {
      validationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = readFormPayload();
        if (payloadPreview) payloadPreview.textContent = prettyJson(payload);
        const result = await requestJson("/test/validate", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
        await loadState();
      });
    }

    if (startRealCallButton) {
      startRealCallButton.addEventListener("click", async () => {
        await startVoiceCall("media_stream");
      });
    }

    if (startDiagnosticCallButton) {
      startDiagnosticCallButton.addEventListener("click", async () => {
        await startVoiceCall("diagnostic_say");
      });
    }

    if (sendWhatsAppButton) {
      sendWhatsAppButton.addEventListener("click", async () => {
        const payload = {
          phone: ((document.getElementById("phone") || {}).value),
          message: ((document.getElementById("fallback_message") || {}).value),
        };
        if (payloadPreview) payloadPreview.textContent = prettyJson(payload);
        const result = await requestJson("/test/whatsapp/send", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
        await loadState();
      });
    }

    if (downloadBatchResultsButton) {
      downloadBatchResultsButton.addEventListener("click", async () => {
        await downloadBatchResultsFile();
      });
    }

    if (downloadSupplierDiscoveryResultsButton) {
      downloadSupplierDiscoveryResultsButton.addEventListener("click", async () => {
        await downloadSupplierDiscoveryFile();
      });
    }

    if (stopRealBatchCallButton) {
      stopRealBatchCallButton.addEventListener("click", async () => {
        if (!liveBatchId) return;
        stopRealBatchCallButton.disabled = true;
        const result = await requestJson(`/test/voice-call/batch/${encodeURIComponent(liveBatchId)}/stop`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
        await loadLiveBatch();
        await loadState();
      });
    }

    if (clearLogsButton) {
      clearLogsButton.addEventListener("click", async () => {
        const result = await requestJson("/test/logs/clear", {
          method: "POST",
          body: JSON.stringify({}),
        });
        if (responsePreview) responsePreview.textContent = prettyJson({ status: result.status, body: result.data });
        if (payloadPreview) payloadPreview.textContent = "{}";
        liveBatchId = null;
        liveBatchWorkflowKind = getSelectedBatchWorkflowKind();
        liveSupplierDiscoveryId = null;
        stopAutoRefresh();
        updateBatchControls();
        updateSupplierDiscoveryControls();
        if (supplierDiscoveryResultsPreview) supplierDiscoveryResultsPreview.innerHTML = '<div class="empty-state">Nenhuma busca executada ainda.</div>';
        await loadState();
        await loadLiveBatch();
      });
    }

    async function refreshDashboards() {
      await loadState();
      await loadLiveBatch();
    }

    if (batchWorkflowKindSelect) {
      batchWorkflowKindSelect.addEventListener("change", updateBatchWorkflowUi);
    }

    updateBatchWorkflowUi();
    updateSupplierDiscoveryControls();
    refreshDashboards();
