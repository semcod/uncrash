"""Exercise the transfer boundary without making SSH calls."""
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Config, RecoveryInterface, Rejected, handler_for


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bundle = self.root / 'source.tar'
        self.bundle.write_bytes(b'owned-test-bundle')
        self.bundle.chmod(0o600)
        self.calls = []
        self.now = 100
        self.interface = RecoveryInterface(
            Config(self.root / 'state', bundle=self.bundle),
            runner=self.transfer, clock=lambda: self.now, audit=lambda *_: None,
        )

    def transfer(self, command, staged, host):
        self.assertNotEqual(staged, self.bundle)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
        raw = staged.read_bytes()
        self.calls.append((host, raw))
        return {'host': host, 'sha256': hashlib.sha256(raw).hexdigest(),
                'bytes': len(raw), 'archive': '/private/test.tar', 'apps_launched': False}

    def test_preview_never_transfers_and_confirmation_is_single_use(self):
        plan = self.interface.plan()
        self.assertEqual(self.calls, [])
        result = self.interface.apply(plan['token'])
        self.assertTrue(result['transferred'])
        self.assertEqual(self.calls, [('tom@minis', self.bundle.read_bytes())])
        with self.assertRaises(Rejected):
            self.interface.apply(plan['token'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(list((self.root / 'state').glob('*.receipt.json'))), 1)
        self.assertEqual(list((self.root / 'state').glob('transfer-*.tar')), [])

    def test_changed_bundle_cannot_use_prior_confirmation(self):
        token = self.interface.plan()['token']
        self.bundle.write_bytes(b'changed-test-bundle')
        with self.assertRaisesRegex(Rejected, 'changed'):
            self.interface.apply(token)
        self.assertEqual(self.calls, [])
        with self.assertRaises(Rejected):
            self.interface.apply(token)

    def test_confirmation_expiry_and_pending_limit(self):
        token = self.interface.plan()['token']
        self.now += 120
        with self.assertRaisesRegex(Rejected, 'expired'):
            self.interface.apply(token)
        for _ in range(32):
            self.interface.plan()
        with self.assertRaisesRegex(Rejected, 'Too many'):
            self.interface.plan()

    def test_private_regular_file_and_parent_symlink_required(self):
        self.bundle.chmod(0o644)
        with self.assertRaises(Rejected):
            self.interface.plan()
        self.bundle.chmod(0o600)
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        linked = RecoveryInterface(Config(self.root / 'state2', bundle=link / self.bundle.name))
        with self.assertRaises(Rejected):
            linked.plan()
        fifo = self.root / 'fifo'
        import os
        os.mkfifo(fifo, 0o600)
        named_pipe = RecoveryInterface(Config(self.root / 'state3', bundle=fifo))
        with self.assertRaises(Rejected):
            named_pipe.plan()

    def test_wrong_receipt_cannot_claim_verified_delivery(self):
        self.interface.runner = lambda *_: {'sha256': '0' * 64, 'host': 'wrong@host'}
        with self.assertRaisesRegex(Rejected, 'receipt'):
            self.interface.apply(self.interface.plan()['token'])
        self.assertEqual(list((self.root / 'state').glob('*.receipt.json')), [])

    def test_same_token_cannot_dispatch_two_concurrent_transfers(self):
        token = self.interface.plan()['token']
        entered, release = threading.Event(), threading.Event()
        transfer = self.transfer
        def paused(*args):
            entered.set()
            release.wait(3)
            return transfer(*args)
        self.interface.runner = paused
        outcomes = []
        def first():
            outcomes.append(self.interface.apply(token))
        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(Rejected):
                self.interface.apply(token)
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(len(self.calls), 1)

    def test_source_replacement_after_copy_does_not_change_uploaded_bytes(self):
        old = self.bundle.read_bytes()
        transfer = self.transfer
        def replace_original(*args):
            self.bundle.write_bytes(b'new-source')
            return transfer(*args)
        self.interface.runner = replace_original
        self.interface.apply(self.interface.plan()['token'])
        self.assertEqual(self.calls, [('tom@minis', old)])


class HTTPTests(unittest.TestCase):
    transfer = TransferTests.transfer

    def setUp(self):
        TransferTests.setUp(self)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.interface))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def post(self, path, body, origin=None, host=None):
        headers = {'Content-Type': 'application/json'}
        if origin is not None:
            headers['Origin'] = origin
        if host is not None:
            headers['Host'] = host
        req = urllib.request.Request(self.origin + path, data=json.dumps(body).encode(), headers=headers)
        return self.opener.open(req, timeout=2)

    def test_cross_origin_and_rebound_host_cannot_prepare_transfer(self):
        for origin, host in [(None, None), ('https://other.test', None), (self.origin, 'other.test')]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/transfer/plan', {}, origin, host)
            self.assertEqual(error.exception.code, 403)
        self.assertEqual(self.interface.plans, {})
        self.assertEqual(self.calls, [])

    def test_health_and_confirmed_transfer_round_trip(self):
        response = self.opener.open(self.origin + '/health')
        self.assertEqual(json.load(response), {'status': 'ok', 'app': 'uncrash-recovery'})
        with self.post('/api/transfer/plan', {}, self.origin) as response:
            token = json.load(response)['token']
        with self.post('/api/transfer/apply', {'token': token}, self.origin) as response:
            self.assertTrue(json.load(response)['transferred'])

    def test_request_cannot_supply_new_host_or_source(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/transfer/plan', {'host': 'other@host', 'source': '/etc/passwd'}, self.origin)
        self.assertEqual(error.exception.code, 404)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
