# Agent Setup Guide for email-cli

This guide is for AI agents and automation scripts to set up and use the email CLI.

## Quick Setup

### Option 1: Interactive (with prompts)

```bash
email accounts add work work@gmail.com
# Enter app-password when prompted
```

### Option 2: Non-interactive (for scripts/agents)

```bash
# Via environment variable
export EMAIL_PASSWORD="your-app-password"
email accounts add work work@gmail.com --non-interactive

# Via password file
echo "your-app-password" > /tmp/pw.txt
email accounts add work work@gmail.com --password-file /tmp/pw.txt --non-interactive

# Via command-line flag (less secure, visible in process list)
email accounts add work work@gmail.com --password "your-app-password" --non-interactive
```

### Option 3: Custom provider (not Gmail)

```bash
export EMAIL_PASSWORD="your-password"
export EMAIL_IMAP_HOST="imap.outlook.com"
export EMAIL_SMTP_HOST="smtp.outlook.com"
email accounts add outlook me@outlook.com --non-interactive
```

## Agent Workflow: Reading Emails

```bash
# 1. Set output format for parsing
export EMAIL_FORMAT="json"

# 2. List recent emails
email list --limit 5
# → JSON array of emails: uid, subject, sender, date, has_attachments, etc.

# 3. Search for a specific email
email search "invoice" --limit 5
# → JSON array of matching emails

# 4. Show full email content and pipe body to a file
email show 12345 --body-file /tmp/email_body.txt
# → JSON with metadata; body written to /tmp/email_body.txt

# 5. Download PDF attachments
email attachments download 12345 --output ./downloads
# → JSON array of saved file paths
```

## Agent Workflow: Sending Emails

```bash
# Send with inline body
email send --to recipient@example.com --subject "Hello" --body "This is a test"

# Send with body from a file
email send --to recipient@example.com --subject "Report" --body-file report.txt --attach report.pdf

# Send to multiple recipients
email send --to a@example.com --to b@example.com --subject "All hands" --body "Meeting at 3pm"
```

## Multi-Account Example

```bash
# Add multiple accounts
email accounts add personal me@gmail.com --password-file /tmp/gmail_pw.txt --non-interactive
email accounts add work work@company.com --imap-host mail.company.com --smtp-host smtp.company.com --password-file /tmp/work_pw.txt --non-interactive

# Switch between accounts
email list --account personal --limit 10
email list --account work --folder "Sent" --limit 5
```

## Output Formats

| Format | Use Case |
|--------|----------|
| `table` | Human-readable (default) |
| `json` | Parse with `jq` or any JSON parser |
| `raw` | Tab-separated or simple text for `cut`, `awk`, `grep` |

Set globally:
```bash
export EMAIL_FORMAT=json
```

Or per-command:
```bash
email list --format json
email folders --format raw
```

## Common Agent Tasks

### Find the latest unread email

```bash
email list --unread --limit 1 --format json | jq '.[0].uid'
```

### Download all PDFs from the last 10 emails

```bash
mkdir -p ./downloads
for uid in $(email list --limit 10 --format raw | cut -f1); do
    email attachments download "$uid" --output ./downloads --format raw
done
```

### Search and save matching emails to files

```bash
email search "invoice" --format json | jq -r '.[] | "\(.uid) \(.subject)"'
```

### Read a specific email's body into a variable

```bash
email show 12345 --format raw --body-file /tmp/body.txt
BODY=$(cat /tmp/body.txt)
```

## Gmail App Passwords

For Gmail with 2FA enabled, you **must** use an App Password:

1. Go to https://myaccount.google.com/apppasswords
2. Generate a new app password
3. Use it as `EMAIL_PASSWORD` or `--password`

## Security Notes for Agents

- **Never** log the password to stdout or files
- Use `--password-file` with a temporary file that you delete immediately after
- The password is stored in the OS keyring (encrypted), never in plaintext in `accounts.json`
- For CI/headless environments without a keyring, the CLI falls back to file-based encryption
