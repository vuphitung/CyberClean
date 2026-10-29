"""Narrow helper transport tests; never invoke UAC or access hardware."""
import socket
import threading

import pytest

from utils import windows_sensor_access as access


def test_mutual_authentication_over_local_socketpair():
    server, client = socket.socketpair()
    token = b'test-only-shared-key'
    failures = []

    def authenticate_server():
        try:
            access._authenticate_server(server, token)
        except Exception as exc:  # surfaced in the test thread
            failures.append(exc)

    thread = threading.Thread(target=authenticate_server)
    thread.start()
    try:
        access._authenticate_client(client, token)
        thread.join(timeout=2.)
        assert not thread.is_alive()
        assert not failures
    finally:
        server.close()
        client.close()


def test_transport_accepts_only_stop_command():
    sender, receiver = socket.socketpair()
    writer = access._StopWriter(access._Channel(sender))
    try:
        with pytest.raises(ValueError, match='Only STOP'):
            writer.write('RUN COMMAND\n')
        writer.write('STOP\n')
        assert receiver.recv(5) == b'STOP\n'
    finally:
        writer.close()
        receiver.close()


def test_helper_must_be_in_fixed_protected_install_location(tmp_path, monkeypatch):
    install = tmp_path / 'Program Files' / 'CyberClean' / 'sensor-host'
    install.mkdir(parents=True)
    executable = install / 'CyberCleanSensorHost.exe'
    executable.write_bytes(b'fixture')
    monkeypatch.setattr(access.sys, 'platform', 'win32')
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'Program Files'))
    assert access.installed_sensor_helper() == executable.resolve()

    executable.unlink()
    assert access.installed_sensor_helper() is None
