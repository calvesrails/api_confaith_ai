# Visao Geral das Tabelas do Banco

Base analisada:
- Banco real: `/home/calves/api_confaith_ai/contact_validation.db`
- Models atuais: `/home/calves/api_confaith_ai/app/db/models`

## Resumo rapido

Hoje o banco possui `12 tabelas`:

### Conta e integracoes
- `platform_accounts`
- `api_tokens`
- `twilio_credentials`
- `twilio_phone_numbers`
- `openai_credentials`
- `email_sender_profiles`

### Processamento
- `validation_batches`
- `validation_records`
- `call_attempts`

### Mensagens e fallback
- `email_messages`
- `whatsapp_messages`

### Rastreio tecnico
- `phone_lookup_traces`

## Relacionamento principal

- `platform_accounts` e a tabela raiz da conta do cliente da API.
- Cada conta pode ter:
  - varios `api_tokens`
  - uma `twilio_credentials`
  - varios `twilio_phone_numbers`
  - uma `openai_credentials`
  - um `email_sender_profiles`
  - varios `validation_batches`
- Cada `validation_batches` possui varios `validation_records`.
- Cada `validation_records` pode ter:
  - varios `call_attempts`
  - varios `email_messages`
  - varios `whatsapp_messages`
  - varios `phone_lookup_traces`

---

## 1. platform_accounts

Finalidade:
- guardar a conta operacional do cliente da plataforma

Relacionamentos:
- 1:N com `api_tokens`
- 1:1 com `twilio_credentials`
- 1:N com `twilio_phone_numbers`
- 1:1 com `openai_credentials`
- 1:1 com `email_sender_profiles`
- 1:N com `validation_batches`

Campos principais:
- `id`
- `external_account_id`
- `company_name`
- `spoken_company_name`
- `owner_name`
- `owner_email`
- `status`
- `created_at`
- `updated_at`

Uso:
- identifica o cliente dono das credenciais e dos lotes

## 2. api_tokens

Finalidade:
- guardar os tokens de acesso da API publica

Relacionamentos:
- N:1 com `platform_accounts`
- 1:N com `validation_batches`

Campos principais:
- `id`
- `platform_account_id`
- `name`
- `token_prefix`
- `token_hash`
- `last_used_at`
- `expires_at`
- `revoked_at`
- `created_at`
- `updated_at`

Uso:
- autenticar chamadas externas como `POST /validations` e endpoints mobile

## 3. twilio_credentials

Finalidade:
- guardar a credencial Twilio da conta

Relacionamentos:
- 1:1 com `platform_accounts`

Campos principais:
- `id`
- `platform_account_id`
- `account_sid`
- `auth_token`
- `webhook_base_url`
- `created_at`
- `updated_at`

Uso:
- configurar o provedor de voz por conta

## 4. twilio_phone_numbers

Finalidade:
- guardar os numeros Twilio disponiveis para originar ligacoes

Relacionamentos:
- N:1 com `platform_accounts`

Campos principais:
- `id`
- `platform_account_id`
- `phone_number`
- `friendly_name`
- `is_active`
- `max_concurrent_calls`
- `created_at`
- `updated_at`

Uso:
- controlar o pool de numeros e o paralelismo de chamadas

## 5. openai_credentials

Finalidade:
- guardar a configuracao OpenAI da conta

Relacionamentos:
- 1:1 com `platform_accounts`

Campos principais:
- `id`
- `platform_account_id`
- `api_key`
- `realtime_model`
- `realtime_voice`
- `realtime_output_speed`
- `realtime_style_instructions`
- `created_at`
- `updated_at`

Uso:
- definir qual chave, modelo e voz a conta usa nas chamadas

## 6. email_sender_profiles

Finalidade:
- guardar a configuracao SMTP/remetente usada no fallback de e-mail

Relacionamentos:
- 1:1 com `platform_accounts`

Campos principais:
- `id`
- `platform_account_id`
- `enabled`
- `smtp_host`
- `smtp_port`
- `smtp_username`
- `smtp_password`
- `smtp_use_tls`
- `from_address`
- `from_name`
- `created_at`
- `updated_at`

