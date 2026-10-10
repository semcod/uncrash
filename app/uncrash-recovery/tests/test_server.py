"""Exercise the transfer boundary without making SSH calls."""
import hashlib
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import (
    MAX_PREVIEW_PAGE,
    Config,
    PreviewPage,
    RecoveryInterface,
    Rejected,
    handler_for,
    preview_available,
)


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


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.requests = []
        requests = self.requests
        valid = b'<div id="noVNC_container"></div><script type="module" src="app/ui.js"></script>'

        class PreviewHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append(self.path)
                if self.path == '/slow':
                    time.sleep(0.4)
                status = 302 if self.path == '/redirect' else 404 if self.path == '/missing' else 200
                body = b'<html>Another application</html>' if self.path == '/other' else valid
                if self.path == '/broken-client':
                    body = b'<div id="noVNC_container"></div>'
                self.send_response(status)
                self.send_header('Content-Type', 'application/json' if self.path == '/json' else 'text/html')
                if status == 302:
                    self.send_header('Location', '/vnc.html')
                length = MAX_PREVIEW_PAGE + 1 if self.path == '/oversized' else len(body)
                self.send_header('Content-Length', str(length))
                self.end_headers()
                if self.path != '/oversized':
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), PreviewHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def stop_server(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)

    def test_http_probe_requires_actual_client_page_and_preserves_query(self):
        self.assertTrue(preview_available(self.base + '/vnc.html?autoconnect=true&resize=scale'))
        self.assertEqual(self.requests, ['/vnc.html?autoconnect=true&resize=scale'])
        for path in ['/other', '/json', '/missing', '/broken-client', '/oversized', '/slow']:
            with self.subTest(path=path):
                self.assertFalse(preview_available(self.base + path))

    def test_inline_and_external_module_clients(self):
        for script in ['<script type="module">import UI from "./app/ui.js";</script>',
                       '<script type="module" src="./app/ui.js"></script>']:
            with self.subTest(script=script):
                parser = PreviewPage()
                parser.feed('<div id="noVNC_container"></div>' + script)
                self.assertTrue(parser.container and parser.client)
        parser = PreviewPage()
        parser.feed('<div id="noVNC_container"></div><script>import UI from "./app/ui.js";</script>')
        self.assertFalse(parser.client)

    def test_redirect_does_not_follow_to_another_page(self):
        self.assertFalse(preview_available(self.base + '/redirect'))
        self.assertEqual(self.requests, ['/redirect'])

    def test_stopped_listener_and_invalid_loopback_endpoint(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.assertFalse(preview_available(f'http://127.0.0.1:{port}/vnc.html'))
        with self.assertRaises(Rejected):
            preview_available('http://example.test:8080/vnc.html')

    def test_inventory_checks_each_url_without_erasing_session_identity(self):
        inventory = self.root / 'sessions.json'
        rows = [{'conversation_id': str(uuid.uuid4()), 'cwd': '/projects/' + name,
                 'novnc_url': self.base + path, 'mode': 'plan', 'fidelity': 'persisted'}
                for name, path in [('ready', '/vnc.html'), ('wrong-service', '/other'),
                                   ('stopped', '/missing')]]
        inventory.write_text(json.dumps(rows))
        inventory.chmod(0o600)
        interface = RecoveryInterface(Config(self.root / 'state', sessions=inventory))
        result = interface.sessions()['sessions']
        self.assertEqual([r['status'] for r in result], ['active', 'stopped', 'stopped'])
        self.assertEqual([r['id'] for r in result], [r['conversation_id'] for r in rows])
        self.assertEqual([r['url'] for r in result], [r['novnc_url'] for r in rows])


if __name__ == '__main__':
    unittest.main()
