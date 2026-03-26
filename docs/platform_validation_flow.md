# API de Validacao

## Objetivo
Esta documentacao descreve a API do servico de validacao cadastral.

Ela cobre:
- endpoints de cadastro e configuracao da conta operacional
- endpoint de geracao de token da API
- endpoint de envio de lote
- endpoint de consulta de lote
- endpoints de eventos assincronos do processamento
- webhooks internos de telefonia usados pela infraestrutura da API
- campos obrigatorios e opcionais de request e response

Ela nao cobre:
- fluxo da plataforma web
- telas do painel
- implementacao do frontend
- endpoints locais de teste (`/test-ui`, `/test/*`)

---

## Visao geral dos grupos de endpoint

### 1. Health
- `GET /health`

### 2. Management API
Usada para criar e configurar a conta operacional que sera dona dos lotes.

- `POST /platform/accounts`
- `GET /platform/accounts/{account_id}`
- `PUT /platform/accounts/{account_id}/company-profile`
- `PUT /platform/accounts/{account_id}/providers/twilio`
- `PUT /platform/accounts/{account_id}/providers/openai`
- `PUT /platform/accounts/{account_id}/providers/email`
- `POST /platform/accounts/{account_id}/api-tokens`

### 3. Validation API
Usada para operar o servico de validacao.

- `POST /validations`
- `GET /validations/{batch_id}`
- `POST /validations/{batch_id}/dispatch`
- `POST /validations/{batch_id}/records/{external_id}/call-events`
- `POST /validations/{batch_id}/records/{external_id}/whatsapp-events`

### 4. Webhooks internos de telefonia
Usados pela propria infraestrutura da API e pelo provedor de voz.

- `POST /webhooks/twilio/voice/twiml`
- `POST /webhooks/twilio/voice/status`
- `WS /webhooks/twilio/voice/media-stream`

---

## Autenticacao

### Management API
A configuracao administrativa da conta usa o header:

```http
```

Esse header e exigido em:
- `POST /platform/accounts`
- `GET /platform/accounts/{account_id}`
- `PUT /platform/accounts/{account_id}/company-profile`
- `PUT /platform/accounts/{account_id}/providers/twilio`
- `PUT /platform/accounts/{account_id}/providers/openai`
- `PUT /platform/accounts/{account_id}/providers/email`
- `POST /platform/accounts/{account_id}/api-tokens`

### Validation API
A operacao do lote usa bearer token:

```http
Authorization: Bearer tkn_live_xxxxx
```

O token identifica a conta executora do lote. A API usa automaticamente a configuracao ja associada a essa conta, como:
- credenciais Twilio
- numeros Twilio ativos
- credenciais OpenAI
- fallback por e-mail
- nome da empresa em nome da qual a IA fala

As credenciais dos provedores nao devem ser enviadas no payload do lote.

---

## Guia rapido de integracao

Esta secao foi pensada para quem vai integrar um backend web com a API.

A ordem recomendada das chamadas e esta:

1. verificar se a API esta online com `GET /health`
2. criar a conta operacional com `POST /platform/accounts`
3. salvar o `account_id` retornado
4. configurar Twilio com `PUT /platform/accounts/{account_id}/providers/twilio`
5. configurar OpenAI com `PUT /platform/accounts/{account_id}/providers/openai`
6. configurar e-mail com `PUT /platform/accounts/{account_id}/providers/email`, se o fallback por e-mail for usado
7. gerar o token com `POST /platform/accounts/{account_id}/api-tokens`
8. salvar o `raw_token` retornado
9. enviar o lote com `POST /validations`
10. consultar o lote com `GET /validations/{batch_id}` ate o resultado final ficar pronto

### O que o integrador precisa guardar

- `account_id`: retornado em `POST /platform/accounts`
- `raw_token`: retornado em `POST /platform/accounts/{account_id}/api-tokens`
- `batch_id`: definido pelo sistema cliente no envio do lote

