"""Деплой на VPS. Только для maintainer: pip install -r requirements-dev.txt (корень репо).
   VPS_PASS в окружении, токен — в app/.env (не в git)."""
from __future__ import annotations

import io
import os
import sys
import tarfile
import textwrap
from pathlib import Path

import paramiko

APP = Path(__file__).resolve().parent.parent
HOST = os.environ.get("VPS_HOST", "45.38.3.49")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASS", "")
REMOTE = "/opt/zampotex/app"


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def build_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("requirements.txt", "zampotex"):
            path = APP / name
            tar.add(path, arcname=name, filter=_tar_filter)
    return buf.getvalue()


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(tarinfo.name).parts
    if any(p in {"__pycache__", ".venv", ".pytest_cache"} for p in parts):
        return None
    if tarinfo.name.endswith(".pyc"):
        return None
    return tarinfo


def run(client: paramiko.SSHClient, command: str) -> None:
    print(f"$ {command[:120]}...")
    _, stdout, stderr = client.exec_command(command, get_pty=True)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out.strip():
        safe = out[-4000:].encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        print(safe)
    if exit_code != 0:
        print(err[-2000:], file=sys.stderr)
        raise SystemExit(f"Command failed ({exit_code}): {command}")


def main() -> None:
    if not PASSWORD:
        raise SystemExit("Set VPS_PASS environment variable")

    env = load_env(APP / ".env")
    token = env.get("BOT_TOKEN", "")
    if not token:
        raise SystemExit("BOT_TOKEN missing in app/.env")

    admin_ids = env.get(
        "ADMIN_IDS",
        "170051092,311684774,206146757,635342790",
    )
    db_url = env.get("DATABASE_URL", "sqlite+aiosqlite:///./data/zampotex.db")

    tarball = build_tarball()
    print(f"Archive size: {len(tarball) // 1024} KiB")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=60)

    sftp = client.open_sftp()
    try:
        run(client, "mkdir -p /opt/zampotex")
        with sftp.file("/opt/zampotex/app.tgz", "wb") as remote:
            remote.write(tarball)
    finally:
        sftp.close()

    remote_env = textwrap.dedent(
        f"""\
        BOT_TOKEN={token}
        BOT_ID=8893240032
        ADMIN_IDS={admin_ids}
        DATABASE_URL={db_url}
        """
    )

    setup = f"""
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip tar >/dev/null
mkdir -p {REMOTE}/data
rm -rf {REMOTE}/zampotex {REMOTE}/requirements.txt
tar -xzf /opt/zampotex/app.tgz -C {REMOTE}
python3 -m venv {REMOTE}/.venv
{REMOTE}/.venv/bin/pip install -q -r {REMOTE}/requirements.txt
cat > {REMOTE}/.env << 'ENVEOF'
{remote_env}ENVEOF
chmod 600 {REMOTE}/.env
"""
    run(client, setup)

    unit = textwrap.dedent(
        f"""\
        [Unit]
        Description=ZamPoTeh Telegram bot
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE}
        Environment=PYTHONUNBUFFERED=1
        ExecStart={REMOTE}/.venv/bin/python -m zampotex
        Restart=always
        RestartSec=5

        [Install]
        WantedBy=multi-user.target
        """
    )

    run(
        client,
        f"cat > /etc/systemd/system/zampotex.service << 'UNITEOF'\n{unit}UNITEOF",
    )
    run(client, "systemctl daemon-reload")
    run(client, "systemctl enable zampotex")
    run(client, "systemctl restart zampotex")
    run(client, "sleep 2 && systemctl is-active zampotex && journalctl -u zampotex -n 15 --no-pager")

    client.close()
    print("Deploy finished OK.")


if __name__ == "__main__":
    main()
