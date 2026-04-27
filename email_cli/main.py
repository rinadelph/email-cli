"""CLI entry point using Typer — agent-friendly with JSON/raw modes, field filtering, and notes."""

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.prompt import Confirm, Prompt

from email_cli.client import EmailClient
from email_cli.config import (
    add_account,
    get_account,
    get_password,
    list_account_names,
    load_accounts,
    remove_account,
    set_default_account,
    store_password,
)
from email_cli.formatter import (
    OutputFormat,
    print_attachments,
    print_downloaded,
    print_email_detail,
    print_emails,
    print_error,
    print_folders,
    print_success,
)
from email_cli.models import Account
from email_cli.notes import (
    add_note,
    get_notes,
    remove_note,
)
from email_cli.utils import resolve_account_name

app = typer.Typer(help="email-cli: Multi-account email CLI via IMAP/SMTP")

accounts_app = typer.Typer(help="Manage email accounts")
app.add_typer(accounts_app, name="accounts")

attachments_app = typer.Typer(help="List or download attachments")
app.add_typer(attachments_app, name="attachments")

notes_app = typer.Typer(help="Agent notes and reminders")
app.add_typer(notes_app, name="notes")


def _get_client(name: Optional[str]) -> EmailClient:
    account_name = resolve_account_name(name)
    account = get_account(account_name)
    if not account:
        raise RuntimeError(f"Account '{account_name}' not found.")
    password = get_password(account_name)
    if not password:
        raise RuntimeError(f"No stored password for account '{account_name}'.")
    client = EmailClient(account, password)
    return client


def _fmt_opt() -> OutputFormat:
    """Resolve output format from env or default to table."""
    env = os.environ.get("EMAIL_FORMAT", "table").lower()
    if env in ("json", "raw"):
        return OutputFormat(env)
    return OutputFormat.TABLE


def _compact_opt() -> bool:
    return os.environ.get("EMAIL_COMPACT", "0").lower() in ("1", "true", "yes")


def _fields_opt() -> Optional[list[str]]:
    env = os.environ.get("EMAIL_FIELDS", "").strip()
    if env:
        return [f.strip() for f in env.split(",")]
    return None


# -- Accounts commands --

