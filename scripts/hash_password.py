#!/usr/bin/env python3
"""Generate the admin password hash for the Web console.

Usage:
    python scripts/hash_password.py                 # write data/admin_password.hash
    python scripts/hash_password.py --print         # print instead of writing

Reads the password twice from the terminal (never echoed, never stored in
shell history). Writing a file is the default because werkzeug hashes contain
'$', which Docker Compose silently strips as variable interpolation when the
value goes through .env — the login would then always fail.
"""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys

from werkzeug.security import generate_password_hash

MIN_LENGTH = 8
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'admin_password.hash',
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=DEFAULT_OUT, help='hash file path')
    parser.add_argument(
        '--print', dest='print_only', action='store_true',
        help='print the hash instead of writing it to a file',
    )
    args = parser.parse_args()

    if not sys.stdin.isatty():
        print(
            'Refusing to read a password from a pipe: run this in a terminal '
            'so the secret is not captured by shell history or logs.',
            file=sys.stderr,
        )
        return 2

    password = getpass.getpass('管理口令: ')
    if len(password) < MIN_LENGTH:
        print(f'口令太短，至少 {MIN_LENGTH} 个字符', file=sys.stderr)
        return 1

    if password != getpass.getpass('再输一次: '):
        print('两次输入不一致', file=sys.stderr)
        return 1

    digest = generate_password_hash(password)

    if args.print_only:
        print()
        print('哈希（放进 .env 时每个 $ 都要写成 $$，否则 compose 会吃掉盐值）:')
        print()
        print(digest)
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(digest + '\n')
    try:
        os.chmod(args.out, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows / mounted volumes may not support this; not fatal.

    print()
    print(f'已写入: {args.out}')
    print('容器里对应设置（docker-compose.yml 已默认配好）:')
    print('  GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE=/app/data/admin_password.hash')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