### Sequencia minima recomendada

#### Passo 1. Verificar a API

```http
GET /health
```

Se retornar `status = ok`, a API esta respondendo.

#### Passo 2. Criar a conta operacional

```http
POST /platform/accounts
Content-Type: application/json
```

```json
{
  "external_account_id": "cliente_123",
  "company_name": "XPTO Cobrancas LTDA",
  "spoken_company_name": "XPTO Validacao",
  "owner_name": "Caio Alves",
  "owner_email": "caio@xpto.com"
}
```

Da response, o integrador deve guardar:
- `id` como `account_id`

#### Passo 3. Configurar Twilio

```http
PUT /platform/accounts/{account_id}/providers/twilio
Content-Type: application/json
```

```json
{
  "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "auth_token": "twilio-secret",
  "webhook_base_url": "https://api.exemplo.com",
  "phone_numbers": [
    {
      "phone_number": "13527176703",
      "friendly_name": "Linha principal",
      "is_active": true,
      "max_concurrent_calls": 1
    }
  ]
}
```

#### Passo 4. Configurar OpenAI

```http
PUT /platform/accounts/{account_id}/providers/openai
Content-Type: application/json
```

```json
{
  "api_key": "sk-xxxxxxxx",
  "realtime_model": "gpt-realtime-1.5",
  "realtime_voice": "cedar",
  "realtime_output_speed": 0.93,
  "realtime_style_instructions": "Fale com tom acolhedor e natural."
}
```

#### Passo 5. Configurar e-mail, se necessario

```http
PUT /platform/accounts/{account_id}/providers/email
Content-Type: application/json
```

```json
{
  "enabled": true,
  "smtp_host": "smtp.exemplo.com",
  "smtp_port": 587,
  "smtp_username": "validacao@xpto.com",
  "smtp_password": "email-secret",
  "smtp_use_tls": true,
  "from_address": "validacao@xpto.com",
  "from_name": "XPTO Validacao"
}
```

Se o cliente nao quiser fallback por e-mail, esse passo pode ser omitido.

#### Passo 6. Gerar o token da API

```http
POST /platform/accounts/{account_id}/api-tokens
Content-Type: application/json
```

```json
{
  "name": "erp_producao"
}
```

Da response, o integrador deve guardar:
- `raw_token`
- `token_id`
- `token_prefix`

Importante:
- o `raw_token` so aparece na criacao
- esse token sera usado nas chamadas de lote

#### Passo 7. Enviar o lote

```http
POST /validations
Authorization: Bearer tkn_live_xxxxx
Content-Type: application/json
```

```json
{
  "batch_id": "erp_lote_20260325_001",
  "source": "integracao_externa",
  "records": [
    {
      "external_id": "1",
      "client_name": "Fornecedor Alfa LTDA",
      "cnpj": "11.222.333/0001-81",
      "phone": "5519994110571",
      "email": "contato@fornecedoralfa.com.br"
    }
  ]
}
```

Importante:
- quando `source = integracao_externa`, o dispatch acontece automaticamente
- nao e necessario chamar `POST /validations/{batch_id}/dispatch` no fluxo padrao

#### Passo 8. Consultar o lote ate finalizar

```http
GET /validations/{batch_id}
Authorization: Bearer tkn_live_xxxxx
```

O integrador deve repetir essa consulta ate observar uma destas condicoes:
- `result_ready = true`
- `batch_status = completed`

### O que normalmente o integrador nao precisa chamar

No fluxo padrao de integracao, o parceiro web normalmente nao precisa chamar diretamente:
- `POST /validations/{batch_id}/dispatch`
- `POST /validations/{batch_id}/records/{external_id}/call-events`
- `POST /validations/{batch_id}/records/{external_id}/whatsapp-events`
- `POST /webhooks/twilio/voice/twiml`
- `POST /webhooks/twilio/voice/status`
- `WS /webhooks/twilio/voice/media-stream`

