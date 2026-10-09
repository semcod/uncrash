"""Structured historical process export and deterministic recovery actions."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit
import re

from .store import RecoveryError


def process_export(store, snapshot='latest'):
    with store.lock():
        sid, _, _, manifest = store.load(snapshot)
    return {'schema': 'wellmanifest.conversational-process-snapshot/v1',
        'exportedAt': datetime.now(timezone.utc).isoformat(),
        'url': 'action://uncrash/restore?snapshot='+sid,
        'state': {'snapshot': sid, 'snapshotCreatedAt': manifest['created_at'],
            'fidelity': manifest['fidelity'], 'profileIds': [p['id'] for p in manifest['profiles']],
            'chatAdapterAvailable': False},
        'chat': {'messageCount': 0, 'messages': []},
        'processes': {'activeProcessId': None, 'items': [
            {'id': p['pid'], 'urn': 'urn:uncrash:proc:'+str(p['pid'])+'-'+p['start_ticks'],
             'uri': 'process://local/'+quote(p['name'], safe='')+'?id='+str(p['pid']),
             'command': p['name'], 'status': 'running', 'startedAt': manifest['created_at'],
             'historicalObservation': True} for p in manifest['processes']]}}


def parse_restore_action(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != 'action' or parsed.netloc != 'uncrash' or parsed.path != '/restore' or parsed.fragment:
        raise RecoveryError('Only action://uncrash/restore is supported')
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if len(pairs) != 2 or {k for k, _ in pairs} != {'snapshot', 'destination'}:
        raise RecoveryError('Restore action requires exactly snapshot and destination parameters')
    params = dict(pairs)
    if params['snapshot'] != 'latest' and not re.fullmatch(r'\d{8}T\d{12}-[a-f0-9]{12}', params['snapshot']):
        raise RecoveryError('Invalid restore action snapshot')
    destination = Path(params['destination'])
    if not destination.is_absolute() or '\x00' in str(destination):
        raise RecoveryError('Restore action requires an absolute destination')
    return params['snapshot'], destination
