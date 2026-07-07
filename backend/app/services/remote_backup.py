"""
SFTP-Upload für Backups auf ein externes NAS — Passwort- oder Key-Auth.
paramiko ist synchron/blockierend, deshalb werden alle Funktionen hier
per asyncio.to_thread() aus async Code aufgerufen (siehe backup_service.py).
"""
import logging
import os
import tempfile
from pathlib import Path

import paramiko

log = logging.getLogger(__name__)


class RemoteBackupError(Exception):
    pass


def _connect(cfg) -> paramiko.SSHClient:
    if not cfg.backup_remote_host:
        raise RemoteBackupError("Kein Host konfiguriert")
    if not cfg.backup_remote_username:
        raise RemoteBackupError("Kein Benutzername konfiguriert")

    client = paramiko.SSHClient()
    # Zielsystem ist ein vom Admin selbst gewähltes NAS ohne vorab hinterlegten
    # Host-Key-Speicher im Container — TOFU-Verhalten wie bei den meisten
    # Backup-Integrationen dieser Art, kein Pinning.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = dict(
        hostname=cfg.backup_remote_host,
        port=cfg.backup_remote_port or 22,
        username=cfg.backup_remote_username,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )

    if cfg.backup_remote_auth_type == "key":
        if not cfg.backup_remote_private_key:
            raise RemoteBackupError("Kein SSH-Key hinterlegt")
        # In temporäre Datei schreiben — paramiko erkennt RSA/Ed25519/ECDSA/DSS
        # automatisch nur über key_filename, nicht über einen String im Speicher.
        fd, key_path = tempfile.mkstemp(prefix="sc_sftp_key_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(cfg.backup_remote_private_key)
            os.chmod(key_path, 0o600)
            if cfg.backup_remote_key_passphrase:
                connect_kwargs["passphrase"] = cfg.backup_remote_key_passphrase
            client.connect(key_filename=key_path, **connect_kwargs)
        finally:
            os.unlink(key_path)
    else:
        if not cfg.backup_remote_password:
            raise RemoteBackupError("Kein Passwort hinterlegt")
        client.connect(password=cfg.backup_remote_password, **connect_kwargs)

    return client


def _ensure_remote_dir(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    """Legt das Zielverzeichnis rekursiv an, falls es noch nicht existiert."""
    parts = [p for p in remote_path.strip("/").split("/") if p]
    path = ""
    for part in parts:
        path += "/" + part
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)


def upload_file_sync(cfg, local_path: Path) -> None:
    """Lädt eine einzelne Backup-Datei per SFTP hoch. Wirft bei Fehlern eine Exception."""
    client = _connect(cfg)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = cfg.backup_remote_path or "/"
            _ensure_remote_dir(sftp, remote_dir)
            remote_file = remote_dir.rstrip("/") + "/" + local_path.name
            sftp.put(str(local_path), remote_file)
        finally:
            sftp.close()
    finally:
        client.close()


def cleanup_remote_sync(cfg, keep: int) -> None:
    """Löscht älteste Backups im SFTP-Zielverzeichnis, bis nur noch `keep` Stück übrig bleiben
    — spiegelt _cleanup_old_backups() für die lokale Aufbewahrung."""
    client = _connect(cfg)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = cfg.backup_remote_path or "/"
            names = sorted(
                n for n in sftp.listdir(remote_dir)
                if n.startswith("spacecaptain_backup_") and n.endswith(".json")
            )
            for name in names[:-keep] if len(names) > keep else []:
                sftp.remove(remote_dir.rstrip("/") + "/" + name)
                log.info(f"Altes Remote-Backup gelöscht: {name}")
        finally:
            sftp.close()
    finally:
        client.close()


def test_connection_sync(cfg) -> None:
    """Prüft Verbindung + Schreibrechte im Zielverzeichnis (Schreibtest, keine Backup-Datei)."""
    client = _connect(cfg)
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = cfg.backup_remote_path or "/"
            _ensure_remote_dir(sftp, remote_dir)
            test_path = remote_dir.rstrip("/") + "/.spacecaptain_test"
            with sftp.open(test_path, "w") as f:
                f.write("spacecaptain connection test")
            sftp.remove(test_path)
        finally:
            sftp.close()
    finally:
        client.close()