Esses endpoints existem para operacao interna da infraestrutura e para integracao com os provedores.

---

## Health

### `GET /health`
Retorna o estado basico da API.

#### Response
```json
{
  "status": "ok",
  "service": "API Confaith AI",
  "version": "0.1.0"
}
```

---

## Management API

## Criar conta operacional

### `POST /platform/accounts`
Cria ou atualiza a conta operacional da empresa.

#### Request
```json
{
  "external_account_id": "cliente_123",
  "company_name": "XPTO Cobrancas LTDA",
  "spoken_company_name": "XPTO Validacao",
  "owner_name": "Caio Alves",
  "owner_email": "caio@xpto.com"
}
```

#### Campos
- `external_account_id`: opcional.
- `company_name`: obrigatorio.
- `spoken_company_name`: opcional. Nome que a IA deve usar ao se apresentar.
- `owner_name`: opcional.
- `owner_email`: opcional.

#### Response
```json
{
  "id": 1,
  "external_account_id": "cliente_123",
  "company_name": "XPTO Cobrancas LTDA",
  "spoken_company_name": "XPTO Validacao",
  "owner_name": "Caio Alves",
  "owner_email": "caio@xpto.com",
  "status": "active",
  "caller_company_name": "XPTO Validacao",
  "active_api_tokens": 0,
  "twilio": {
    "configured": false,
    "account_sid_masked": null,
    "webhook_base_url": null,
    "active_phone_numbers": 0,
    "phone_numbers": []
  },
  "openai": {
    "configured": false,
    "api_key_masked": null,
    "realtime_model": null,
    "realtime_voice": null,
    "realtime_output_speed": null,
    "has_style_instructions": false
  },
  "email": {
    "configured": false,
    "enabled": false,
    "smtp_host": null,
    "from_address": null,
    "from_name": null
  },
  "created_at": "2026-03-25T12:00:00.000000",
  "updated_at": "2026-03-25T12:00:00.000000"
}
```

---

## Consultar conta operacional

### `GET /platform/accounts/{account_id}`
Retorna o estado atual da conta operacional.

#### Response
Usa o mesmo formato de `PlatformAccountResponse` do endpoint de criacao.

---

## Atualizar perfil da empresa

### `PUT /platform/accounts/{account_id}/company-profile`
Atualiza os dados principais da empresa dona da conta.

#### Request
```json
{
  "company_name": "XPTO Cobrancas LTDA",
  "spoken_company_name": "XPTO Validacao",
  "owner_name": "Caio Alves",
  "owner_email": "caio@xpto.com"
}
```

#### Campos
- `company_name`: obrigatorio.
- `spoken_company_name`: opcional.
- `owner_name`: opcional.
- `owner_email`: opcional.

#### Response
Usa o mesmo formato de `PlatformAccountResponse`.

---

## Configurar Twilio

### `PUT /platform/accounts/{account_id}/providers/twilio`
Configura as credenciais Twilio e os numeros de origem disponiveis para ligacao.

#### Request
```json
{
  "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "auth_token": "twilio-secret",
  "webhook_base_url": "https://api.exemplo.com",
  "phone_numbers": [
    {
      "phone_number": "13527176703",
      "friendly_name": "Linha principal",
      "is_active": true,
      "max_concurrent_calls": 1
    },
    {
      "phone_number": "13527176704",
      "friendly_name": "Linha secundaria",
      "is_active": true,
      "max_concurrent_calls": 1
    }
  ]
}
```

#### Campos
- `account_sid`: obrigatorio.
- `auth_token`: obrigatorio.
- `webhook_base_url`: opcional.
- `phone_numbers`: obrigatorio. Lista com pelo menos um numero.

#### Campos de `phone_numbers[]`
- `phone_number`: obrigatorio.
- `friendly_name`: opcional.
- `is_active`: opcional. Default `true`.
- `max_concurrent_calls`: opcional. Default `1`. Minimo `1`, maximo `20`.

