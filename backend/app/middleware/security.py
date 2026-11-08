import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("tarkapp.security")


def mask_device_id(device_id: str) -> str:
    """
    Masks a device identifier to preserve user privacy while allowing debugging:
    Leaves only the first 4 and last 4 characters (e.g. 'dev-test-device-0001' -> 'dev-...0001').
    """
    clean = str(device_id or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "****"
    return f"{clean[:4]}...{clean[-4:]}"


def sanitize_log_message(msg: str) -> str:
    """
    Sanitizes log messages, query strings, headers, and payloads:
    1. Replaces binary Base64 image payloads with human-readable size labels '[image: 245 KB]'
    2. Masks X-Device-ID to first 4 and last 4 characters ('abcd...1234')
    3. Fully masks license keys ('TARK-****-****'), auth tokens ('[TOKEN_MASKED]'),
       and Telegram webhook / admin secrets ('[SECRET_MASKED]').
    """
    if not msg or not isinstance(msg, str):
        return str(msg)

    sanitized = msg

    # 1. Base64 Data URIs
    def replace_data_uri(m: re.Match) -> str:
        b64_content = m.group(1)
        kb = max(1, round(len(b64_content) * 3 / 4 / 1024))
        return f"[image: {kb} KB]"

    sanitized = re.sub(
        r"data:image/[a-zA-Z0-9.+_-]+;base64,([A-Za-z0-9+/=]{40,})",
        replace_data_uri,
        sanitized,
    )

    # 2. JSON Base64 fields ("images_base64", "image_base64", "base64")
    def replace_b64_json_field(m: re.Match) -> str:
        prefix = m.group(1)
        b64_content = m.group(2)
        suffix = m.group(3)
        kb = max(1, round(len(b64_content) * 3 / 4 / 1024))
        return f"{prefix}[image: {kb} KB]{suffix}"

    sanitized = re.sub(
        r'("(?:images?_base64|base64|image)":\s*"?)(?:data:image/[^;]+;base64,)?([A-Za-z0-9+/=]{40,})("?)',
        replace_b64_json_field,
        sanitized,
    )

    # 3. Standalone long Base64 strings (>= 120 characters)
    def replace_standalone_b64(m: re.Match) -> str:
        chunk = m.group(0)
        kb = max(1, round(len(chunk) * 3 / 4 / 1024))
        return f"[image: {kb} KB]"

    sanitized = re.sub(
        r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{120,}={0,2}(?![A-Za-z0-9+/=])",
        replace_standalone_b64,
        sanitized,
    )

    # 4. Mask X-Device-ID in headers, strings, and query parameters
    def replace_device_header(m: re.Match) -> str:
        prefix = m.group(1)
        dev = m.group(2)
        return f"{prefix}{mask_device_id(dev)}"

    sanitized = re.sub(
        r"(X-Device-ID[\'\":\s=]+)([a-zA-Z0-9_\-]{8,})",
        replace_device_header,
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(device_id[\'\":\s=]+[\'\"]?)([a-zA-Z0-9_\-]{8,})([\'\"]?)",
        lambda m: f"{m.group(1)}{mask_device_id(m.group(2))}{m.group(3)}",
        sanitized,
        flags=re.IGNORECASE,
    )

    # 5. Mask License Keys
    sanitized = re.sub(
        r"\bTARK-[A-Z0-9]{4}-[A-Z0-9]{4}\b",
        "TARK-****-****",
        sanitized,
    )
    sanitized = re.sub(
        r'("(?:key_code|license_key|activated_key)":\s*")[^"]+(")',
        r"\1[KEY_MASKED]\2",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"((?:license_key|key_code|activated_key)=)[^&\s,]+",
        r"\1[KEY_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # 6. Mask Auth Tokens
    sanitized = re.sub(
        r"Bearer\s+[A-Za-z0-9_\-\.]{8,}",
        "Bearer [TOKEN_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(X-Auth-Token[\'\":\s=]+)[^\s,}\'\"]+",
        r"\1[TOKEN_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # 7. Mask Webhook & Admin Secrets
    sanitized = re.sub(
        r"(X-Telegram-Bot-Api-Secret-Token[\'\":\s=]+)[^\s,}\'\"]+",
        r"\1[SECRET_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(X-Admin-Secret[\'\":\s=]+)[^\s,}\'\"]+",
        r"\1[SECRET_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"((?:admin_secret|webhook_secret|secret_token)=)[^&\s,]+",
        r"\1[SECRET_MASKED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    return sanitized


class SensitiveDataLoggingFilter(logging.Filter):
    """
    Logging Filter that intercepts all outgoing LogRecord messages and arguments
    and strips PII (Device IDs), license keys, auth tokens, secrets, and large image base64 strings.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)

        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_log_message(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (sanitize_log_message(str(v)) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }

        return True


class SecurityHeadersMiddleware:
    """
    Pure ASGI middleware that injects modern HTTP security headers to all outgoing responses:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: geolocation=(), camera=(), microphone=()
    """

    SECURITY_HEADERS: Tuple[Tuple[bytes, bytes], ...] = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
    )

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                existing_headers = list(message.get("headers") or [])
                existing_names = {k.lower() for k, _ in existing_headers}

                for sec_key, sec_val in self.SECURITY_HEADERS:
                    if sec_key not in existing_names:
                        existing_headers.append((sec_key, sec_val))

                message = {**message, "headers": existing_headers}

            await send(message)

        await self.app(scope, receive, send_wrapper)
