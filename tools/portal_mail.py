"""SMTP do portal: senha no cofre do Windows e portal/mail-config.php enviado só ao servidor.

O arquivo fica fora do Git e da publicação da aplicação; portal/ é negado pela web.
  python tools/portal_mail.py --store          (pede a senha SMTP sem eco)
  python tools/portal_mail.py --publish --host H --port 587 --encryption tls --username U --from F
"""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path

import deploy
import portal_credentials

TARGET = 'Humcode/SMTP/humcode'
REMOTE_PATH = 'portal/mail-config.php'
ROOT = Path(__file__).resolve().parents[1]


def source(settings):
    encoded = base64.b64encode(json.dumps(settings).encode()).decode()
    return ('<?php\n// Gerado por tools/portal_mail.py; não versionar.\nreturn json_decode(base64_decode(' + deploy.php_string(encoded) + '), true);\n').encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--host'); parser.add_argument('--port', type=int, default=587)
    parser.add_argument('--encryption', choices=['tls', 'ssl'], default='tls')
    parser.add_argument('--username'); parser.add_argument('--from', dest='sender'); parser.add_argument('--from-name', default='Humcode')
    args = parser.parse_args()
    if args.store:
        portal_credentials.save(getpass.getpass('Senha SMTP (cofre Windows): '), TARGET, 'smtp')
        print('Senha SMTP guardada no cofre do Windows.')
        return
    if not args.publish or not (args.host and args.username and args.sender):
        parser.error('Use --store, ou --publish com --host, --username e --from.')
    settings = {'transport': 'smtp', 'host': args.host, 'port': args.port, 'encryption': args.encryption, 'username': args.username,
                'password': portal_credentials.read(TARGET), 'from': args.sender, 'from_name': args.from_name}
    data = source(settings)
    with deploy.connect(portal_credentials.read()) as ftp:
        deploy.upload(ftp, REMOTE_PATH, data)
        published = deploy.remote_bytes(ftp, REMOTE_PATH)
    status = deploy.http('/' + REMOTE_PATH)[0]
    report = {'published_at': datetime.now(timezone.utc).isoformat(), 'remote_path': REMOTE_PATH, 'sha256_matches': hashlib.sha256(published).digest() == hashlib.sha256(data).digest(),
              'web_status': status, 'host': args.host, 'port': args.port, 'encryption': args.encryption, 'username': args.username, 'from': args.sender, 'password': 'cofre do Windows (' + TARGET + '); não registrada'}
    (ROOT / 'artifacts/mail-config-publication.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not report['sha256_matches'] or status not in (403, 404):
        raise SystemExit('Falha: arquivo divergente ou acessível pela web (HTTP ' + str(status) + ').')
    print(json.dumps({k: v for k, v in report.items() if k != 'password'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
