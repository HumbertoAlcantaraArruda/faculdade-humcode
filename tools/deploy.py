"""Publicação via FTPS. O padrão é somente conferir; --publish ativa o portal."""
import argparse
import base64
from datetime import datetime, timezone
import ftplib
import getpass
import hashlib
from http.cookiejar import CookieJar
import io
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Servidor, usuários e pasta remota ficam fora do Git: tools/deploy.local.json
# (veja deploy.local.example.json) ou variáveis HUMCODE_*; o ambiente tem prioridade.
LOCAL = json.loads((ROOT / 'tools' / 'deploy.local.json').read_text(encoding='utf-8')) if (ROOT / 'tools' / 'deploy.local.json').is_file() else {}


def setting(name, default=''):
    return os.environ.get('HUMCODE_' + name.upper()) or LOCAL.get(name) or default


FTP_HOST = setting('ftp_host')
FTP_USER = setting('ftp_user')
REMOTE = setting('remote', '/www')
DB_HOST = setting('db_host', 'localhost')
DB_NAME = setting('db_name')
DB_USER = setting('db_user')
SITE = setting('site', 'https://www.exemplo.com.br')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_response(opener, request):
    attempts = 3 if request.get_method() == 'GET' else 1
    for attempt in range(attempts):
        try:
            return opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            return error
        except OSError:
            if attempt + 1 == attempts:
                raise
            print('HTTP_RETRY:', request.full_url, flush=True)
            time.sleep(1)


def http(path, data=None):
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(SITE + path, data=urllib.parse.urlencode(data).encode() if data is not None else None)
    response = open_response(opener, request)
    return response.status, response.headers, response.read()


def connect(password):
    context = ssl.create_default_context()
    with urllib.request.urlopen('https://secure.globalsign.com/cacert/gsgccr6alphasslca2025.crt', timeout=20) as response:
        context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(response.read()))
    ftp = ftplib.FTP_TLS(context=context, timeout=30)
    if not FTP_HOST or not FTP_USER:
        raise RuntimeError('Defina ftp_host e ftp_user em tools/deploy.local.json ou HUMCODE_FTP_HOST/HUMCODE_FTP_USER.')
    ftp.connect(FTP_HOST, 21)
    ftp.login(FTP_USER, password)
    ftp.prot_p()
    if ftp.pwd() != REMOTE:
        ftp.cwd(REMOTE)
    return ftp


def remote_bytes(ftp, relative):
    buffer = bytearray()
    ftp.retrbinary('RETR ' + REMOTE + '/' + relative, buffer.extend)
    return bytes(buffer)


def local_payload():
    payload = {}
    for folder in ['src', 'assets']:
        for path in (ROOT / 'portal' / folder).rglob('*'):
            if path.is_file():
                payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for relative in ['index.php', '.htaccess', 'portal/.htaccess', 'portal/schema.sql', 'portal/import-manifest.json']:
        payload[relative] = (ROOT / relative).read_bytes()
    return payload


def ensure_directory(ftp, relative):
    current = REMOTE
    for part in relative.split('/'):
        if not part:
            continue
        current += '/' + part
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            ftp.cwd(current)  # Confirma que a pasta existe e é acessível.
    ftp.cwd(REMOTE)


def upload(ftp, relative, data):
    parent = str(Path(relative).parent).replace('\\', '/')
    if parent != '.':
        ensure_directory(ftp, parent)
    ftp.storbinary('STOR ' + REMOTE + '/' + relative, io.BytesIO(data))


def php_string(value):
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def config_source(password):
    settings = {
        'db': {'dsn': 'mysql:host=' + DB_HOST + ';port=3306;dbname=' + DB_NAME + ';charset=utf8mb4', 'user': DB_USER, 'password': password},
        'site_url': SITE, 'base_path': '', 'force_https': True,
        'max_upload_bytes': 25 * 1024 * 1024, 'max_upload_files': 10,
    }
    encoded = base64.b64encode(json.dumps(settings).encode()).decode()
    return ('<?php\n$config = json_decode(base64_decode(' + php_string(encoded) + '), true);\n$config["document_root"] = dirname(__DIR__);\n$config["storage_path"] = __DIR__ . "/storage";\nreturn $config;\n').encode()