#### Response
Usa o mesmo formato de `PlatformAccountResponse`.

Observacao:
- a response mascara o `account_sid`
- o `auth_token` nao e retornado na response

---

## Configurar OpenAI

### `PUT /platform/accounts/{account_id}/providers/openai`
Configura a chave e o perfil de voz da conta.

#### Request
```json
{
  "api_key": "sk-xxxxxxxx",
  "realtime_model": "gpt-realtime-1.5",
  "realtime_voice": "cedar",
  "realtime_output_speed": 0.93,
  "realtime_style_instructions": "Fale com tom acolhedor e natural."
}
```

#### Campos
- `api_key`: obrigatorio.
- `realtime_model`: opcional. Default `gpt-realtime-1.5`.
- `realtime_voice`: opcional. Default `cedar`.
- `realtime_output_speed`: opcional. Intervalo permitido `0.25` a `1.5`.
- `realtime_style_instructions`: opcional.

#### Response
Usa o mesmo formato de `PlatformAccountResponse`.

Observacao:
- a response mascara a `api_key`
- a chave original nao e retornada

---

## Configurar fallback por e-mail

### `PUT /platform/accounts/{account_id}/providers/email`
Configura o remetente e o SMTP usado no fallback de e-mail.

#### Request
```json
{
  "enabled": true,
  "smtp_host": "smtp.exemplo.com",
  "smtp_port": 587,
  "smtp_username": "validacao@xpto.com",
  "smtp_password": "email-secret",
  "smtp_use_tls": true,
  "from_address": "validacao@xpto.com",
  "from_name": "XPTO Validacao"
}
```

#### Campos
- `enabled`: opcional. Default `true`.
- `smtp_host`: opcional.
- `smtp_port`: opcional. Default `587`.
- `smtp_username`: opcional.
- `smtp_password`: opcional.
- `smtp_use_tls`: opcional. Default `true`.
- `from_address`: opcional.
- `from_name`: opcional.

#### Response
Usa o mesmo formato de `PlatformAccountResponse`.

Observacao:
- a senha SMTP nao e retornada na response

---

## Gerar token da API

### `POST /platform/accounts/{account_id}/api-tokens`
Gera um novo token para operar os lotes da conta.

#### Request
```json
{
  "name": "erp_producao",
  "expires_at": "2026-12-31T23:59:59Z"
}
```

#### Campos
- `name`: obrigatorio. Default `default`.
- `expires_at`: opcional.

#### Response
```json
{
  "account_id": 1,
  "token_id": 7,
  "name": "erp_producao",
  "token_prefix": "tkn_live_abcd",
  "raw_token": "tkn_live_abcd1234567890",
  "created_at": "2026-03-25T12:10:00.000000",
  "expires_at": "2026-12-31T23:59:59.000000"
}
```

Observacao:
- `raw_token` deve ser armazenado pelo consumidor no momento da criacao
- o token puro nao volta a ser exibido depois

---

## Validation API

## Enviar lote

### `POST /validations`
Cria um lote de validacao cadastral.

#### Headers
```http
Authorization: Bearer tkn_live_xxxxx
```

#### Payload esperado
```json
{
  "batch_id": "erp_lote_20260325_001",
  "source": "integracao_externa",
  "records": [
    {
      "external_id": "1",
      "client_name": "Fornecedor Alfa LTDA",
      "cnpj": "11.222.333/0001-81",
      "phone": "5519994110571",
      "email": "contato@fornecedoralfa.com.br"
    },
    {
      "external_id": "2",
      "client_name": "Fornecedor Beta LTDA",
      "cnpj": "22.333.444/0001-55",
      "phone": "5511999990001",
      "email": null
    }
  ]
}
```

#### Campos do lote
- `batch_id`: obrigatorio. Identificador unico do lote no sistema do cliente.
- `source`: obrigatorio. Valores aceitos atualmente:
  - `integracao_externa`
  - `web`
- `records`: obrigatorio. Lista com um ou mais registros.

