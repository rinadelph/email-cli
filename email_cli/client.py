"""IMAP and SMTP client wrapper."""

import email
import imaplib
import socket
import smtplib
from datetime import datetime
from email.header import decode_header
from email.message import EmailMessage as StdEmailMessage
from pathlib import Path
from typing import Optional

from email_cli.models import Account, AttachmentInfo, EmailMessage


class EmailClient:
    """Wraps IMAP and SMTP connections for a single account."""

    def __init__(self, account: Account, password: str) -> None:
        self.account = account
        self.password = password
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._smtp: Optional[smtplib.SMTP_SSL] = None

    # -- IMAP --

    def imap_connect(self) -> None:
        """Open IMAP SSL connection and login."""
        self._imap = imaplib.IMAP4_SSL(
            host=self.account.imap_host,
            port=self.account.imap_port,
            timeout=30,
        )
        self._imap.login(self.account.email, self.password)

    def imap_disconnect(self) -> None:
        if self._imap:
            try:
                self._imap.close()
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    def select_folder(self, folder: str = "INBOX") -> None:
        if not self._imap:
            raise RuntimeError("IMAP not connected.")
        status, _ = self._imap.select(folder)
        if status != "OK":
            raise RuntimeError(f"Failed to select folder '{folder}'")

    def list_folders(self) -> list[str]:
        if not self._imap:
            raise RuntimeError("IMAP not connected.")
        status, folders = self._imap.list()
        if status != "OK" or not folders:
            return []
        names = []
        for f in folders:
            if isinstance(f, bytes):
                # Parse: b'(\\HasNoChildren) "/" "INBOX"'
                parts = f.decode("utf-8", errors="replace").rsplit(' "', 1)
                if len(parts) == 2:
                    name = parts[1].strip('"')
                    names.append(name)
        return names

    def search(
        self,
        criteria: str = "ALL",
        folder: str = "INBOX",
        limit: int = 20,
    ) -> list[EmailMessage]:
        self.select_folder(folder)
        status, data = self._imap.search(None, criteria)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        uids = uids[-limit:]  # newest first
        results: list[EmailMessage] = []
        for uid in reversed(uids):  # reverse so newest first
            msg = self._fetch_summary(uid.decode())
            if msg:
                results.append(msg)
        return results

    def _fetch_summary(self, uid: str) -> Optional[EmailMessage]:
        status, data = self._imap.fetch(uid.encode(), "(RFC822 FLAGS)")
        if status != "OK" or not data:
            return None
        raw_msg = None
        flags = []
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                raw_msg = part[1]
            elif isinstance(part, bytes) and b"FLAGS" in part:
                # Parse flags line: b'1 (FLAGS (\\Seen))'
                flags = self._parse_flags(part.decode())
        if raw_msg is None:
            return None
        msg = email.message_from_bytes(raw_msg)
        subject = self._decode_header_value(msg.get("Subject", ""))
        sender = self._decode_header_value(msg.get("From", ""))
        to = self._decode_header_value(msg.get("To", ""))
        raw_date = msg.get("Date", "")
        parsed_date = self._parse_date(raw_date)
        body_preview = self._extract_preview(msg)
        has_attachments = self._has_attachments(msg)
        size = len(raw_msg)
        return EmailMessage(
            uid=uid,
            subject=subject,
            sender=sender,
            to=to,
            date=parsed_date,
            raw_date=raw_date,
            body_preview=body_preview,
            flags=flags,
            size=size,
            has_attachments=has_attachments,
        )

    def fetch_full(self, uid: str) -> tuple[EmailMessage, email.message.Message]:
        """Fetch full raw message and return parsed model + message object."""
        if not self._imap:
            raise RuntimeError("IMAP not connected.")
        status, data = self._imap.fetch(uid.encode(), "(RFC822)")
        if status != "OK" or not data:
            raise RuntimeError(f"Failed to fetch message {uid}")
        raw_msg = None
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                raw_msg = part[1]
                break
        if raw_msg is None:
            raise RuntimeError(f"No message body for UID {uid}")
        msg = email.message_from_bytes(raw_msg)
        summary = self._fetch_summary(uid)
        if summary is None:
            raise RuntimeError(f"Failed to parse summary for UID {uid}")
        return summary, msg

    def list_attachments(self, uid: str) -> list[AttachmentInfo]:
        _, msg = self.fetch_full(uid)
        attachments: list[AttachmentInfo] = []
        for part in msg.walk():
            cdisp = part.get_content_disposition() or ""
            filename = part.get_filename()
            if filename or "attachment" in cdisp:
                filename = filename or "unnamed"
                filename = self._decode_header_value(filename)
                size = len(part.get_payload(decode=True) or b"")
                attachments.append(
                    AttachmentInfo(
                        filename=filename,
                        content_type=part.get_content_type(),
                        size=size,
                    )
                )
        return attachments

    def download_attachments(
        self, uid: str, output_dir: Path
    ) -> list[Path]:
        _, msg = self.fetch_full(uid)
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []
        for part in msg.walk():
            cdisp = part.get_content_disposition() or ""
            filename = part.get_filename()
            if filename or "attachment" in cdisp:
                filename = filename or "unnamed"
                filename = self._decode_header_value(filename)
                payload = part.get_payload(decode=True) or b""
                dest = output_dir / filename
                # Avoid overwrite by appending number
                counter = 1
                stem = dest.stem
                suffix = dest.suffix
                while dest.exists():
                    dest = output_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                with open(dest, "wb") as f:
                    f.write(payload)
                downloaded.append(dest)
        return downloaded

    # -- SMTP --

    def smtp_connect(self) -> None:
        self._smtp = smtplib.SMTP_SSL(
            host=self.account.smtp_host,
            port=self.account.smtp_port,
            timeout=30,
        )
        self._smtp.ehlo()
        self._smtp.login(self.account.email, self.password)

    def smtp_disconnect(self) -> None:
        if self._smtp:
            try:
                self._smtp.close()
            except Exception:
                pass
            self._smtp = None

    def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        attachments: Optional[list[Path]] = None,
    ) -> None:
        if not self._smtp:
            raise RuntimeError("SMTP not connected.")
        msg = StdEmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.account.email
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if attachments:
            msg.make_mixed()
            text_part = StdEmailMessage()
            text_part.set_content(body)
            msg.attach(text_part)
            for path in attachments:
                with open(path, "rb") as f:
                    data = f.read()
                ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=path.name,
                )
        else:
            msg.set_content(body)

        all_recipients = to[:]
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)
        self._smtp.send_message(msg, to_addrs=all_recipients)

    # -- Helpers --

    @staticmethod
    def _decode_header_value(value: str) -> str:
        parts = decode_header(value)
        result = []
        for text, charset in parts:
            if isinstance(text, bytes):
                try:
                    result.append(text.decode(charset or "utf-8", errors="replace"))
                except (LookupError, TypeError):
                    result.append(text.decode("utf-8", errors="replace"))
            else:
                result.append(text)
        return "".join(result)

    @staticmethod
    def _parse_date(raw: str) -> Optional[datetime]:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(raw)
        except Exception:
            return None

    @staticmethod
    def _extract_preview(msg: email.message.Message, length: int = 200) -> str:
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        text = payload.decode("utf-8", errors="replace")
                    except Exception:
                        text = payload.decode("ascii", errors="replace")
                    return text.replace("\n", " ").replace("\r", "")[:length]
        return ""

    @staticmethod
    def _has_attachments(msg: email.message.Message) -> bool:
        for part in msg.walk():
            cdisp = part.get_content_disposition() or ""
            if part.get_filename() or "attachment" in cdisp:
                return True
        return False

    @staticmethod
    def _parse_flags(line: str) -> list[str]:
        # e.g. '1 (FLAGS (\\Seen \\Recent))'
        flags = []
        if "FLAGS" in line:
            start = line.find("(")
            end = line.rfind(")")
            if start != -1 and end != -1:
                inner = line[start + 1 : end]
                # inner = 'FLAGS (\\Seen \\Recent)'
                parts = inner.split()
                for p in parts:
                    p = p.strip()
                    if p.startswith("\\"):
                        flags.append(p)
        return flags
