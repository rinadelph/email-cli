"""Pydantic models for accounts and emails."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Account(BaseModel):
    """An email account configuration."""
    name: str = Field(..., description="User-defined alias for this account")
    email: str = Field(..., description="Email address")
    imap_host: str = Field(default="imap.gmail.com", description="IMAP server hostname")
    imap_port: int = Field(default=993, description="IMAP server port")
    smtp_host: str = Field(default="smtp.gmail.com", description="SMTP server hostname")
    smtp_port: int = Field(default=465, description="SMTP server port")
    use_ssl: bool = Field(default=True, description="Use SSL/TLS connections")


class EmailMessage(BaseModel):
    """A simplified email message representation."""
    uid: str = Field(..., description="IMAP UID")
    subject: str = Field(default="", description="Email subject")
    sender: str = Field(default="", description="From address")
    to: str = Field(default="", description="To address")
    date: Optional[datetime] = Field(default=None, description="Parsed date")
    raw_date: str = Field(default="", description="Raw date string from headers")
    body_preview: str = Field(default="", description="First ~200 chars of text body")
    flags: list[str] = Field(default_factory=list, description="IMAP flags")
    size: int = Field(default=0, description="Message size in bytes")
    has_attachments: bool = Field(default=False, description="Whether MIME parts indicate attachments")


class AttachmentInfo(BaseModel):
    """Info about an email attachment."""
    filename: str = Field(..., description="Attachment filename")
    content_type: str = Field(default="application/octet-stream", description="MIME type")
    size: int = Field(default=0, description="Approximate size in bytes")
