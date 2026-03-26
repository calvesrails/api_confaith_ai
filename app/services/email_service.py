from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from ..schemas.email_delivery import EmailSendResult

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(
        self,
        *,
        host: str | None,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        from_address: str | None,
        from_name: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address
        self.from_name = from_name

    def is_configured(self) -> bool:
        return bool(self.host and self.from_address)

    def send_validation_fallback_email(
        self,
        *,
        recipient_email: str,
        client_name: str,
        cnpj: str,
        phone: str,
        caller_company_name: str | None = None,
    ) -> EmailSendResult:
        sender_label = caller_company_name or self.from_name
        subject = f"Validacao cadastral da empresa {client_name}"
        message_body = (
            f"Ola,\n\n"
            f"Nao conseguimos concluir a validacao por ligacao da empresa {client_name}.\n"
            f"CNPJ: {cnpj}\n"
            f"Telefone em validacao: {phone}\n\n"
            f"Por favor, confirme por este canal se o numero pertence a empresa.\n"
            f"Responda a este e-mail com SIM ou NAO.\n\n"
            f"Atenciosamente,\n"
            f"{sender_label}"
        )

        if not self.is_configured():
            logger.warning(
                "SMTP nao configurado para envio de fallback por e-mail | recipient_email=%s",
                recipient_email,
            )
            return EmailSendResult(
                success=False,
                subject=subject,
                message_body=message_body,
                error_message=(
                    "SMTP nao configurado. Defina SMTP_HOST e SMTP_FROM_ADDRESS no .env."
                ),
            )

        provider_message_id = make_msgid(domain=(self.from_address or "localhost").split("@")[-1])
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.from_name} <{self.from_address}>"
        message["To"] = recipient_email
        message["Message-ID"] = provider_message_id
        message.set_content(message_body)

        logger.info(
            "Enviando fallback por e-mail | recipient_email=%s smtp_host=%s smtp_port=%s",
            recipient_email,
            self.host,
            self.port,
        )
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.send_message(message)
        except OSError as error:
            logger.exception(
                "Falha ao enviar fallback por e-mail | recipient_email=%s error=%s",
                recipient_email,
                error,
            )
            return EmailSendResult(
                success=False,
                provider_message_id=provider_message_id,
                subject=subject,
                message_body=message_body,
                error_message=f"Erro ao enviar e-mail: {error}",
            )

        logger.info(
            "Fallback por e-mail enviado com sucesso | recipient_email=%s provider_message_id=%s",
            recipient_email,
            provider_message_id,
        )
        return EmailSendResult(
            success=True,
            provider_message_id=provider_message_id,
            subject=subject,
            message_body=message_body,
        )