#### Campos de cada registro
- `external_id`: obrigatorio.
- `client_name`: obrigatorio.
- `cnpj`: obrigatorio.
- `phone`: obrigatorio.
- `email`: opcional.

#### Aliases aceitos no request
- `batch_id` ou `id_lote`
- `source` ou `origem`
- `external_id` ou `id_registro`
- `client_name`, `supplier_name`, `nome_cliente` ou `nome_fornecedor`
- `phone` ou `telefone`
- `email`, `e_mail` ou `correio_eletronico`

#### Response imediata
A API retorna `202 Accepted` com o estado atual do lote no momento do aceite.

```json
{
  "batch_id": "erp_lote_20260325_001",
  "account_id": 12,
  "api_token_id": 7,
  "caller_company_name": "XPTO Validacao",
  "source": "integracao_externa",
  "batch_status": "processing",
  "processed_at": "2026-03-25T14:05:10.000000",
  "created_at": "2026-03-25T14:05:10.000000",
  "updated_at": "2026-03-25T14:05:10.000000",
  "finished_at": null,
  "result_ready": false,
  "technical_status": "processing",
  "total_records": 2,
  "summary": {
    "ready_for_call": 2,
    "ready_for_retry_call": 0,
    "validation_failed": 0,
    "invalid_phone": 0,
    "cnpj_not_found": 0,
    "processing": 2,
    "pending_records": 2,
    "validated_records": 0,
    "failed_records": 0,
    "confirmed_by_call": 0,
    "confirmed_by_whatsapp": 0,
    "waiting_whatsapp_reply": 0,
    "confirmed_by_email": 0,
    "waiting_email_reply": 0
  },
  "records": []
}
```

---

## Consultar lote

### `GET /validations/{batch_id}`
Retorna o estado atual do lote.

#### Headers
```http
Authorization: Bearer tkn_live_xxxxx
```

#### Observacoes
- esse endpoint ja esta implementado
- para lotes autenticados, exige o bearer token da mesma conta dona do lote
- sem token em lote protegido: `401 Unauthorized`
- com token de outra conta: `403 Forbidden`
- lote inexistente: `404 Not Found`

#### Exemplo de consulta
```http
GET /validations/erp_lote_20260325_001
Authorization: Bearer tkn_live_xxxxx
```

---

## Disparar lote manualmente

### `POST /validations/{batch_id}/dispatch`
Dispara ou redespacha um lote para processamento.

#### Query params
- `twiml_mode`: opcional.
  - `media_stream`
  - `diagnostic_say`

#### Response
Retorna `ValidationBatchResponse`.

Observacao:
- para lotes enviados com `source = integracao_externa`, o dispatch ja ocorre automaticamente no `POST /validations`
- este endpoint e util quando o fluxo precisa de disparo explicito

---

## Registrar evento de chamada

### `POST /validations/{batch_id}/records/{external_id}/call-events`
Registra o resultado de uma tentativa de chamada para um registro especifico.

#### Request
```json
{
  "provider_call_id": "CAxxxxxxxx",
  "call_status": "answered",
  "call_result": "confirmed",
  "transcript_summary": "cliente: Sim. | agente: ...",
  "sentiment": null,
  "duration_seconds": 41,
  "observation": "Numero confirmado por ligacao conversacional.",
  "happened_at": "2026-03-25T14:06:01.000000"
}
```

#### Campos
- `provider_call_id`: opcional.
- `call_status`: obrigatorio.
- `call_result`: obrigatorio.
- `transcript_summary`: opcional.
- `sentiment`: opcional.
- `duration_seconds`: opcional. Minimo `0`.
- `observation`: opcional.
- `happened_at`: opcional.

#### Response
Retorna `ValidationRecordResponse` com o estado atualizado do registro.

---

## Registrar evento de WhatsApp

### `POST /validations/{batch_id}/records/{external_id}/whatsapp-events`
Registra um evento de mensagem WhatsApp para um registro especifico.

