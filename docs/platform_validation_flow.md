# API de Validacao

## Objetivo
Esta documentacao cobre o contrato oficial da API para integracao com a plataforma web e com clientes externos autenticados.

Ela cobre:
- Management API para criar e configurar contas operacionais
- Validation API para validacao cadastral por lote
- Supplier Validation API para validacao de fornecedores por planilha, com ligacao
- Supplier Discovery API para busca publica de fornecedores, sem ligacao por enquanto
- Mobile API para dashboard e lista de chamadas

Ela nao cobre:
- `/test-ui`
- endpoints `/test/*`
- telas do frontend
- detalhes internos dos webhooks da infraestrutura

---

## Autenticacao

### Management API
Os endpoints administrativos exigem o header abaixo em todas as chamadas:

```http
X-Platform-Admin-Key: sua-chave-interna
```

Esses endpoints sao destinados ao backend da plataforma web.

### APIs publicas de operacao
Os endpoints de lote, mobile e supplier discovery usam bearer token:

```http
Authorization: Bearer tkn_live_xxxxx
```

O bearer token identifica a conta dona da requisicao.

---

## Seguranca de segredos
Os segredos de provedores agora sao criptografados em repouso no banco:
- `twilio.auth_token`
- `openai.api_key`
- `email.smtp_password`

As responses publicas continuam retornando apenas valores mascarados quando necessario.

Observacao:
- leituras ainda aceitam registros legados em texto puro para compatibilidade com dados antigos
- para ambientes reais, configure `SECRET_ENCRYPTION_KEY`

---

## Visao geral dos grupos de endpoint

### Health
- `GET /health`

### Management API
- `POST /platform/accounts`
- `GET /platform/accounts/{account_id}`
- `PUT /platform/accounts/{account_id}/company-profile`
- `PUT /platform/accounts/{account_id}/providers/twilio`
- `PUT /platform/accounts/{account_id}/providers/openai`
- `PUT /platform/accounts/{account_id}/providers/email`
- `POST /platform/accounts/{account_id}/api-tokens`

### Validation API
- `POST /validations`
- `GET /validations`
- `GET /validations/{batch_id}`
- `POST /validations/{batch_id}/dispatch`

### Supplier Validation API
- `POST /supplier-validations`
- `GET /supplier-validations/{batch_id}`

### Supplier Discovery API
- `POST /supplier-discovery`
- `GET /supplier-discovery/{search_id}`
- `GET /supplier-discovery/{search_id}/results.xlsx`

### Mobile API
- `GET /mobile/dashboard?period=24h|week|month`
- `GET /mobile/calls?period=24h|week|month&limit=50&offset=0`

---

## Fluxo recomendado da plataforma web
1. `GET /health`
2. `POST /platform/accounts`
3. `PUT /platform/accounts/{account_id}/providers/twilio`
4. `PUT /platform/accounts/{account_id}/providers/openai`
5. `PUT /platform/accounts/{account_id}/providers/email` se houver fallback
6. `POST /platform/accounts/{account_id}/api-tokens`
7. usar o `raw_token` nas APIs publicas

---

## Health

### `GET /health`
Response:
```json
{
  "status": "ok",
  "service": "Client Contact Validation API",
  "version": "0.1.0"
}
```

---

## Management API

### `POST /platform/accounts`
Cria ou atualiza a conta operacional.

Request:
```json
{
  "external_account_id": "cliente_123",
  "company_name": "XPTO Cobrancas LTDA",
  "spoken_company_name": "XPTO Validacao",
  "owner_name": "Caio Alves",
  "owner_email": "caio@xpto.com"
}
```

