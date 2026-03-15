from __future__ import annotations

import logging
from typing import Any

import httpx

from ..schemas.test_flow import WhatsAppSendResult

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(
        self,
        *,
        access_token: str | None,
        phone_number_id: str | None,
        api_version: str,
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version

    async def send_text_message(self, phone: str, message: str) -> WhatsAppSendResult:
        logger.info("Preparando envio de WhatsApp | phone=%s", phone)
        request_payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message},
        }

        if not self.access_token or not self.phone_number_id:
            logger.warning("Meta WhatsApp nao configurado para envio | phone=%s", phone)
            return WhatsAppSendResult(
                meta_http_status=0,
                success=False,
                request_payload=request_payload,
                error_message=(
                    "Meta WhatsApp nao configurado. Defina META_ACCESS_TOKEN "
                    "e META_PHONE_NUMBER_ID no .env."
                ),
            )

        request_url = (
            f"https://graph.facebook.com/{self.api_version}/"
            f"{self.phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Enviando mensagem para Meta Cloud API | phone=%s api_version=%s",
            phone,
            self.api_version,
        )
        try:
            response = await self._post_to_meta(
                request_url,
                headers=headers,
                payload=request_payload,
            )
        except httpx.HTTPError as error:
            logger.exception("Erro ao chamar Meta Cloud API | phone=%s error=%s", phone, error)
            return WhatsAppSendResult(
                meta_http_status=0,
                success=False,
                request_payload=request_payload,
                error_message=f"Erro ao chamar a Meta Cloud API: {error}",
            )

        response_payload = self._safe_json(response)
        meta_message_id = self._extract_message_id(response_payload)
        success = response.is_success and meta_message_id is not None

        logger.info(
            "Resultado envio WhatsApp | phone=%s success=%s meta_http_status=%s meta_message_id=%s",
            phone,
            success,
            response.status_code,
            meta_message_id,
        )
        return WhatsAppSendResult(
            meta_http_status=response.status_code,
            success=success,
            request_payload=request_payload,
            response_payload=response_payload,
            meta_message_id=meta_message_id,
            error_message=None if success else self._extract_error_message(response_payload),
        )

    async def _post_to_meta(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.post(url, headers=headers, json=payload)

    def _safe_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}

        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _extract_message_id(self, payload: dict[str, Any]) -> str | None:
        messages = payload.get("messages")
        if isinstance(messages, list) and messages:
            first_message = messages[0]
            if isinstance(first_message, dict):
                message_id = first_message.get("id")
                if isinstance(message_id, str) and message_id:
                    return message_id
        return None

    def _extract_error_message(self, payload: dict[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        return "A Meta Cloud API retornou erro ao enviar a mensagem."