#### Request
```json
{
  "provider_message_id": "wamid.xxxxx",
  "status": "confirmed_by_whatsapp",
  "direction": "inbound",
  "message_body": "Sim, pertence.",
  "response_text": "SIM",
  "observation": "Cliente confirmou por WhatsApp.",
  "happened_at": "2026-03-25T14:09:00.000000"
}
```

#### Campos
- `provider_message_id`: opcional.
- `status`: obrigatorio.
- `direction`: opcional. Default `inbound`.
- `message_body`: opcional.
- `response_text`: opcional.
- `observation`: opcional.
- `happened_at`: opcional.

#### Response
Retorna `ValidationRecordResponse` com o estado atualizado do registro.

---

## Response do lote

A response de lote usa o schema `ValidationBatchResponse`.

### Exemplo de response final

```json
{
  "batch_id": "erp_lote_20260325_001",
  "account_id": 12,
  "api_token_id": 7,
  "caller_company_name": "XPTO Validacao",
  "source": "integracao_externa",
  "batch_status": "completed",
  "processed_at": "2026-03-25T14:05:10.000000",
  "created_at": "2026-03-25T14:05:10.000000",
  "updated_at": "2026-03-25T14:10:22.000000",
  "finished_at": "2026-03-25T14:10:22.000000",
  "result_ready": true,
  "technical_status": "completed",
  "total_records": 2,
  "summary": {
    "ready_for_call": 0,
    "ready_for_retry_call": 0,
    "validation_failed": 1,
    "invalid_phone": 0,
    "cnpj_not_found": 0,
    "processing": 0,
    "pending_records": 0,
    "validated_records": 1,
    "failed_records": 1,
    "confirmed_by_call": 1,
    "confirmed_by_whatsapp": 0,
    "waiting_whatsapp_reply": 0,
    "confirmed_by_email": 0,
    "waiting_email_reply": 0
  },
  "records": [
    {
      "external_id": "1",
      "client_name": "Fornecedor Alfa LTDA",
      "cnpj_original": "11.222.333/0001-81",
      "cnpj_normalized": "11222333000181",
      "phone_original": "5519994110571",
      "phone_normalized": "5519994110571",
      "phone_type": "mobile",
      "email_original": "contato@fornecedoralfa.com.br",
      "email_normalized": "contato@fornecedoralfa.com.br",
      "official_registry_email": null,
      "fallback_email_used": null,
      "cnpj_found": true,
      "phone_valid": true,
      "ready_for_contact": true,
      "technical_status": "completed",
      "business_status": "confirmed_by_call",
      "call_status": "answered",
      "call_result": "confirmed",
      "transcript_summary": "cliente: Sim. | agente: ...",
      "customer_transcript": "Sim.",
      "assistant_transcript": "Ola, aqui e da XPTO Validacao...",
      "sentiment": null,
      "whatsapp_status": "not_required",
      "email_status": "not_required",
      "phone_confirmed": true,
      "confirmation_source": "voice_call",
      "validated_phone": "5519994110571",
      "last_phone_dialed": "5519994110571",
      "last_phone_source": "payload_phone",
      "attempted_phones": ["5519994110571"],
      "attempts_count": 1,
      "official_registry_checked": true,
      "official_registry_retry_found": false,
      "official_registry_retry_phone": null,
      "final_status": "validated",
      "observation": "Numero confirmado por ligacao conversacional.",
      "call_attempts": [
        {
          "attempt_number": 1,
          "provider_call_id": "CAxxxxxxxx",
          "phone_dialed": "5519994110571",
          "from_phone_number_used": "13527176703",
          "phone_source": "payload_phone",
          "status": "answered",
          "result": "confirmed",
          "transcript_summary": "cliente: Sim. | agente: ...",
          "customer_transcript": "Sim.",
          "assistant_transcript": "Ola, aqui e da XPTO Validacao...",
          "sentiment": null,
          "duration_seconds": 41,
          "started_at": "2026-03-25T14:05:20.000000",
          "finished_at": "2026-03-25T14:06:01.000000",
          "observation": "Numero confirmado por ligacao conversacional."
        }
      ],
      "whatsapp_history": [],
      "email_history": []
    }
  ]
}
```

