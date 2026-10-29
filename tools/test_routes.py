"""Testa rotas públicas, compatibilidade e limites de acesso com banco temporário."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    args = parser.parse_args()
    php = Path(args.php)
    checks = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with test_server(php) as (base, connection, config, _, _, folder, environment):
        guest = portal.Client(base)
        canonical = {
            'home': '/biblioteca', 'login': '/entrar', 'password': '/minha-conta',
            'users': '/contas', 'subject&id=1': '/materias/1',
            'view&id=1': '/materiais/1', 'file&id=1': '/materiais/1/arquivo',
            'file&id=1&download=1': '/materiais/1/download',
            'edit-material&id=1': '/materiais/1/editar',
            'edit-subject&id=1': '/materias/1/editar',
            'unassigned': '/materiais/sem-materia',
            'home&q=oracle&page=2': '/biblioteca?q=oracle&page=2',
        }
        for route, expected in canonical.items():
            status, headers, _ = guest.request('route=' + route, follow_canonical=False)
            check(status == 308 and headers['Location'] == expected, 'Link antigo redireciona: ' + route)
        check(guest.request('/?route=login', follow_canonical=False)[1]['Location'] == '/entrar', 'Link antigo na raiz redireciona')
        check(guest.request('/biblioteca')[1]['Location'] == '/entrar', 'Biblioteca nova exige login')
        check(guest.request('/materiais/1')[1]['Location'] == '/entrar', 'Material novo exige login')
        check(guest.login()[1]['Location'] == '/materiais/1', 'Login conserva o destino com URL limpa')
        token = guest.csrf('/biblioteca')
        status, _, body = guest.request('/biblioteca')
        check(status == 200 and b'/index.php?' not in body, 'Biblioteca gera somente links e formulários novos')
        check(guest.request('/materiais/1?route=users&id=999999&legacy_path=portal/config.php')[0] == 200, 'Parâmetros não substituem a rota nem o ID do caminho')
        check(guest.request('/materiais/999999')[0] == 404, 'ID inexistente mantém resposta 404')
        check(guest.request('/materiais/abc')[0] == 404, 'Caminho de material inválido mantém resposta 404')
        check(guest.request('/portal/config.php')[0] == 403, 'Configuração continua protegida')
        for path in ('/materiais/excluir', '/materiais/atualizar', '/materias/excluir', '/contas/atualizar', '/sair'):
            check(guest.request(path)[0] == 405, 'GET não altera dados: ' + path)
        check(guest.request('/materias/criar', {'csrf': 'invalid', 'name': 'Indevida'})[0] == 403, 'Rota nova valida CSRF')
        status, headers, _ = guest.request('/materias/criar', {'csrf': token, 'name': 'Teste de rotas', 'color': 'teal'})
        check(status == 303 and re.fullmatch(r'/materias/[0-9]+', headers['Location']), 'Criação por POST redireciona para matéria limpa')
        subject = int(headers['Location'].rsplit('/', 1)[1])
        check(guest.multipart('/materiais/enviar', {'csrf': token, 'subject_id': subject, 'expected_files': 1}, [('rota.txt', 'text/plain', b'Bytes da rota')], 'documents[]')[0] == 303, 'Upload funciona no endereço novo')
        material = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'rota.txt'").fetchone()[0]
        check(guest.request('/materiais/' + str(material) + '/download')[2] == b'Bytes da rota', 'Download novo preserva os bytes')
        member = portal.Client(base)
        check(member.login('aluno', portal.MEMBER_PASSWORD)[0] == 303, 'Estudante autentica nas rotas novas')
        check(member.request('/contas')[0] == 403, 'Contas continuam exclusivas de administradores')
        check(member.request('/materiais/' + str(material) + '/editar')[0] == 403, 'Estudante não edita pelo endereço novo')
        check(member.request('/materiais/' + str(material) + '/download')[2] == b'Bytes da rota', 'Estudante baixa pelo endereço novo')
        script = folder / 'destinations.php'
        script.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; echo json_encode(array_map("local_destination", json_decode(stream_get_contents(STDIN), true)));', encoding='utf-8')
        unsafe = ['/sair', '/contas', '/materias/1/editar', '/materiais/1/editar', '/materiais/excluir', '/minha-conta/foto/atualizar', '//example.com', '/%2fexample.com', '/materias/../portal/config.php', '/?route=logout']
        result = subprocess.run([str(php), '-n', str(script)], input=json.dumps(unsafe).encode(), env=environment, capture_output=True, check=True)
        check(json.loads(result.stdout) == [None] * len(unsafe), 'Retorno do login recusa destinos de alteração, externos e travessia')
        config.write_text(config.read_text(encoding='utf-8').replace('"base_path" => ""', '"base_path" => "/estudos"'), encoding='utf-8')
        script.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; echo json_encode([url("subject", ["id"=>12]), url("file", ["id"=>3,"download"=>1]), local_destination("/estudos/materiais/3"), local_destination("/materiais/3")]);', encoding='utf-8')
        result = subprocess.run([str(php), '-n', str(script)], env=environment, capture_output=True, check=True)
        check(json.loads(result.stdout) == ['/estudos/materias/12', '/estudos/materiais/3/download', '/estudos/materiais/3', None], 'Rotas e retorno respeitam instalações em subpasta')

    files = ['.htaccess', 'portal/src/bootstrap.php', 'portal/src/controller.php', 'portal/src/views.php', 'portal/assets/app.js']
    report = {'status': 'passed', 'verified_at': datetime.now(timezone.utc).isoformat(), 'checks_count': len(checks), 'checks': checks, 'sha256': {name: hashlib.sha256((portal.ROOT / name).read_bytes()).hexdigest() for name in files}}
    (portal.ROOT / 'artifacts/routes-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