@accounts_app.command("add")
def accounts_add(
    name: str = typer.Argument(..., help="Alias for this account"),
    email: str = typer.Argument(..., help="Email address"),
    imap_host: str = typer.Option("imap.gmail.com", help="IMAP server host"),
    imap_port: int = typer.Option(993, help="IMAP server port"),
    smtp_host: str = typer.Option("smtp.gmail.com", help="SMTP server host"),
    smtp_port: int = typer.Option(465, help="SMTP server port"),
    password: Optional[str] = typer.Option(None, help="Password/app-password. Prompted if omitted."),
    password_file: Optional[Path] = typer.Option(None, help="Read password from file (for automation)"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Fail instead of prompting"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Add a new email account. Supports env vars EMAIL_PASSWORD and EMAIL_*_HOST."""
    password = password or os.environ.get("EMAIL_PASSWORD")
    imap_host = os.environ.get("EMAIL_IMAP_HOST", imap_host)
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", smtp_host)

    if not password and password_file:
        try:
            password = password_file.read_text().strip()
        except Exception as exc:
            print_error(f"Failed to read password file: {exc}", fmt, compact)
            raise typer.Exit(1)

    if not password:
        if non_interactive:
            print_error("Password required (use --password, --password-file, or EMAIL_PASSWORD env var).", fmt, compact)
            raise typer.Exit(1)
        password = Prompt.ask(f"Password for {email}", password=True)

    account = Account(
        name=name,
        email=email,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )

    try:
        client = EmailClient(account, password)
        client.imap_connect()
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Failed to connect: {exc}", fmt, compact)
        raise typer.Exit(1)

    add_account(account)
    store_password(name, password)
    print_success(f"Account '{name}' added successfully.", fmt, compact)


@accounts_app.command("list")
def accounts_list(
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """List configured accounts."""
    data = load_accounts()
    default = data.get("default")
    accounts = data.get("accounts", [])
    if not accounts:
        if fmt != OutputFormat.RAW:
            print_error("No accounts configured.", fmt, compact)
        raise typer.Exit(1)
    if fmt == OutputFormat.JSON:
        import json, sys
        json.dump({"default": default, "accounts": accounts}, sys.stdout, indent=None if compact else 2, ensure_ascii=False)
        print()
        return
    if fmt == OutputFormat.RAW:
        for acc in accounts:
            is_default = "*" if acc["name"] == default else ""
            print(f"{is_default}\t{acc['name']}\t{acc['email']}")
        return
    for acc in accounts:
        marker = " (default)" if acc["name"] == default else ""
        rprint(f"[cyan]{acc['name']}[/cyan]: {acc['email']}{marker}")


@accounts_app.command("remove")
def accounts_remove(
    name: str = typer.Argument(..., help="Account alias to remove"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Remove an account."""
    if not yes and _fmt_opt() == OutputFormat.TABLE:
        if not Confirm.ask(f"Remove account '{name}'?"):
            raise typer.Exit(0)
    try:
        remove_account(name)
        print_success(f"Account '{name}' removed.", fmt, compact)
    except ValueError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)


@accounts_app.command("set-default")
def accounts_set_default(
    name: str = typer.Argument(..., help="Account alias to set as default"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Set the default account."""
    try:
        set_default_account(name)
        print_success(f"Default account set to '{name}'.", fmt, compact)
    except ValueError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)


# -- Folders --

@app.command("folders")
def folders(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """List IMAP folders."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    try:
        client.imap_connect()
        folders = client.list_folders()
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)
    print_folders(folders, fmt, compact)


# -- List emails --

@app.command("list")
def list_emails(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    folder: str = typer.Option("INBOX", help="IMAP folder"),
    limit: int = typer.Option(20, help="Max emails to show"),
    unread: bool = typer.Option(False, help="Only unread emails"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
    fields: Optional[list[str]] = typer.Option(_fields_opt(), help="Fields to include (comma-separated)"),
) -> None:
    """List emails in a folder."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    criteria = "UNSEEN" if unread else "ALL"
    try:
        client.imap_connect()
        emails = client.search(criteria=criteria, folder=folder, limit=limit)
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)

    if not emails:
        if fmt != OutputFormat.RAW:
            print_error("No emails found.", fmt, compact)
        raise typer.Exit(0)
    print_emails(emails, fmt, compact, fields)


# -- Search emails --

@app.command("search")
def search_emails(
    query: str = typer.Argument(..., help="Search string"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    folder: str = typer.Option("INBOX", help="IMAP folder"),
    limit: int = typer.Option(20, help="Max results"),
    in_field: Optional[str] = typer.Option(None, "--in", help="Search only in field: subject|from|to|body"),
    since: Optional[str] = typer.Option(None, help="Only emails since date (YYYY-MM-DD)"),
    before: Optional[str] = typer.Option(None, help="Only emails before date (YYYY-MM-DD)"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
    fields: Optional[list[str]] = typer.Option(_fields_opt(), help="Fields to include (comma-separated)"),
) -> None:
    """Search emails by subject, sender, recipient, or body text."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)

    # Build IMAP search criteria
    imap_criteria = ["ALL"]
    if since:
        try:
            d = datetime.strptime(since, "%Y-%m-%d")
            imap_criteria.append(f"SINCE {d.strftime('%d-%b-%Y')}")
        except ValueError:
            print_error(f"Invalid since date: {since}. Use YYYY-MM-DD.", fmt, compact)
            raise typer.Exit(1)
    if before:
        try:
            d = datetime.strptime(before, "%Y-%m-%d")
            imap_criteria.append(f"BEFORE {d.strftime('%d-%b-%Y')}")
        except ValueError:
            print_error(f"Invalid before date: {before}. Use YYYY-MM-DD.", fmt, compact)
            raise typer.Exit(1)

    criteria_str = " ".join(imap_criteria)

    try:
        client.imap_connect()
        emails = client.search(criteria=criteria_str, folder=folder, limit=200)
        query_lower = query.lower()
        filtered = []
        for e in emails:
            # Field-specific search
            if in_field == "subject":
                match = query_lower in e.subject.lower()
            elif in_field == "from":
                match = query_lower in e.sender.lower()
            elif in_field == "to":
                match = query_lower in e.to.lower()
            elif in_field == "body":
                match = query_lower in e.body_preview.lower()
            else:
                # Search all fields
                match = (
                    query_lower in e.subject.lower()
                    or query_lower in e.sender.lower()
                    or query_lower in e.to.lower()
                    or query_lower in e.body_preview.lower()
                )
            if match:
                filtered.append(e)
        filtered = filtered[:limit]
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)

    if not filtered:
        if fmt != OutputFormat.RAW:
            print_error("No emails matched.", fmt, compact)
        raise typer.Exit(0)
    print_emails(filtered, fmt, compact, fields)


# -- Show email --

@app.command("show")
def show_email(
    uid: str = typer.Argument(..., help="Email UID"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    folder: str = typer.Option("INBOX", help="IMAP folder"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
    body_file: Optional[str] = typer.Option(None, help="Write body to a file"),
    fields: Optional[list[str]] = typer.Option(_fields_opt(), help="Fields to include (comma-separated)"),
) -> None:
    """Show full email content."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    try:
        client.imap_connect()
        client.select_folder(folder)
        summary, msg = client.fetch_full(uid)
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)

    print_email_detail(summary, body, fmt, body_file=body_file, compact=compact, fields=fields)


# -- Attachments commands --

@attachments_app.command("list")
def attachments_list(
    uid: str = typer.Argument(..., help="Email UID"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    folder: str = typer.Option("INBOX", help="IMAP folder"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """List attachments for an email."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    try:
        client.imap_connect()
        client.select_folder(folder)
        attachments = client.list_attachments(uid)
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)

    if not attachments:
        if fmt != OutputFormat.RAW:
            print_error("No attachments found.", fmt, compact)
        raise typer.Exit(0)
    print_attachments(attachments, fmt, compact)


@attachments_app.command("download")
def attachments_download(
    uid: str = typer.Argument(..., help="Email UID"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    folder: str = typer.Option("INBOX", help="IMAP folder"),
    output: Path = typer.Option(Path("."), help="Output directory"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Download all attachments from an email."""
    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    try:
        client.imap_connect()
        client.select_folder(folder)
        paths = client.download_attachments(uid, output)
        client.imap_disconnect()
    except Exception as exc:
        print_error(f"Error: {exc}", fmt, compact)
        raise typer.Exit(1)

    if not paths:
        if fmt != OutputFormat.RAW:
            print_error("No attachments found.", fmt, compact)
        raise typer.Exit(0)
    print_downloaded(paths, fmt, compact)


# -- Send email --

@app.command("send")
def send_email(
    to: list[str] = typer.Option([], help="Recipient email address(es)"),
    subject: str = typer.Option(..., help="Email subject"),
    body: Optional[str] = typer.Option(None, help="Email body text"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account alias"),
    cc: Optional[list[str]] = typer.Option(None, help="CC addresses"),
    bcc: Optional[list[str]] = typer.Option(None, help="BCC addresses"),
    attach: Optional[list[Path]] = typer.Option(None, help="File(s) to attach"),
    body_file: Optional[Path] = typer.Option(None, help="Read body from file"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Send an email."""
    if not to:
        print_error("At least one --to recipient is required.", fmt, compact)
        raise typer.Exit(1)
    if body_file:
        try:
            body = body_file.read_text()
        except Exception as exc:
            print_error(f"Failed to read body file: {exc}", fmt, compact)
            raise typer.Exit(1)
    if body is None:
        body = typer.prompt("Email body", default="")

    try:
        client = _get_client(account)
    except RuntimeError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)
    try:
        client.smtp_connect()
        client.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc or [],
            bcc=bcc or [],
            attachments=attach,
        )
        client.smtp_disconnect()
    except Exception as exc:
        print_error(f"Failed to send: {exc}", fmt, compact)
        raise typer.Exit(1)

    print_success("Email sent successfully.", fmt, compact)


# -- Notes commands --

@notes_app.command("add")
def notes_add(
    message: str = typer.Argument(..., help="Note text to store"),
    tag: Optional[str] = typer.Option(None, help="Optional tag/category"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Add a note/reminder for agents."""
    note = add_note(message, tag=tag)
    print_success(f"Note #{note['id']} added.", fmt, compact)


@notes_app.command("list")
def notes_list(
    tag: Optional[str] = typer.Option(None, help="Filter by tag"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """List agent notes/reminders."""
    notes = get_notes(tag=tag)
    if not notes:
        if fmt != OutputFormat.RAW:
            print_error("No notes found.", fmt, compact)
        raise typer.Exit(0)
    if fmt == OutputFormat.JSON:
        import json, sys
        json.dump(notes, sys.stdout, indent=None if compact else 2, ensure_ascii=False)
        print()
        return
    if fmt == OutputFormat.RAW:
        for n in notes:
            tag_str = n.get("tag", "")
            print(f"{n['id']}\t{n['created']}\t{tag_str}\t{n['message']}")
        return
    from rich.table import Table
    table = Table(title="Agent Notes")
    table.add_column("#", style="cyan")
    table.add_column("Date", style="magenta")
    table.add_column("Tag", style="green")
    table.add_column("Message", style="white")
    for n in notes:
        table.add_row(str(n["id"]), n["created"], n.get("tag", ""), n["message"])
    console = Console()
    console.print(table)


@notes_app.command("remove")
def notes_remove(
    note_id: int = typer.Argument(..., help="Note ID to remove"),
    fmt: OutputFormat = typer.Option(_fmt_opt(), "--format", help="Output format"),
    compact: bool = typer.Option(_compact_opt(), "--compact", help="Compact JSON output"),
) -> None:
    """Remove a note by ID."""
    try:
        remove_note(note_id)
        print_success(f"Note #{note_id} removed.", fmt, compact)
    except ValueError as exc:
        print_error(str(exc), fmt, compact)
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