Response principal:
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
  "created_at": "2026-03-28T12:00:00Z",
  "updated_at": "2026-03-28T12:00:00Z"
}
```

### `PUT /platform/accounts/{account_id}/providers/twilio`
Request:
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

### `PUT /platform/accounts/{account_id}/providers/openai`
Request:
```json
{
  "api_key": "sk-xxxxxxxx",
  "realtime_model": "gpt-realtime-1.5",
  "realtime_voice": "cedar",
  "realtime_output_speed": 0.93,
  "realtime_style_instructions": "Fale com tom acolhedor e natural."
}
```

### `PUT /platform/accounts/{account_id}/providers/email`
Request:
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

### `POST /platform/accounts/{account_id}/api-tokens`
Request:
```json
{
  "name": "erp_producao"
}
```

Response:
```json
{
  "account_id": 1,
  "token_id": 10,
  "name": "erp_producao",
  "token_prefix": "tkn_live_xxxxx",
  "raw_token": "tkn_live_xxxxx.yyyyy",
  "created_at": "2026-03-28T12:05:00Z",
  "expires_at": null
}
```

Importante:
- o `raw_token` so aparece na criacao
- a plataforma deve armazenar esse valor de forma segura

---

## Validation API

### `POST /validations`
Usada para validacao cadastral por lote.

Request:
```json
{
  "batch_id": "erp_lote_20260328_001",
  "source": "integracao_externa",
  "records": [
    {
      "external_id": "1",
      "client_name": "Fornecedor Alfa LTDA",
      "cnpj": "11.222.333/0001-81",
      "phone": "5511999999999",
      "email": "contato@fornecedor.com"
    }
  ]
}
```

### `GET /validations`
Lista os lotes da conta autenticada.

Query params:
- `limit`
- `offset`
- `batch_status` opcional

### `GET /validations/{batch_id}`
Consulta o lote completo.

---

## Supplier Validation API

### `POST /supplier-validations`
Usada quando o cliente ja possui uma planilha de fornecedores e deseja validar por ligacao.

Request:
```json
{
  "batch_id": "supplier_batch_20260328_001",
  "source": "integracao_externa",
  "segment_name": "Adubo",
  "callback_phone": "5511999999999",
  "callback_contact_name": "Comercial Agro Compras",
  "records": [
    {
      "external_id": "1",
      "supplier_name": "Fornecedor Adubo 1 LTDA",
      "phone": "5511988887777",
      "email": "contato@fornecedor.com"
    }
  ]
}
```

### `GET /supplier-validations/{batch_id}`
Retorna o lote de fornecedor processado, com os campos extras de `supplier_validation` no response.

---

## Supplier Discovery API

Estado atual:
- endpoint publico
- autenticado por bearer token
- executa apenas busca web
- nao dispara ligacoes automaticamente por enquanto

### `POST /supplier-discovery`
Busca fornecedores reais na web e devolve um resultado estruturado com `search_id` e link para planilha.

Request:
```json
{
  "segment_name": "Adubo",
  "callback_phone": "5511999999999",
  "callback_contact_name": "Comercial Agro Compras",
  "region": "Campinas",
  "max_suppliers": 10
}
```

Campos:
- `segment_name`: obrigatorio
- `callback_phone`: obrigatorio
- `callback_contact_name`: opcional
- `region`: opcional
- `max_suppliers`: opcional, default `10`, maximo `50`

Response:
```json
{
  "search_id": "supplier_search_20260328150000_ab12cd",
  "mode": "openai_web_search",
  "segment_name": "Adubo",
  "region": "Campinas",
  "callback_phone": "5511999999999",
  "callback_contact_name": "Comercial Agro Compras",
  "generated_at": "2026-03-28T15:00:00Z",
  "total_suppliers": 3,
  "suppliers": [
    {
      "supplier_name": "Fornecedor Exemplo LTDA",
      "phone": "5511999999999",
      "website": "https://fornecedor.com.br",
      "city": "Campinas",
      "state": "SP",
      "source_urls": ["https://fornecedor.com.br/contato"],
      "discovery_confidence": 0.82,
      "notes": "Fornecedor encontrado em site oficial do segmento."
    }
  ],
  "downloadable_file_url": "/supplier-discovery/supplier_search_20260328150000_ab12cd/results.xlsx",
  "message": "Busca concluida com a Responses API usando web search."
}
```

### `GET /supplier-discovery/{search_id}`
Recupera uma busca anterior da mesma conta autenticada.

### `GET /supplier-discovery/{search_id}/results.xlsx`
Baixa a planilha pronta com os resultados da busca.

Observacoes:
- o endpoint usa a credencial OpenAI configurada na conta do token
- se a conta nao tiver OpenAI configurada, retorna `422`
- se a busca externa falhar, a API retorna erro para o cliente em vez de usar mock
- no estado atual, o resultado da busca publica fica mantido em memoria da aplicacao; apos restart, `GET /supplier-discovery/{search_id}` e o download podem deixar de encontrar o resultado

---

## Mobile API

### `GET /mobile/dashboard?period=24h|week|month`
Retorna agregados da conta autenticada:
- total de lotes
- registros validados
- confirmados
- nao confirmados
- nao atendidos
- tempo medio real
- custo medio estimado

### `GET /mobile/calls?period=24h|week|month&limit=50&offset=0`
Retorna a lista paginada das tentativas de chamada da conta autenticada.

---

## Endpoints internos e de infraestrutura
Os endpoints abaixo existem, mas normalmente nao sao chamados diretamente pelo integrador:
- `POST /validations/{batch_id}/dispatch`
- `POST /validations/{batch_id}/records/{external_id}/call-events`
- `POST /validations/{batch_id}/records/{external_id}/whatsapp-events`
- `POST /webhooks/twilio/voice/twiml`
- `POST /webhooks/twilio/voice/status`
- `WS /webhooks/twilio/voice/media-stream`
