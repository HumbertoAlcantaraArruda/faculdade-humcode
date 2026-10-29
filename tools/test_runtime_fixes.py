"""Regressões de uploads, redirecionamentos, senhas e compatibilidade do banco."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import test_portal as portal


@contextmanager
def test_server(php, settings=()):
    with tempfile.TemporaryDirectory(prefix='humcode-runtime-tests-') as temporary:
        folder = Path(temporary)
        connection, config, storage, manifest = portal.create_fixture(folder, php)
        sessions = folder / 'sessions'
        sessions.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        command = [str(php), '-n']
        for setting in ['display_errors=0', 'extension_dir=' + str(php.parent / 'ext'), 'extension=pdo_sqlite', 'extension=fileinfo', 'session.save_path=' + str(sessions), 'upload_tmp_dir=' + str(folder), 'upload_max_filesize=26M', 'post_max_size=30M', *settings]:
            command.extend(['-d', setting])
        command.extend(['-S', '127.0.0.1:' + str(port), '-t', str(portal.ROOT), str(portal.ROOT / 'tools/dev-router.php')])
        environment = dict(os.environ, HUMCODE_CONFIG_FILE=str(config))
        with (folder / 'php.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, env=environment, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(50):
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2):
                            break
                    except OSError:
                        time.sleep(.1)
                yield 'http://127.0.0.1:' + str(port), connection, config, storage, manifest, folder, environment
            except Exception:
                print((folder / 'php.log').read_text(encoding='utf-8', errors='replace')[-4000:])
                raise
            finally:
                process.terminate()
                process.wait(timeout=10)
                connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser')
    args = parser.parse_args()
    php = Path(args.php)
    checks = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with test_server(php) as (base, connection, config, storage, manifest, folder, environment):
        if args.browser:
            portal.capture_previews(base, args.browser, folder / 'screenshots')
            check(True, 'Interface completa validada em Chrome desktop e celular')
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
                page = browser.new_page()
                page.goto(base + '/index.php?route=login')
                page.get_by_label('Usuário', exact=True).fill('admin')
                page.get_by_label('Senha', exact=True).fill(portal.ADMIN_PASSWORD)
                page.get_by_role('button', name='Entrar no portal').click()
                page.wait_for_url('**/biblioteca')
                page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
                result = page.locator('#upload-dialog').evaluate('''form => {
                    const input = form.querySelector('input[type="file"]');
                    const data = new DataTransfer();
                    for (const name of ['a.txt', 'b.txt']) data.items.add(new File([new Uint8Array(16 * 1024 * 1024)], name));
                    input.files = data.files;
                    input.dispatchEvent(new Event('change', {bubbles:true}));
                    return {invalid:!input.checkValidity(), count:form.querySelector('[data-upload-count]').value, error:form.querySelector('[data-upload-error]').textContent};
                }''')
                check(result['invalid'] and result['count'] == '2' and 'limite total' in result['error'], 'Navegador bloqueia lote de 32 MiB e mantém a contagem dos arquivos')
                page.goto(base + '/index.php?route=password')
                password = page.locator('input[name="password"]')
                password.fill('é' * 40)
                check(not password.evaluate('input => input.checkValidity()'), 'Navegador recusa senha de 80 bytes antes do envio')
                password.fill('é' * 12)
                check(password.evaluate('input => input.checkValidity()'), 'Navegador aceita senha acentuada dentro dos limites')
                browser.close()
        existing = portal.run_checks(base, connection, storage, manifest)
        print('EXISTING_CHECKS_PASSED', len(existing), flush=True)
        client = portal.Client(base)
        client.request('route=view&id=1')
        check(client.login()[1]['Location'] == '/materiais/1', 'Login retoma o material solicitado')
        legacy = portal.Client(base)
        legacy.request('/SOI/Threads.html')
        check(legacy.login()[1]['Location'] == '/SOI/Threads.html', 'Login retoma o endereço legado')
        admin = portal.Client(base)
        check(admin.login()[0] == 303, 'Administrador autentica nas regressões')
        token = admin.csrf()
        for password, expected, label in [('é' * 40, 400, 'Senha acima de 72 bytes recusada'), ('é' * 6, 400, 'Senha de seis caracteres recusada mesmo com doze bytes'), ('Senha-Nula-123\0', 400, 'Senha com NUL recusada sem erro interno'), ('é' * 12, 303, 'Senha acentuada dentro dos limites aceita')]:
            status = admin.request('route=create-user', {'csrf': token, 'login': 'senha.' + str(len(checks)), 'name': 'Teste de senha', 'password': password})[0]
            check(status == expected, label)
        subject = connection.execute('SELECT id FROM hc_portal_subjects LIMIT 1').fetchone()[0]
        before = connection.execute('SELECT COUNT(*) FROM hc_portal_files').fetchone()[0]
        status = admin.multipart('route=upload', {'csrf': token, 'subject_id': subject, 'expected_files': 3}, [('faltante.txt', 'text/plain', b'Um arquivo')], 'documents[]')[0]
        check(status == 400 and connection.execute('SELECT COUNT(*) FROM hc_portal_files').fetchone()[0] == before, 'Lote incompleto recusado antes de salvar arquivos')
        check(admin.multipart('route=upload', {'csrf': token, 'subject_id': subject}, [('antigo.txt', 'text/plain', b'Um arquivo')], 'documents[]')[0] == 400, 'Formulário antigo sem contagem não permite sucesso parcial')
        connection.execute('ALTER TABLE hc_portal_subjects DROP COLUMN revision')
        connection.commit()
        check(admin.request('route=home')[0] == 503, 'Esquema antigo retorna manutenção em vez de formulário inválido')
        connection.execute('ALTER TABLE hc_portal_subjects ADD COLUMN revision INT NOT NULL DEFAULT 1')
        connection.commit()
        check(admin.request('route=home')[0] == 200, 'Esquema atualizado libera o portal')
        failure = folder / 'failure.php'
        failure.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; throw new RuntimeException("TEST_FAILURE");', encoding='utf-8')
        result = subprocess.run([str(php), '-n', str(failure)], env=environment, capture_output=True)
        check(result.returncode == 1, 'Exceção CLI retorna código de falha')
        result = subprocess.run([str(php), '-n', str(failure)], env=dict(environment, HUMCODE_CONFIG_FILE=str(folder / 'missing.php')), capture_output=True)
        check(result.returncode == 1, 'Configuração ausente retorna falha na CLI')
        cases = folder / 'destinations.php'
        cases.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; echo json_encode(array_map("local_destination", json_decode(stream_get_contents(STDIN), true)));', encoding='utf-8')
        unsafe = ['https://example.com/', '//example.com/', '/%2fexample.com/', '/index.php\r\nLocation: https://example.com', '/portal/config.php', '/index.php?route=logout', '/SOI/../portal/config.php', '/%5cexample.com']
        result = subprocess.run([str(php), '-n', str(cases)], input=json.dumps(unsafe).encode(), env=environment, capture_output=True, check=True)
        check(json.loads(result.stdout) == [None] * len(unsafe), 'Retorno do login recusa URLs externas, travessia e rotas de alteração')

    with test_server(php) as (base, _, config, _, _, _, _):
        source = config.read_text(encoding='utf-8')
        config.write_text(source.replace('"force_https" => false', '"force_https" => true').replace('http://127.0.0.1', 'https://www.exemplo.com.br'), encoding='utf-8')
        for path in ['/SOI/Threads.html', '/index.php?route=view&id=1', '/index.php?route=login']:
            status, headers, _ = portal.Client(base).request(path)
            check(status == 302 and headers['Location'] == 'https://www.exemplo.com.br' + path, 'HTTPS preserva caminho e parâmetros: ' + path)

    with test_server(php, ['max_file_uploads=3']) as (base, connection, _, storage, _, _, _):
        admin = portal.Client(base)
        admin.login()
        token = admin.csrf()
        subject = connection.execute('SELECT id FROM hc_portal_subjects LIMIT 1').fetchone()[0]
        status = admin.upload(token, subject, [('parcial-' + str(i) + '.txt', 'text/plain', b'Arquivo') for i in range(4)])[0]
        check(status == 400 and not list(storage.iterdir()), 'Truncamento pelo PHP não salva parte do lote')
        page = admin.request('route=home')[2]
        check(b'data-max-files="3"' in page, 'Interface anuncia o limite efetivo do PHP')

    with test_server(php, ['upload_max_filesize=400K', 'post_max_size=512K']) as (base, connection, _, storage, _, _, _):
        admin = portal.Client(base)
        admin.login()
        token = admin.csrf()
        subject = connection.execute('SELECT id FROM hc_portal_subjects LIMIT 1').fetchone()[0]
        status = admin.upload(token, subject, [('lote-a.txt', 'text/plain', b'A' * (240 * 1024)), ('lote-b.txt', 'text/plain', b'B' * (240 * 1024))])[0]
        check(status == 413 and not list(storage.iterdir()), 'Soma acima do orçamento do lote é recusada sem gravação parcial')

    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'existing_http_checks': len(existing), 'regression_checks': len(checks), 'total_checks': len(existing) + len(checks), 'browser_checked': bool(args.browser), 'database': 'SQLite temporário; produção não alterada', 'checks': checks}
    (portal.ROOT / 'artifacts/runtime-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'checks'}, ensure_ascii=True))


if __name__ == '__main__':
    main()
