"""Delegate private wellmanifest.logs/event/v1 observations to Uncrash."""
from pathlib import Path


def record(state_dir, outcome, input_hash, receipt_ref=None):
    # Backend events are observations, never independent approval evidence.
    from uncrash.events import append_event
    return append_event(
        Path(state_dir) / '.apx', event_type='uncrash.apx_transfer', outcome=outcome,
        input_data={'bundle_sha256': input_hash, 'receipt_ref': receipt_ref},
        subject_ref='application:uncrash-apx',
    )
