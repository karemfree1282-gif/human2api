"""Real loopback HTTP/TLS security and lifecycle regressions; no external accounts."""
from __future__ import annotations

import base64
import datetime
import ipaddress
import json
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from human2api.marketplace import pack_workflow
from human2api.models import WorkflowError, save_workflow
from human2api.registry import Registry, make_registry
from human2api.registry_backup import backup, restore
from human2api.trust import generate_keypair


def wire_status(server, path: str, extra: list[str]) -> int:
    host, port = server.server_address
    request = '\r\n'.join([f'GET {path} HTTP/1.1', f'Host: {host}:{port}', *extra, 'Connection: close', '', ''])
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall(request.encode('ascii'))
        line = connection.makefile('rb').readline(1024)
    return int(line.split()[1])


@pytest.mark.parametrize('header', ['Host', 'Origin', 'X-H2A-Token', 'Authorization'])
def test_local_rejects_duplicate_security_headers(local_server, header):
    server, folder, origin = local_server
    if header == 'Host':
        headers = [f'Host: 127.0.0.1:{server.server_address[1]}']
    else:
        value = origin if header == 'Origin' else server.token if header == 'X-H2A-Token' else 'Bearer test'
        headers = [f'{header}: {value}', f'{header.lower()}: {value}']
    assert wire_status(server, '/health', headers) == 403


@pytest.fixture
def publisher(tmp_path):
    store = Registry(tmp_path / 'registry')
    private, public = tmp_path / 'signing.pem', tmp_path / 'public.pem'
    generate_keypair(private, public)
    token = store.enroll('publisher', public)
    workflow = {'schemaVersion': 1, 'name': 'qa_skill', 'description': 'Synthetic read-only acceptance test',
                'target': 'desktop', 'permissions': 'read', 'steps': [{'action': 'wait_ms', 'durationMs': 100}]}
    source = save_workflow(tmp_path / 'qa_skill.json', workflow)
    package = pack_workflow(source, tmp_path / 'qa_skill.h2a.zip', publisher='publisher',
                            sign_key=private, release_version='1.0.0')
    return store, token, package, private, public


@pytest.mark.parametrize('header', ['Host', 'Origin', 'Authorization'])
def test_registry_rejects_duplicate_security_headers(publisher, header):
    store, token, *_ = publisher
    server = make_registry(store.directory, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        value = server.public_origin if header == 'Origin' else 'Bearer ' + token
        headers = [f'{header}: {value}', f'{header.lower()}: {value}'] if header != 'Host' else [f'Host: 127.0.0.1:{server.server_address[1]}']
        assert wire_status(server, '/health', headers) == 403
    finally:
        server.shutdown(); server.server_close(); thread.join(5)


@pytest.mark.parametrize('change', ['revoke', 'rotate'])
def test_yank_rechecks_token_inside_write_transaction(publisher, monkeypatch, change):
    store, token, package, *_ = publisher
    store.publish(token, '1.0.0', package.read_bytes())
    authenticate = store.authenticate
    def changed(supplied):
        who = authenticate(supplied)
        if change == 'revoke': store.revoke(who)
        else: store.rotate_token(who)
        return who
    monkeypatch.setattr(store, 'authenticate', changed)
    with pytest.raises(WorkflowError, match='revoked|rotated|token'):
        store.yank(token, 'qa_skill', '1.0.0')
    with store.connect() as db:
        assert db.execute('SELECT yanked FROM packages').fetchone()[0] == 0


@pytest.mark.parametrize('change', ['revoke', 'rotate'])
def test_rating_rechecks_token_inside_write_transaction(publisher, tmp_path, monkeypatch, change):
    store, token, package, *_ = publisher
    store.publish(token, '1.0.0', package.read_bytes())
    private, public = tmp_path / 'review.pem', tmp_path / 'review-public.pem'
    generate_keypair(private, public)
    reviewer_token = store.enroll('reviewer', public)
    authenticate = store.authenticate
    def changed(supplied):
        who = authenticate(supplied)
        if change == 'revoke': store.revoke(who)
        else: store.rotate_token(who)
        return who
    monkeypatch.setattr(store, 'authenticate', changed)
    with pytest.raises(WorkflowError, match='revoked|rotated|token'):
        store.rate(reviewer_token, 'publisher', 'qa_skill', 4)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM ratings').fetchone()[0] == 0


def test_revoked_publisher_cannot_receive_new_reviews(publisher, tmp_path):
    store, token, package, *_ = publisher
    store.publish(token, '1.0.0', package.read_bytes())
    private, public = tmp_path / 'review.pem', tmp_path / 'review-public.pem'
    generate_keypair(private, public)
    review = store.enroll('reviewer', public)
    store.revoke('publisher')
    with pytest.raises(WorkflowError, match='package|revoked'):
        store.rate(review, 'publisher', 'qa_skill', 5)


def test_concurrent_publish_is_immutable(publisher):
    store, token, package, *_ = publisher
    raw = package.read_bytes()
    def upload(_):
        try:
            store.publish(token, '1.0.0', raw)
            return 'created'
        except WorkflowError as exc:
            assert 'immutable' in str(exc)
            return 'conflict'
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(upload, range(16)))
    assert results.count('created') == 1 and results.count('conflict') == 15
    assert store.download('publisher', 'qa_skill', '1.0.0') == raw


