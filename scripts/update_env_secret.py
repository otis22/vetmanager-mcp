#!/usr/bin/env python3
"""Update one .env key from a secret file without leaking the value."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def update_env_secret(env_path: Path, key: str, secret_path: Path) -> None:
    if not key.isidentifier():
        raise SystemExit("Invalid env key.")
    if env_path.is_symlink():
        raise SystemExit("Refusing to update symlink .env.")
    if secret_path.is_symlink() or not secret_path.is_file():
        raise SystemExit("Secret file is not a regular file.")

    value = secret_path.read_text(encoding="utf-8")
    if not value:
        raise SystemExit("Secret value is empty.")
    if "\n" in value or "\r" in value:
        raise SystemExit("Secret value must not contain newline characters.")

    if env_path.exists():
        st = env_path.stat()
        mode = stat.S_IMODE(st.st_mode)
        uid = st.st_uid
        gid = st.st_gid
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        mode = 0o600
        uid = os.getuid()
        gid = os.getgid()
        lines = []

    new_line = f"{key}={_shell_quote(value)}"
    prefix = f"{key}="
    replaced = False
    next_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            if not replaced:
                next_lines.append(new_line)
                replaced = True
            continue
        next_lines.append(line)
    if not replaced:
        next_lines.append(new_line)

    parent = env_path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{env_path.name}.", dir=parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(next_lines))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, mode)
        try:
            os.chown(tmp_path, uid, gid)
        except PermissionError:
            if env_path.exists() and (uid != os.getuid() or gid != os.getgid()):
                raise
        os.replace(tmp_path, env_path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: update_env_secret.py <env_path> <key> <secret_file>", file=sys.stderr)
        return 2
    update_env_secret(Path(argv[1]), argv[2], Path(argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
