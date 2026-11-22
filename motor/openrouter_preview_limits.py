"""Safe, bounded retries for isolated free-model previews; never enables paid inference."""
from __future__ import annotations
import datetime
import email.utils
import json
import time


def classify_retry(error, attempt: int) -> tuple[str, float | None]:
    """Return (reason, seconds) after a failed request; None means stop now.

    Never log the provider response. Daily limit exhaustion cannot be fixed by
    rapid retries. Long retry hints are not slept through in an interactive run.
    """
    if getattr(error, 'code', None) != 429:
        return 'transient_http', (6.0, 12.0)[min(attempt, 1)]
    try:
        payload = json.loads(error.read(16384))
        metadata = (payload.get('error') or {}).get('metadata') or {}
        source = str(metadata.get('limit_source') or '')
    except Exception:
        source = ''
    if source == 'openrouter_free_tier_daily':
        return 'daily_quota_exhausted', None
    headers = getattr(error, 'headers', None) or {}
    retry_after = headers.get('Retry-After')
    reset = headers.get('X-RateLimit-Reset')
    delay = None
    if retry_after:
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            try:
                value = email.utils.parsedate_to_datetime(str(retry_after))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=datetime.timezone.utc)
                delay = value.timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                pass
    elif reset:
        try:
            delay = float(reset) / 1000.0 - time.time()
        except (TypeError, ValueError, OverflowError):
            pass
    if delay is None:
        delay = (6.0, 12.0)[min(attempt, 1)]
    delay = max(0.0, delay)
    if delay > 20.0:
        return 'retry_later', None
    return 'rate_limited', delay