def test_local_rest_survives_concurrent_reads(local_server):
    server, _, origin = local_server
    def fetch(_):
        request = Request(origin + '/api/workflows', headers={'X-H2A-Token': server.token})
        with urlopen(request, timeout=10) as response:
            assert response.status == 200
            return json.load(response)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, range(120)))
    assert len(results) == 120


def test_registry_verified_tls_lifecycle_backup_restore(publisher, tmp_path, monkeypatch):
    """A real verified local TLS socket, not public hosting or a TLS mock."""
    store, token, package, private, public = publisher
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Human2API local QA only')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'qa-cert.pem', tmp_path / 'qa-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    server = make_registry(store.directory, 0)
    origin = f'https://127.0.0.1:{server.server_address[1]}'
    server.public_origin = origin
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    trusted = ssl.create_default_context(cafile=str(cert_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def request(path, payload=None, credential=None):
        headers = {'Content-Type': 'application/json'}
        if credential: headers['Authorization'] = 'Bearer ' + credential
        body = None if payload is None else json.dumps(payload).encode()
        with urlopen(Request(origin + path, data=body, headers=headers), context=trusted, timeout=5) as response:
            return response.status, response.read()
    try:
        assert request('/health')[0] == 200
        assert request('/v1/publish', {'version': '1.0.0', 'package': base64.b64encode(package.read_bytes()).decode()}, token)[0] == 201
        assert request('/v1/packages/publisher/qa_skill/1.0.0')[1] == package.read_bytes()
        # Trust this test certificate explicitly; never disable verification.
        monkeypatch.setenv('SSL_CERT_FILE', str(cert_path))
        from human2api.registry_client import install
        installed = install(origin, 'publisher', 'qa_skill', '1.0.0', tmp_path / 'installed', public, approve=True)
        assert installed.is_file()
        update = pack_workflow(tmp_path / 'qa_skill.json', tmp_path / 'updated.h2a.zip', publisher='publisher',
                               sign_key=private, release_version='1.1.0')
        assert request('/v1/publish', {'version': '1.1.0', 'package': base64.b64encode(update.read_bytes()).decode()}, token)[0] == 201
        assert install(origin, 'publisher', 'qa_skill', '1.1.0', tmp_path / 'installed', public, approve=True, upgrade=True) == installed
        with pytest.raises(WorkflowError, match='newer'):
            install(origin, 'publisher', 'qa_skill', '1.0.0', tmp_path / 'installed', public, approve=True, upgrade=True)
        with pytest.raises(HTTPError) as denied:
            request('/v1/yank', {'name': 'qa_skill', 'version': '1.0.0'}, 'invalid')
        assert denied.value.code == 401
        snapshot = tmp_path / 'qa-backup.sqlite3'
        backup(store, snapshot); restore(snapshot, tmp_path / 'restored')
        restored = Registry(tmp_path / 'restored')
        assert restored.download('publisher', 'qa_skill', '1.0.0') == package.read_bytes()
        new_token = store.rotate_token('publisher')
        with pytest.raises(HTTPError): request('/v1/yank', {'name': 'qa_skill', 'version': '1.0.0'}, token)
        assert request('/v1/yank', {'name': 'qa_skill', 'version': '1.0.0'}, new_token)[0] == 200
        assert request('/v1/yank', {'name': 'qa_skill', 'version': '1.1.0'}, new_token)[0] == 200
        assert json.loads(request('/v1/packages')[1])['packages'] == []
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