def setup_source(token):
    return ('<?php\n'
            'if ($_SERVER["REQUEST_METHOD"] !== "POST" || !isset($_POST["token"]) || !is_string($_POST["token"]) || !hash_equals(' + php_string(token) + ', $_POST["token"])) { http_response_code(404); exit; }\n'
            'header("Content-Type: application/json; charset=utf-8"); header("Cache-Control: no-store");\n'
            'if (PHP_VERSION_ID < 70400) { http_response_code(500); echo json_encode(["error" => "PHP 7.4 ou superior necessario", "php" => PHP_VERSION]); exit; }\n'
            'require __DIR__ . "/portal/src/bootstrap.php";\n'
            'require __DIR__ . "/portal/src/documents.php";\n'
            'require __DIR__ . "/portal/src/install.php";\n'
            'try { $result = install_portal("admin", "Administrador", $_POST["admin_password"] ?? ""); header("Content-Type: application/json"); echo json_encode($result); }\n'
            'catch (Throwable $exception) { error_log("Humcode install: " . $exception->getMessage()); http_response_code(500); header("Content-Type: application/json"); echo json_encode(["error" => "Instalacao interrompida. Consulte o log PHP."]); }\n').encode()


def verify_publication(manifest, admin_password, check_legacy=True):
    checks = []
    status, headers, body = http('/')
    if status != 303 or 'route=login' not in headers.get('Location', ''):
        raise RuntimeError('A página principal não direcionou ao login.')
    checks.append('pagina principal exige login')
    status, headers, body = http('/index.php?route=login')
    if status != 200 or b'Entrar no portal' not in body:
        raise RuntimeError('A tela de login não carregou.')
    cookies_header = headers.get('Set-Cookie', '').lower()
    if not all(flag in cookies_header for flag in ['secure', 'httponly', 'samesite=lax']):
        raise RuntimeError('O cookie de sessão não possui as proteções esperadas.')
    checks.append('login carregado')
    if check_legacy:
        for file in manifest['files']:
            status, headers, body = http('/' + urllib.parse.quote(file['stored_path']))
            if status != 303 or 'route=login' not in headers.get('Location', ''):
                raise RuntimeError('Link antigo não protegido: ' + file['stored_path'])
        checks.append(str(len(manifest['files'])) + ' links antigos exigem login')
    for path in ['/portal/config.php', '/portal/storage/', '/portal/src/bootstrap.php', '/portal/import-manifest.json']:
        if http(path)[0] != 403:
            raise RuntimeError('Arquivo privado acessível: ' + path)
    checks.append('configuracao, fontes e armazenamento protegidos')
    if http('/portal/assets/app.css')[0] != 200:
        raise RuntimeError('O CSS não está acessível.')
    checks.append('assets disponiveis')
    cookies = CookieJar()
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cookies))

    def session_request(path, values=None):
        request = urllib.request.Request(SITE + path, data=urllib.parse.urlencode(values).encode() if values is not None else None)
        response = open_response(opener, request)
        return response.status, response.headers, response.read()

    status, headers, body = session_request('/index.php?route=login')
    csrf = re.search(rb'name="csrf" value="([a-f0-9]+)"', body).group(1).decode()
    status, headers, body = session_request('/index.php?route=login', {'csrf': csrf, 'login': 'admin', 'password': admin_password})
    if status != 303 or 'route=password' not in headers.get('Location', ''):
        raise RuntimeError('A conta inicial não autenticou ou não exigiu troca de senha.')
    status, headers, body = session_request('/index.php?route=password')
    if status != 200:
        raise RuntimeError('A sessão autenticada não persistiu.')
    csrf = re.search(rb'name="csrf" value="([a-f0-9]+)"', body).group(1).decode()
    if session_request('/index.php?route=logout', {'csrf': csrf})[0] != 303:
        raise RuntimeError('O logout da verificação não foi concluído.')
    checks.append('login real, sessao e troca obrigatoria de senha verificados')
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true', help='Instala o banco e ativa a página principal; exige autorização do responsável.')
    args = parser.parse_args()
    password = os.environ.get('HUMCODE_FTP_PASSWORD') or getpass.getpass('Senha FTP: ')
    manifest = json.loads((ROOT / 'portal/import-manifest.json').read_text(encoding='utf-8'))
    payload = local_payload()
    with connect(password) as ftp:
        root_entries = {name: facts for name, facts in ftp.mlsd(REMOTE) if name not in ('.', '..')}
        for name in ['index.php', 'index.html', 'index.htm', '.htaccess', 'portal']:
            if name in root_entries:
                raise RuntimeError('Já existe ' + name + ' no servidor. Compare antes de publicar; nada foi alterado.')
        checked_files = 0
        for file in manifest['files']:
            digest = hashlib.sha256(remote_bytes(ftp, file['stored_path'])).hexdigest()
            if digest != file['sha256']:
                raise RuntimeError('Arquivo mudou desde a preparação: ' + file['stored_path'])
            checked_files += 1
        plan = {
            'mode': 'publish' if args.publish else 'check_only',
            'original_files_verified': checked_files,
            'new_subjects': len(manifest['subjects']),
            'tables': ['hc_portal_users', 'hc_portal_subjects', 'hc_portal_files', 'hc_portal_login_attempts'],
            'upload_files': sorted(payload) + ['portal/config.php'],
            'excluded': ['trabalho_datait'],
            'sha256': {path: hashlib.sha256(content).hexdigest() for path, content in payload.items()},
        }
        artifacts = ROOT / 'artifacts'
        artifacts.mkdir(exist_ok=True)
        (artifacts / 'publication-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if not args.publish:
            print(json.dumps({key: value for key, value in plan.items() if key not in ['sha256', 'upload_files']}, ensure_ascii=True))
            return
        db_password = os.environ.get('HUMCODE_DB_PASSWORD') or getpass.getpass('Senha MySQL: ')
        admin_password = os.environ.get('HUMCODE_ADMIN_PASSWORD') or secrets.token_urlsafe(18)
        if not 12 <= len(admin_password) <= 72:
            raise RuntimeError('A senha do administrador deve ter de 12 a 72 caracteres.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = ROOT / 'server-reference/backups' / stamp
        backup.mkdir(parents=True)
        (backup / 'before.json').write_text(json.dumps({'root_entries': root_entries, 'original_files': manifest['files'], 'main_files_previously_absent': True}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Protege os fontes antes de enviar credenciais ou qualquer configuração.
        upload(ftp, 'portal/.htaccess', payload['portal/.htaccess'])
        for path, content in payload.items():
            if path not in ['index.php', '.htaccess', 'portal/.htaccess']:
                upload(ftp, path, content)
        upload(ftp, 'portal/config.php', config_source(db_password))
        setup_name = 'portal-setup-' + secrets.token_hex(24) + '.php'
        token = secrets.token_hex(32)
        setup_created = False
        activated = []
        try:
            upload(ftp, setup_name, setup_source(token))
            setup_created = True
            if http('/' + setup_name)[0] != 404:
                raise RuntimeError('O instalador não está protegendo o acesso sem token.')
            status, headers, body = http('/' + setup_name, {'token': token, 'admin_password': admin_password})
            if status != 200:
                raise RuntimeError('Falha na instalação: ' + body.decode('utf-8', errors='replace')[:500])
            result = json.loads(body)
            if result['created_users'] != 1 or result['created_files'] != len(manifest['files']):
                raise RuntimeError('Contagens inesperadas na instalação: ' + json.dumps(result))
            ftp.delete(REMOTE + '/' + setup_name)
            setup_created = False
            activated.append('index.php')
            upload(ftp, 'index.php', payload['index.php'])
            activated.append('.htaccess')
            upload(ftp, '.htaccess', payload['.htaccess'])
            checks = verify_publication(manifest, admin_password)
            # Evidência de que o conteúdo anterior não foi movido nem alterado.
            for file in manifest['files']:
                if hashlib.sha256(remote_bytes(ftp, file['stored_path'])).hexdigest() != file['sha256']:
                    raise RuntimeError('Um original mudou durante a publicação: ' + file['stored_path'])
            result.update({'site': SITE, 'admin_login': 'admin', 'checks': checks, 'original_files_preserved': len(manifest['files'])})
            (artifacts / 'publication-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(dict(result, admin_temporary_password=admin_password), ensure_ascii=True))
        except Exception:
            # Os arquivos principais não existiam: removê-los restaura a entrada anterior.
            for path in reversed(activated):
                try:
                    ftp.delete(REMOTE + '/' + path)
                except ftplib.error_perm as error:
                    if not str(error).startswith('550'):
                        raise
            raise
        finally:
            if setup_created:
                ftp.delete(REMOTE + '/' + setup_name)


if __name__ == '__main__':
    main()