### Campos de `ValidationBatchResponse`

#### Nivel do lote
- `batch_id`
- `account_id`
- `api_token_id`
- `caller_company_name`
- `source`
- `batch_status`
- `processed_at`
- `created_at`
- `updated_at`
- `finished_at`
- `result_ready`
- `technical_status`
- `total_records`
- `summary`
- `records`

#### Nivel do resumo
- `ready_for_call`
- `ready_for_retry_call`
- `validation_failed`
- `invalid_phone`
- `cnpj_not_found`
- `processing`
- `pending_records`
- `validated_records`
- `failed_records`
- `confirmed_by_call`
- `confirmed_by_whatsapp`
- `waiting_whatsapp_reply`
- `confirmed_by_email`
- `waiting_email_reply`

#### Nivel do registro
- `external_id`
- `client_name`
- `cnpj_original`
- `cnpj_normalized`
- `phone_original`
- `phone_normalized`
- `phone_type`
- `email_original`
- `email_normalized`
- `official_registry_email`
- `fallback_email_used`
- `cnpj_found`
- `phone_valid`
- `ready_for_contact`
- `technical_status`
- `business_status`
- `call_status`
- `call_result`
- `transcript_summary`
- `customer_transcript`
- `assistant_transcript`
- `sentiment`
- `whatsapp_status`
- `email_status`
- `phone_confirmed`
- `confirmation_source`
- `validated_phone`
- `last_phone_dialed`
- `last_phone_source`
- `attempted_phones`
- `attempts_count`
- `official_registry_checked`
- `official_registry_retry_found`
- `official_registry_retry_phone`
- `final_status`
- `observation`
- `call_attempts`
- `whatsapp_history`
- `email_history`

#### Nivel da tentativa de ligacao
- `attempt_number`
- `provider_call_id`
- `phone_dialed`
- `from_phone_number_used`
- `phone_source`
- `status`
- `result`
- `transcript_summary`
- `customer_transcript`
- `assistant_transcript`
- `sentiment`
- `duration_seconds`
- `started_at`
- `finished_at`
- `observation`

#### Nivel do historico de e-mail
- `provider_message_id`
- `direction`
- `recipient_email`
- `subject`
- `message_body`
- `response_text`
- `status`
- `sent_at`
- `responded_at`
- `observation`

#### Nivel do historico de WhatsApp
- `provider_message_id`
- `direction`
- `message_body`
- `response_text`
- `status`
- `sent_at`
- `responded_at`
- `observation`

---

## Webhooks internos de telefonia

## TwiML da chamada

### `POST /webhooks/twilio/voice/twiml`
Endpoint interno usado pelo Twilio para obter a TwiML da chamada.

#### Query params usados internamente
- `batch_id`
- `external_id`
- `attempt_number`
- `caller_company_name`
- `client_name`
- `cnpj`
- `phone_dialed`
- `twiml_mode`
- `realtime_model`
- `realtime_voice`
- `realtime_output_speed`
- `realtime_style_profile`

#### Observacao
- endpoint interno da infraestrutura
- nao e endpoint de consumo para integradores de negocio

---

## Callback de status Twilio

### `POST /webhooks/twilio/voice/status`
Endpoint interno usado pelo Twilio para notificar o status da chamada.

#### Campos lidos do form do provedor
- `CallSid`
- `CallStatus`
- `CallDuration`

#### Query params usados internamente
- `batch_id`
- `external_id`
- `attempt_number`

---

## Media stream Twilio

### `WS /webhooks/twilio/voice/media-stream`
WebSocket interno que faz a ponte entre o audio da chamada e o OpenAI Realtime.

