#!/usr/bin/env python3
"""One-time, user-approved Google OAuth setup for the Bilgi Dozu worker.

This script runs only in GitHub Actions. It never prints credentials, Google
response bodies or authorization codes. Its only result is encrypted to the
one-time recipient public key below. It does not upload or change YouTube/Drive.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

FLOW_ID = '404378298e2d1502'
RECIPIENT_PUBLIC_KEY = 'YIs6vxl8kv21GwJzzL/uyk6dLMefTWxwwrBRM3Rx90M='
EXPECTED_CHANNEL = 'UC3bjZMPZ5FW2JQGfU41iaUg'
DRIVE_FOLDER = '1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_'
DRIVE_WORKBOOK = '1HzJQuok1Qs6rnucrUqHuuLE7eAr_4bIF'
SCOPES = (
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/yt-analytics.readonly',
)
SAFE_OAUTH_ERRORS = {'invalid_grant', 'invalid_client', 'invalid_request', 'unauthorized_client', 'access_denied', 'invalid_scope'}


class SetupError(Exception):
    """Carries a sanitized status code, never provider response text."""


def configured_client(raw: str) -> dict:
    try:
        conf = json.loads(raw)
        client = conf['installed']
    except (ValueError, KeyError, TypeError):
        raise SetupError('CLIENT_CONFIG_INVALID') from None
    if not isinstance(client, dict):
        raise SetupError('CLIENT_CONFIG_INVALID')
    cid = str(client.get('client_id') or '')
    if not re.fullmatch(r'[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com', cid):
        raise SetupError('CLIENT_ID_INVALID')
    if not client.get('client_secret'):
        raise SetupError('CLIENT_SECRET_MISSING')
    return client


def emit_sealed(payload: dict) -> None:
    from nacl.public import PublicKey, SealedBox
    try:
        recipient = PublicKey(base64.b64decode(RECIPIENT_PUBLIC_KEY, validate=True))
        clear = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        sealed = SealedBox(recipient).encrypt(clear)
    except Exception:
        raise SetupError('ENCRYPTION_FAILED') from None
    print('BD_OAUTH_SEALED=' + base64.b64encode(sealed).decode('ascii'), flush=True)


def request_json(url: str, *, form: dict | None = None, access_token: str | None = None) -> dict:
    headers = {'Accept': 'application/json'}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        error = ''
        try:
            value = json.loads(exc.read().decode('utf-8')).get('error')
            if isinstance(value, str) and value in SAFE_OAUTH_ERRORS:
                error = '_' + value.upper()
        except Exception:
            pass
        raise SetupError('GOOGLE_HTTP_' + str(exc.code) + error) from None
    except Exception:
        raise SetupError('GOOGLE_NETWORK_OR_RESPONSE_ERROR') from None
    if not isinstance(data, dict):
        raise SetupError('GOOGLE_RESPONSE_INVALID')
    return data


def setup_request(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise SetupError('SETUP_REQUEST_INVALID') from None
    if not isinstance(data, dict) or data.get('flow_id') != FLOW_ID:
        raise SetupError('SETUP_REQUEST_MISMATCH')
    verifier = str(data.get('verifier') or '')
    code = str(data.get('code') or '')
    redirect = str(data.get('redirect_uri') or '')
    if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or not (15 <= len(code) <= 2048):
        raise SetupError('SETUP_REQUEST_INVALID')
    u = urllib.parse.urlsplit(redirect)
    try:
        good_port = 1024 <= u.port <= 65535
    except (ValueError, TypeError):
        good_port = False
    if not (u.scheme == 'http' and u.hostname == '127.0.0.1' and good_port and u.path == '/oauth2callback' and not u.query and not u.fragment and not u.username):
        raise SetupError('REDIRECT_URI_INVALID')
    return data


def inspect(client: dict) -> dict:
    return {'flow_id': FLOW_ID, 'kind': 'inspect', 'client_id': client['client_id'], 'project_id': str(client.get('project_id') or '')}


def exchange(client: dict, request: dict) -> dict:
    cid, csecret = client['client_id'], client['client_secret']
    token = request_json('https://oauth2.googleapis.com/token', form={
        'client_id': cid,
        'client_secret': csecret,
        'code': request['code'],
        'code_verifier': request['verifier'],
        'redirect_uri': request['redirect_uri'],
        'grant_type': 'authorization_code',
    })
    refresh = token.get('refresh_token')
    granted = set(str(token.get('scope') or '').split())
    if not refresh:
        raise SetupError('REFRESH_TOKEN_NOT_RETURNED')
    if not set(SCOPES).issubset(granted):
        raise SetupError('REQUESTED_SCOPES_NOT_GRANTED')
    # Verify that offline refresh really works before touching the live secret.
    again = request_json('https://oauth2.googleapis.com/token', form={
        'client_id': cid,
        'client_secret': csecret,
        'refresh_token': refresh,
        'grant_type': 'refresh_token',
    })
    access = str(again.get('access_token') or '')
    if not access:
        raise SetupError('REFRESH_VALIDATION_FAILED')
    try:
        expires = int(again.get('expires_in') or 3600)
    except (TypeError, ValueError):
        raise SetupError('TOKEN_EXPIRY_INVALID') from None
    if expires < 60 or expires > 86400:
        raise SetupError('TOKEN_EXPIRY_INVALID')
    channels = request_json('https://youtube.googleapis.com/youtube/v3/channels?part=id&mine=true&maxResults=50', access_token=access)
    if EXPECTED_CHANNEL not in {str(x.get('id') or '') for x in channels.get('items', []) if isinstance(x, dict)}:
        raise SetupError('WRONG_YOUTUBE_CHANNEL')
    folder = request_json('https://www.googleapis.com/drive/v3/files/' + DRIVE_FOLDER + '?fields=id%2CmimeType', access_token=access)
    if folder.get('id') != DRIVE_FOLDER or folder.get('mimeType') != 'application/vnd.google-apps.folder':
        raise SetupError('DRIVE_FOLDER_UNAVAILABLE')
    wb = request_json('https://www.googleapis.com/drive/v3/files/' + DRIVE_WORKBOOK + '?fields=id%2Ccapabilities%28canEdit%2CcanDownload%29', access_token=access)
    caps = wb.get('capabilities') or {}
    if wb.get('id') != DRIVE_WORKBOOK or not caps.get('canEdit') or not caps.get('canDownload'):
        raise SetupError('DRIVE_WORKBOOK_ACCESS_INSUFFICIENT')
    # Analytics availability is reported separately and cannot block the
    # repaired uploader if the API is disabled or no data is available.
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    query = urllib.parse.urlencode({'ids':'channel==MINE', 'startDate':start.isoformat(), 'endDate':end.isoformat(), 'metrics':'views', 'dimensions':'day'})
    analytics = 'OK'
    try:
        request_json('https://youtubeanalytics.googleapis.com/v2/reports?' + query, access_token=access)
    except SetupError as exc:
        analytics = str(exc) if str(exc).startswith('GOOGLE_HTTP_') else 'UNAVAILABLE'
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires - 30)).isoformat().replace('+00:00', 'Z')
    credentials = {
        'token': access,
        'refresh_token': refresh,
        'token_uri': 'https://oauth2.googleapis.com/token',
        'client_id': cid,
        'client_secret': csecret,
        'scopes': sorted(granted),
        'expiry': expiry,
    }
    return {'flow_id': FLOW_ID, 'kind': 'exchange', 'client_id': cid, 'channel_id': EXPECTED_CHANNEL,
            'drive_access': 'OK', 'analytics': analytics, 'credentials': credentials}


def main() -> None:
    try:
        client = configured_client(os.environ.get('CLIENT_JSON', ''))
        phase = os.environ.get('SETUP_PHASE', '')
        if phase == 'inspect':
            result = inspect(client)
        elif phase == 'exchange':
            result = exchange(client, setup_request(os.environ.get('SETUP_JSON', '')))
        else:
            raise SetupError('PHASE_INVALID')
        emit_sealed(result)
        print('BD_OAUTH_PHASE_COMPLETE=' + phase, flush=True)
    except SetupError as exc:
        print('BD_OAUTH_SETUP_FAILED=' + str(exc), flush=True)
        raise SystemExit(1) from None
    except Exception:
        print('BD_OAUTH_SETUP_FAILED=UNEXPECTED', flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
