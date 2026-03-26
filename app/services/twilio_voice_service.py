from __future__ import annotations

from dataclasses import dataclass
from html import escape
import logging
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import json

from .errors import ProviderConfigurationError, ProviderRequestError

logger = logging.getLogger(__name__)

TwimlMode = Literal["media_stream", "diagnostic_say"]


@dataclass(slots=True)
class TwilioCallDispatchResult:
    provider_call_id: str
    provider_status: str | None
    raw_payload: dict[str, Any]


class TwilioVoiceService:
    def __init__(
        self,
        *,
        account_sid: str | None,
        auth_token: str | None,
        from_phone_number: str | None,
        webhook_base_url: str | None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_phone_number = from_phone_number
        self.webhook_base_url = webhook_base_url.rstrip("/") if webhook_base_url else None

    def is_configured(self) -> bool:
        return all(
            [
                self.account_sid,
                self.auth_token,
                self.from_phone_number,
                self.webhook_base_url,
            ]
        )

    def create_outbound_call(
        self,
        *,
        batch_id: str,
        external_id: str,
        attempt_number: int,
        caller_company_name: str | None,
        client_name: str,
        cnpj: str,
        phone_to_dial: str,
        from_phone_number_override: str | None = None,
        twiml_mode: TwimlMode = "media_stream",
        realtime_model_override: str | None = None,
        realtime_voice_override: str | None = None,
        realtime_output_speed_override: float | None = None,
        realtime_style_profile: str | None = None,
    ) -> TwilioCallDispatchResult:
        self._ensure_configured()
        twilio_to_phone = self._format_e164(phone_to_dial)
        twilio_from_phone = self._format_e164(from_phone_number_override or self.from_phone_number)
        logger.info(
            "Solicitando criacao de chamada no Twilio | batch_id=%s external_id=%s attempt_number=%s phone_to_dial=%s twilio_to_phone=%s twilio_from_phone=%s twiml_mode=%s",
            batch_id,
            external_id,
            attempt_number,
            phone_to_dial,
            twilio_to_phone,
            twilio_from_phone,
            twiml_mode,
        )

        call_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"
        )
        twiml_query = {
            "batch_id": batch_id,
            "external_id": external_id,
            "attempt_number": str(attempt_number),
            "caller_company_name": caller_company_name or "",
            "client_name": client_name,
            "cnpj": cnpj,
            "phone_dialed": twilio_to_phone,
            "twiml_mode": twiml_mode,
        }
        if realtime_model_override:
            twiml_query["realtime_model"] = realtime_model_override
        if realtime_voice_override:
            twiml_query["realtime_voice"] = realtime_voice_override
        if realtime_output_speed_override is not None:
            twiml_query["realtime_output_speed"] = str(realtime_output_speed_override)
        if realtime_style_profile:
            twiml_query["realtime_style_profile"] = realtime_style_profile

        twiml_url = self._build_https_url(
            "/webhooks/twilio/voice/twiml",
            **twiml_query,
        )
        status_callback_url = self._build_https_url(
            "/webhooks/twilio/voice/status",
            batch_id=batch_id,
            external_id=external_id,
            attempt_number=str(attempt_number),
        )
        logger.info(
            "URLs publicas da chamada no Twilio | batch_id=%s external_id=%s twiml_url=%s status_callback_url=%s",
            batch_id,
            external_id,
            twiml_url,
            status_callback_url,
        )

        payload: dict[str, Any] = {
            "To": twilio_to_phone,
            "From": twilio_from_phone,
            "Url": twiml_url,
            "Method": "POST",
            "StatusCallback": status_callback_url,
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": [
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
        }

        try:
            response = httpx.post(
                call_url,
                data=payload,
                auth=(self.account_sid or "", self.auth_token or ""),
                timeout=20.0,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            response_body = error.response.text
            provider_code = self._extract_provider_error_code(response_body)
            logger.exception(
                "Twilio retornou erro HTTP ao criar chamada | batch_id=%s external_id=%s status_code=%s provider_code=%s response_body=%s",
                batch_id,
                external_id,
                error.response.status_code,
                provider_code,
                response_body,
            )
            raise ProviderRequestError(
                "Twilio Voice",
                (
                    "Twilio retornou erro ao criar a ligacao. "
                    f"status_code={error.response.status_code} response_body={response_body}"
                ),
                status_code=error.response.status_code,
                provider_code=provider_code,
            ) from error
        except httpx.HTTPError as error:
            logger.exception(
                "Erro HTTP ao criar chamada no Twilio | batch_id=%s external_id=%s error=%s",
                batch_id,
                external_id,
                error,
            )
            raise ProviderRequestError("Twilio Voice", str(error)) from error

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"raw_text": response.text}

        call_sid = response_payload.get("sid") if isinstance(response_payload, dict) else None
        if not isinstance(call_sid, str) or not call_sid:
            raise ProviderRequestError(
                "Twilio Voice",
                "A resposta do provedor nao trouxe o Call SID da ligacao.",
            )

        provider_status = None
        if isinstance(response_payload, dict):
            status_value = response_payload.get("status")
            if isinstance(status_value, str) and status_value:
                provider_status = status_value

        logger.info(
            "Twilio retornou chamada criada | batch_id=%s external_id=%s provider_call_id=%s provider_status=%s",
            batch_id,
            external_id,
            call_sid,
            provider_status,
        )
        return TwilioCallDispatchResult(
            provider_call_id=call_sid,
            provider_status=provider_status,
            raw_payload=response_payload if isinstance(response_payload, dict) else {},
        )

    def _extract_provider_error_code(self, response_body: str) -> str | None:
        try:
            payload = json.loads(response_body)
        except (TypeError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None

        code = payload.get("code")
        if code is None:
            return None
        return str(code)

    def end_outbound_call(self, *, provider_call_id: str) -> None:
        self._ensure_configured()
        logger.warning(
            "Solicitando encerramento de chamada ativa no Twilio | provider_call_id=%s",
            provider_call_id,
        )
        call_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls/{provider_call_id}.json"
        )

        try:
            response = httpx.post(
                call_url,
                data={"Status": "completed"},
                auth=(self.account_sid or "", self.auth_token or ""),
                timeout=20.0,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            response_body = error.response.text
            logger.exception(
                "Twilio retornou erro HTTP ao encerrar chamada ativa | provider_call_id=%s status_code=%s response_body=%s",
                provider_call_id,
                error.response.status_code,
                response_body,
            )
            raise ProviderRequestError(
                "Twilio Voice",
                (
                    "Twilio retornou erro ao encerrar a ligacao ativa. "
                    f"status_code={error.response.status_code} response_body={response_body}"
                ),
            ) from error
        except httpx.HTTPError as error:
            logger.exception(
                "Erro HTTP ao encerrar chamada ativa no Twilio | provider_call_id=%s error=%s",
                provider_call_id,
                error,
            )
            raise ProviderRequestError("Twilio Voice", str(error)) from error

        logger.info(
            "Twilio confirmou encerramento da chamada ativa | provider_call_id=%s",
            provider_call_id,
        )

    def build_voice_twiml(
        self,
        *,
        batch_id: str,
        external_id: str,
        attempt_number: str,
        caller_company_name: str | None,
        client_name: str,
        cnpj: str,
        phone_dialed: str,
        twiml_mode: TwimlMode = "media_stream",
        realtime_model: str | None = None,
        realtime_voice: str | None = None,
        realtime_output_speed: str | None = None,
        realtime_style_profile: str | None = None,
    ) -> str:
        logger.info(
            "Montando TwiML da chamada | batch_id=%s external_id=%s twiml_mode=%s",
            batch_id,
            external_id,
            twiml_mode,
        )
        if twiml_mode == "diagnostic_say":
            return self._build_diagnostic_say_twiml(
                client_name=client_name,
                phone_dialed=phone_dialed,
            )

        stream_url = self.build_media_stream_url()
        logger.info(
            "Montando TwiML para media stream | batch_id=%s external_id=%s stream_url=%s",
            batch_id,
            external_id,
            stream_url,
        )
        parameters = {
            "batch_id": batch_id,
            "external_id": external_id,
            "attempt_number": attempt_number,
            "caller_company_name": caller_company_name or "",
            "client_name": client_name,
            "cnpj": cnpj,
            "phone_dialed": self._format_e164(phone_dialed),
        }
        if realtime_model:
            parameters["realtime_model"] = realtime_model
        if realtime_voice:
            parameters["realtime_voice"] = realtime_voice
        if realtime_output_speed:
            parameters["realtime_output_speed"] = realtime_output_speed
        if realtime_style_profile:
            parameters["realtime_style_profile"] = realtime_style_profile
        parameters_xml = "".join(
            (
                f'<Parameter name="{escape(key)}" value="{escape(value)}" />'
            )
            for key, value in parameters.items()
            if value
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Connect>"
            f'<Stream url="{escape(stream_url)}">{parameters_xml}</Stream>'
            "</Connect>"
            "</Response>"
        )

    def build_media_stream_url(self) -> str:
        self._ensure_webhook_base_url()
        assert self.webhook_base_url is not None
        if self.webhook_base_url.startswith("https://"):
            websocket_base_url = "wss://" + self.webhook_base_url[len("https://") :]
        elif self.webhook_base_url.startswith("http://"):
            websocket_base_url = "ws://" + self.webhook_base_url[len("http://") :]
        else:
            websocket_base_url = self.webhook_base_url
        return f"{websocket_base_url}/webhooks/twilio/voice/media-stream"

    def _build_https_url(self, path: str, **query: str) -> str:
        self._ensure_webhook_base_url()
        assert self.webhook_base_url is not None
        query_string = urlencode(query)
        return (
            f"{self.webhook_base_url}{path}?{query_string}"
            if query_string
            else f"{self.webhook_base_url}{path}"
        )

    def _build_diagnostic_say_twiml(self, *, client_name: str, phone_dialed: str) -> str:
        logger.info(
            "Montando TwiML diagnostico com voz nativa do Twilio | client_name=%s phone_dialed=%s",
            client_name,
            phone_dialed,
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            '<Say language="pt-BR" voice="alice">'
            "Ola. Este e um teste de diagnostico do Twilio para validar o endpoint de voz da API."
            "</Say>"
            '<Pause length="1"/>'
            '<Say language="pt-BR" voice="alice">'
            f"Se voce ouviu esta mensagem, a chamada chegou ao TwiML corretamente para o cliente {escape(client_name or 'sem nome')}."
            "</Say>"
            "<Hangup/>"
            "</Response>"
        )

    def _ensure_webhook_base_url(self) -> None:
        if self.webhook_base_url:
            return
        raise ProviderConfigurationError(
            "Twilio Voice",
            "defina TWILIO_WEBHOOK_BASE_URL para montar as rotas publicas do provedor.",
        )

    def _ensure_configured(self) -> None:
        if self.is_configured():
            return
        raise ProviderConfigurationError(
            "Twilio Voice",
            "defina TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER e TWILIO_WEBHOOK_BASE_URL.",
        )

    def _format_e164(self, phone: str | None) -> str:
        digits = "".join(character for character in str(phone or "") if character.isdigit())
        if not digits:
            return ""
        return digits if digits.startswith("+") else f"+{digits}"