#### Observacao
- endpoint interno da infraestrutura
- nao e endpoint de consumo para integradores de negocio

---

## Status possiveis

### BatchStatus
- `received`
- `processing`
- `completed`

### TechnicalStatus
- `received`
- `payload_invalid`
- `normalized`
- `ready_for_validation`
- `processing`
- `completed`

### BusinessStatus
- `cnpj_not_found`
- `invalid_phone`
- `ready_for_call`
- `ready_for_retry_call`
- `call_not_answered`
- `call_answered`
- `confirmed_by_call`
- `rejected_by_call`
- `inconclusive_call`
- `whatsapp_sent`
- `waiting_whatsapp_reply`
- `confirmed_by_whatsapp`
- `rejected_by_whatsapp`
- `email_sent`
- `waiting_email_reply`
- `confirmed_by_email`
- `rejected_by_email`
- `validation_failed`
- `validated`

### CallStatus
- `not_started`
- `queued`
- `answered`
- `not_answered`
- `failed`

### CallResult
- `not_started`
- `pending_dispatch`
- `confirmed`
- `rejected`
- `inconclusive`
- `not_answered`

### CallPhoneSource
- `payload_phone`
- `official_company_registry`

### WhatsAppStatus
- `not_required`
- `queued`
- `sent`
- `waiting_whatsapp_reply`
- `confirmed_by_whatsapp`
- `rejected_by_whatsapp`
- `expired_without_reply`

### EmailStatus
- `not_required`
- `sent`
- `waiting_email_reply`
- `confirmed_by_email`
- `rejected_by_email`
- `failed`
- `expired_without_reply`

### FinalStatus
- `processing`
- `validation_failed`
- `validated`

---

## Erros comuns

### `401 Unauthorized`
Pode ocorrer quando:
- o header `Authorization` nao foi enviado
- o bearer token esta invalido
- o bearer token nao pode ser autenticado

### `403 Forbidden`
Pode ocorrer quando:
- o lote pertence a outra conta
- o token autenticado nao e dono do `batch_id` consultado

### `404 Not Found`
Pode ocorrer quando:
- a conta nao existe
- o lote nao existe
- o registro nao existe em rotas especificas de registro

### `409 Conflict`
Pode ocorrer quando:
- o `batch_id` ja foi utilizado anteriormente

### `422 Unprocessable Entity`
Pode ocorrer quando:
- a conta dona do token nao esta pronta para operar
- falta configuracao obrigatoria para processar validacoes
- configuracao enviada para um provedor nao passou na validacao da API

### `503 Service Unavailable`
Pode ocorrer quando:
- a infraestrutura de provedor nao esta pronta para montar o fluxo de voz

---

## Observacoes atuais

- `POST /platform/accounts` esta implementado
- `GET /platform/accounts/{account_id}` esta implementado
- `PUT /platform/accounts/{account_id}/company-profile` esta implementado
- `PUT /platform/accounts/{account_id}/providers/twilio` esta implementado
- `PUT /platform/accounts/{account_id}/providers/openai` esta implementado
- `PUT /platform/accounts/{account_id}/providers/email` esta implementado
- `POST /platform/accounts/{account_id}/api-tokens` esta implementado
- `POST /validations` esta implementado
- `GET /validations` esta implementado
- `GET /validations/{batch_id}` esta implementado
- `POST /validations/{batch_id}/dispatch` esta implementado
- `POST /validations/{batch_id}/records/{external_id}/call-events` esta implementado
- `POST /validations/{batch_id}/records/{external_id}/whatsapp-events` esta implementado
- para lotes associados a uma conta, os endpoints de evento exigem o bearer token dono do lote
- `GET /validations` lista os lotes da conta autenticada por bearer token
- o fallback por e-mail ja pode ser disparado quando a ligacao nao e atendida
- o processamento da resposta inbound do cliente por e-mail ainda nao fecha o lote automaticamente
- endpoints locais de teste nao fazem parte deste contrato
