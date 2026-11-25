"""Actionable, sanitized errors shared by mail transport, batches, and UI."""
import re


class GmailAuthError(RuntimeError):
    """Google rejected authorization before the requested Gmail operation."""


AUTH_MESSAGE = ("Gmail authorization expired or was revoked (invalid_grant). "
                "Reconnect Gmail using the sending account, then test the connection again. "
                "No automatic retry was made.")


def leaves(error):
    children = getattr(error, "exceptions", ())
    return [item for child in children for item in leaves(child)] if children else [error]


def is_auth_error(error):
    return any(isinstance(item, GmailAuthError) or "invalid_grant" in str(item).lower() for item in leaves(error))


def mail_error_message(error):
    if is_auth_error(error):
        return AUTH_MESSAGE
    messages = []
    for item in leaves(error):
        value = str(item).strip() or type(item).__name__
        value = re.sub(r'https?://\S+', '[URL omitted]', value)
        value = re.sub(r'(?i)(access_token|refresh_token|client_secret|authorization)([\s"\x27:=]+)[^\s,}\]]+',
                       r'\1=[redacted]', value)
        if value not in messages:
            messages.append(value[:350])
    return "; ".join(messages[:3])