Uso:
- enviar e-mails em nome da conta do cliente

## 7. validation_batches

Finalidade:
- representar o lote de validacao enviado para a API

Relacionamentos:
- N:1 com `platform_accounts`
- N:1 com `api_tokens`
- 1:N com `validation_records`

Campos principais:
- `id`
- `batch_id`
- `public_batch_id`
- `platform_account_id`
- `api_token_id`
- `caller_company_name`
- `source`
- `batch_status`
- `technical_status`
- `total_records`
- `created_at`
- `updated_at`
- `finished_at`

Uso:
- consolidar o estado geral do lote
- separar o `batch_id` publico do identificador interno armazenado

## 8. validation_records

Finalidade:
- guardar cada linha/empresa dentro de um lote

Relacionamentos:
- N:1 com `validation_batches`
- 1:N com `call_attempts`
- 1:N com `email_messages`
- 1:N com `whatsapp_messages`

Campos principais:
- `id`
- `validation_batch_id`
- `external_id`
- `supplier_name` mapeado como `client_name` no model
- `cnpj_original`
- `cnpj_normalized`
- `phone_original`
- `phone_normalized`
- `phone_type`
- `email_original`
- `email_normalized`
- `official_registry_email`
- `cnpj_found`
- `phone_valid`
- `ready_for_contact`
- `technical_status`
- `business_status`
- `call_status`
- `call_result`
- `transcript_summary`
- `whatsapp_status`
- `email_status`
- `phone_confirmed`
- `confirmation_source`
- `final_status`
- `observation`
- `created_at`
- `updated_at`

Uso:
- guardar o estado final e intermediario de cada empresa/telefone validado

## 9. call_attempts

Finalidade:
- guardar cada tentativa de ligacao de um registro

Relacionamentos:
- N:1 com `validation_records`

Campos principais:
- `id`
- `validation_record_id`
- `attempt_number`
- `provider_call_id`
- `phone_dialed`
- `from_phone_number_used`
- `phone_source`
- `status`
- `result`
- `transcript_summary`
- `sentiment`
- `duration_seconds`
- `started_at`
- `finished_at`
- `observation`
- `created_at`
- `updated_at`

Uso:
- historico detalhado das ligacoes feitas
- base para dashboard mobile, transcricoes e auditoria

## 10. email_messages

Finalidade:
- guardar historico do fallback por e-mail

Relacionamentos:
- N:1 com `validation_records`

Campos principais:
- `id`
- `validation_record_id`
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
- `created_at`
- `updated_at`

Uso:
- rastrear envio e eventual resposta de e-mail

## 11. whatsapp_messages

Finalidade:
- guardar historico de mensagens de WhatsApp relacionadas ao registro

Relacionamentos:
- N:1 com `validation_records`

Campos principais:
- `id`
- `validation_record_id`
- `provider_message_id`
- `direction`
- `message_body`
- `response_text`
- `status`
- `sent_at`
- `responded_at`
- `observation`
- `created_at`
- `updated_at`

Uso:
- registrar fallback ou interacoes por WhatsApp

## 12. phone_lookup_traces

Finalidade:
- guardar rastros tecnicos da busca de telefone

Relacionamentos:
- N:1 com `validation_records`

Campos principais encontrados no banco:
- `id`
- `validation_record_id`
- `source`
- `status`
- `message`
- `url`
- `phone`
- `created_at`

Observacao:
- essa tabela existe no banco real atual
- nao encontrei model correspondente em `app/db/models`
- entao hoje ela parece ser uma tabela tecnica/remanescente do banco

---

## Observacoes finais

- O banco hoje ja suporta o modelo multi-tenant da API.
- A conta do cliente fica em `platform_accounts`.
- O token da API fica em `api_tokens`.
- O lote operacional fica em `validation_batches`.
- O detalhe por empresa fica em `validation_records`.
- O historico de chamadas fica em `call_attempts`.
- Os fallbacks ficam em `email_messages` e `whatsapp_messages`.

