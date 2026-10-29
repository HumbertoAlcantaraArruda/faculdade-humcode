"""Testes HTTP isolados. Não acessam FTP nem o banco de produção."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSWORD = 'Teste-Local-Admin-123!'
MEMBER_PASSWORD = 'Teste-Local-Aluno-123!'


def photo_png(color=(38, 150, 125), width=2, height=2):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = (b'\x00' + bytes(color) * width) * height
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, route='', data=None, content_type=None, follow_canonical=True):
        target = route if route.startswith('/') else '/index.php?' + route
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
        headers = {'Content-Type': content_type or 'application/x-www-form-urlencoded'} if data is not None else {}
        req = urllib.request.Request(self.base + target, data=data, headers=headers)
        try:
            response = self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        body = response.read()
        if follow_canonical and data is None and response.status == 308:
            destination = response.headers.get('Location', '')
            assert destination.startswith('/') and not destination.startswith('//'), destination
            return self.request(destination, follow_canonical=False)
        return response.status, response.headers, body

    def csrf(self, route='route=home'):
        status, headers, body = self.request(route)
        assert status == 200, (status, body[:150])
        return re.search(rb'name="csrf" value="([a-f0-9]+)"', body).group(1).decode()

    def trust(self, name, value):
        """Cookie de navegador lembrado pela validação em 2 etapas."""
        host = urllib.parse.urlsplit(self.base).hostname
        self.cookies.set_cookie(http.cookiejar.Cookie(0, name, value, None, False, host, False, False, '/', True, False, None, False, None, None, {}))

    def login(self, username='admin', password=ADMIN_PASSWORD):
        token = self.csrf('route=login')
        return self.request('route=login', {'csrf': token, 'login': username, 'password': password})

    def upload(self, token, subject, files):
        return self.multipart('route=upload', {'csrf': token, 'subject_id': subject, 'expected_files': len(files)}, files, 'documents[]')

    def multipart(self, route, fields, files=(), file_field='replacement'):
        boundary = 'HumcodeBoundary' + os.urandom(10).hex()
        body = bytearray()
        for name, value in fields.items():
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for filename, mime, content in files:
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
            body.extend(content)
            body.extend(b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode())
        return self.request(route, bytes(body), f'multipart/form-data; boundary={boundary}')


def sent_mail(folder):
    """Mensagens gravadas pelo transporte de arquivo dos testes, da mais antiga para a mais recente."""
    return [json.loads(path.read_text(encoding='utf-8')) for path in sorted((Path(folder) / 'mail').glob('*.json'))]


def mail_code(folder, to=None):
    """Código de 6 números da mensagem mais recente (opcionalmente para um destinatário)."""
    messages = [m for m in sent_mail(folder) if to is None or m['to'] == to]
    assert messages, 'Nenhum e-mail enviado' + ('' if to is None else ' para ' + to)
    return re.search(r'\b(\d{6})\b', messages[-1]['text']).group(1)


def php_literal(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def create_fixture(folder, php):
    legacy = folder / 'legacy'
    storage = folder / 'storage'
    legacy.mkdir()
    storage.mkdir()
    schema = (ROOT / 'portal/schema.sql').read_text(encoding='utf-8')
    schema = schema.replace('BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
    schema = re.sub(r'UNIQUE KEY \w+ ', 'UNIQUE ', schema)
    schema = re.sub(r'^    KEY \w+ .*\n', '', schema, flags=re.M)
    schema = re.sub(r' ENGINE=InnoDB[^;]*;', ';', schema)
    connection = sqlite3.connect(folder / 'portal.sqlite')
    connection.executescript(schema)
    for login, name, password, role in [('admin', 'Admin Teste', ADMIN_PASSWORD, 'admin'), ('aluno', 'Aluno Teste', MEMBER_PASSWORD, 'member')]:
        password_hash = subprocess.check_output([str(php), '-n', '-r', f'echo password_hash({php_literal(password)}, PASSWORD_BCRYPT, ["cost" => 4]);']).decode()
        connection.execute('INSERT INTO hc_portal_users (login, name, password_hash, role, must_change_password) VALUES (?, ?, ?, ?, 0)', (login, name, password_hash, role))
    manifest = json.loads((ROOT / 'portal/import-manifest.json').read_text(encoding='utf-8'))
    subjects = {}
    for item in manifest['subjects']:
        cursor = connection.execute('INSERT INTO hc_portal_subjects (name, description, color) VALUES (?, ?, ?)', (item['name'], item['description'], item['color']))
        subjects[item['key']] = cursor.lastrowid
    for item in manifest['files']:
        path = legacy / item['stored_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ('<!doctype html><html><head><title>' + item['title'] + '</title></head><body><h1>Material de teste</h1><script>document.body.dataset.interativo="sim"</script></body></html>').encode()
        if item['extension'] == 'pdf':
            content = b'%PDF-1.4\nfixture de teste\n%%EOF'
        path.write_bytes(content)
        connection.execute('INSERT INTO hc_portal_files (subject_id, title, original_name, stored_path, source, extension, mime, size, sha256, trusted_app) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (subjects[item['subject']], item['title'], item['original_name'], item['stored_path'], 'legacy', item['extension'], item['mime'], item['size'], hashlib.sha256(content).hexdigest(), int(item['trusted_app'])))
    (legacy / 'trab/api.php').write_text('<?php header("Content-Type: application/json"); echo json_encode(["ok" => true]);', encoding='utf-8')
    (legacy / 'materiais_fipp_bsi.php').write_text('<?php $secret = "nao-pode-vazar";', encoding='utf-8')
    (legacy / 'portfolio/assets').mkdir(parents=True, exist_ok=True)
    (legacy / 'portfolio/assets/test.js').write_text('window.portfolio = true;', encoding='utf-8')
    connection.execute("UPDATE hc_portal_files SET legacy_path = stored_path WHERE source = 'legacy'")
    connection.commit()
    (folder / 'mail').mkdir()
    config = folder / 'config.php'
    config.write_text('<?php return ["db" => ["dsn" => ' + php_literal('sqlite:' + str(folder / 'portal.sqlite')) + '], "base_path" => "", "site_url" => "http://127.0.0.1", "force_https" => false, "document_root" => ' + php_literal(legacy) + ', "storage_path" => ' + php_literal(storage) + ', "max_upload_bytes" => 25 * 1024 * 1024, "max_upload_files" => 10, "two_factor_required_roles" => [], "mail" => ["transport" => "file", "directory" => ' + php_literal(folder / 'mail') + ']];', encoding='utf-8')
    return connection, config, storage, manifest


def card_count(body, href):
    """Quantidade exibida no card da biblioteca que leva a href, ou None sem card."""
    for card in re.findall(rb'<article class="subject-card">(.*?)</article>', body):
        if f'href="{href}"'.encode() in card:
            return int(re.search(rb'(\d+) materia', card).group(1))
    return None


def run_checks(base, connection, storage, manifest):
    passed = []

    def check(condition, label):
        assert condition, label
        passed.append(label)

    guest = Client(base)
    check(guest.request('route=home')[0] == 303, 'Página inicial exige login')
    for item in manifest['files']:
        check(guest.request('/' + urllib.parse.quote(item['stored_path']))[0] == 303, 'Link antigo protegido: ' + item['stored_path'])
    check(guest.request('/portal/config.php')[0] == 403, 'Configuração inacessível pela web')
    check(guest.request('route=login', {'csrf': 'invalido', 'login': 'admin', 'password': ADMIN_PASSWORD})[0] == 403, 'Login valida CSRF')
    check(guest.login(password='senha-errada')[0] == 401, 'Senha incorreta recusada')
    prior_session = next(iter(guest.cookies)).value
    check(guest.login()[0] == 303, 'Login do administrador')
    check(next(iter(guest.cookies)).value != prior_session, 'Identificador de sessão renovado no login')
    admin = guest
    status, headers, body = admin.request('route=home')
    check(status == 200 and b'<h1>Biblioteca</h1>' in body, 'Biblioteca renderiza em português')
    check('Ferramentas Computacionais III'.encode() in body, 'Matérias existentes aparecem no portal')
    bd2 = connection.execute("SELECT id FROM hc_portal_subjects WHERE name = 'Banco de Dados II'").fetchone()[0]
    check(b'class="subject-card"' in body and f'href="/materias/{bd2}"'.encode() in body and b'materials-table' not in body, 'Biblioteca mostra cards que levam à matéria')
    check(admin.request(f'route=subject&id={bd2}&page=2')[0] == 200, 'Paginação dos materiais')
    check(admin.request(f'route=subject&id={bd2}&q=Gatilhos')[2].count('Gatilhos no Oracle'.encode()) > 0, 'Busca encontra um material')
    check(admin.request(f'route=subject&id={bd2}&q=xyz-inexistente')[2].count('Nenhum material encontrado'.encode()) > 0, 'Busca vazia tem estado informativo')
    check(admin.request('route=legacy&path=../config.php')[0] == 404, 'Travessia de diretórios recusada')
    check(admin.request('route=legacy&path=materiais_fipp_bsi.php')[0] == 404, 'Fontes PHP antigas não são expostas')
    check(admin.request('/portfolio/assets/test.js')[0] == 200, 'Recursos do portfólio passam pela autenticação')
    check(admin.request('/portfolio')[0] == 200, 'Portfólio abre sem barra no final do endereço')
    check(admin.request('/trab/')[0] == 200, 'Aplicação de estudo abre pela pasta antiga')
    check(admin.request('/trab/api.php')[0] == 200, 'Aplicação antiga acessível após login')
    check(admin.request('/trab/api.php', {'acao': 'comentario'})[0] == 403, 'API antiga valida CSRF em gravações')
    token = admin.csrf()
    check(admin.request('/trab/api.php', {'csrf': token, 'acao': 'comentario'})[0] == 200, 'API antiga aceita formulário autenticado com CSRF')
    check(admin.request('route=create-subject', {'csrf': 'invalido', 'name': 'Não criar'})[0] == 403, 'Criação de matéria valida CSRF')
    check(admin.request('route=create-subject', {'csrf': token, 'name': 'Redes de Computadores', 'description': 'Protocolos e redes', 'color': 'blue'})[0] == 303, 'Criação de matéria')
    subject = connection.execute('SELECT id FROM hc_portal_subjects WHERE name = ?', ('Redes de Computadores',)).fetchone()[0]
    check(admin.request('route=create-subject', {'csrf': token, 'name': 'Redes de Computadores'})[0] == 303, 'Matérias duplicadas tratadas sem erro interno')
    check('Adicione um arquivo para começar esta biblioteca.'.encode() in admin.request('route=subject&id=' + str(subject))[2], 'Matéria nova exibe convite para primeiro upload')
    count_before = connection.execute('SELECT COUNT(*) FROM hc_portal_files').fetchone()[0]
    check(admin.upload(token, subject, [('arquivo.php', 'application/x-php', b'<?php echo 1;')])[0] == 400, 'Upload de executável PHP bloqueado')
    check(admin.upload(token, subject, [('falso.pdf', 'application/pdf', b'isto nao e um PDF')])[0] == 400, 'Conteúdo diferente da extensão bloqueado')
    check(admin.upload(token, subject, [('ok.txt', 'text/plain', b'Conteudo valido'), ('ruim.php', 'text/plain', b'<?php echo 1;')])[0] == 400, 'Lote inválido não publica arquivos parciais')
    check(admin.upload(token, subject, [('arquivo' + str(index) + '.txt', 'text/plain', b'Um material') for index in range(11)])[0] == 400, 'Limite de dez arquivos validado no servidor')
    check(admin.upload(token, subject, [('grande.txt', 'text/plain', b'A' * (25 * 1024 * 1024 + 1))])[0] == 400, 'Limite de tamanho validado no servidor')
    check(connection.execute('SELECT COUNT(*) FROM hc_portal_files').fetchone()[0] == count_before and not list(storage.iterdir()), 'Uploads recusados não deixam dados nem arquivos')
    contents = b'Conteudo enviado pelo teste HTTP.\n'
    html = b'<!doctype html><html><body><h1>Interativo</h1><script>document.body.dataset.ready="yes";</script></body></html>'
    check(admin.upload(token, subject, [('resumo.txt', 'text/plain', contents), ('interativo.html', 'text/html', html)])[0] == 303, 'Upload múltiplo de documentos válidos')
    uploaded = connection.execute("SELECT id, stored_path FROM hc_portal_files WHERE source = 'upload' AND extension = 'txt'").fetchone()
    html_id = connection.execute("SELECT id FROM hc_portal_files WHERE source = 'upload' AND extension = 'html'").fetchone()[0]
    check(re.fullmatch(r'[a-f0-9]{48}\.bin', uploaded[1]) is not None, 'Upload usa nome aleatório sem extensão executável')
    status, headers, downloaded = admin.request('route=file&id=' + str(uploaded[0]) + '&download=1')
    check(status == 200 and downloaded == contents and 'attachment' in headers['Content-Disposition'], 'Download entrega os mesmos bytes como anexo')
    status, headers, response = admin.request('route=file&id=' + str(html_id))
    check(status == 200 and 'sandbox' in headers['Content-Security-Policy'] and 'allow-same-origin' not in headers['Content-Security-Policy'], 'HTML enviado é isolado da origem do portal')
    check(admin.request('route=view&id=' + str(html_id))[0] == 200, 'Página de visualização do material enviado')
    original_id = connection.execute("SELECT id FROM hc_portal_files WHERE source = 'legacy' AND extension = 'html'").fetchone()[0]
    status, headers, original = admin.request('route=file&id=' + str(original_id))
    check(status == 200 and b'<base href=' in original and 'sandbox' not in headers['Content-Security-Policy'], 'HTML original mantém scripts e caminhos relativos')
    source_path = storage.parent / 'legacy/trab/index.php'
    source_bytes = source_path.read_bytes()
    source_path.write_bytes(b'<?php $senha = "nao-expor"; ?>')
    legacy_php_id = connection.execute("SELECT id FROM hc_portal_files WHERE stored_path = 'trab/index.php'").fetchone()[0]
    check(admin.request('route=file&id=' + str(legacy_php_id) + '&download=1')[0] == 404, 'PHP alterado para conter código nunca é baixado como fonte')
    source_path.write_bytes(source_bytes)
    check(admin.upload(token, subject, [('<img src=x onerror=alert(1)>.txt', 'text/plain', b'Teste de nome escapado')])[0] == 303, 'Nome de arquivo não é usado como caminho do armazenamento')
    escaped_page = admin.request('route=subject&id=' + str(subject))[2]
    check(b'&lt;img src=x onerror=alert(1)&gt;' in escaped_page and b'<img src=x onerror=alert(1)>' not in escaped_page, 'Nomes de arquivos são escapados na interface')
    missing_id = connection.execute("INSERT INTO hc_portal_files (subject_id,title,original_name,stored_path,source,extension,mime,size,sha256) VALUES (?,?,?,?,?,?,?,?,?)", (subject,'Invalido','invalido.txt','../config.php','upload','txt','text/plain',1,'0'*64)).lastrowid
    connection.commit()
    check(admin.request('route=file&id=' + str(missing_id))[0] == 404, 'Download rejeita caminho fora do armazenamento')
    member = Client(base)
    check(member.login('aluno', MEMBER_PASSWORD)[0] == 303, 'Login de estudante')
    member_token = member.csrf()
    check(member.request('route=users')[0] == 403, 'Estudante não acessa administração')
    check(member.request('route=create-user', {'csrf': member_token, 'name': 'Intruso', 'login': 'intruso', 'password': MEMBER_PASSWORD})[0] == 403, 'Estudante não cria contas')
    check(admin.upload(token, subject, [('aluno.txt', 'text/plain', b'Material enviado antes da restricao')])[0] == 303, 'Administrador prepara arquivo para testar autoria anterior de estudante')
    former_upload = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'aluno.txt'").fetchone()[0]
    member_id = connection.execute("SELECT id FROM hc_portal_users WHERE login = 'aluno'").fetchone()[0]
    connection.execute('UPDATE hc_portal_files SET uploaded_by = ? WHERE id = ?', (member_id, former_upload))
    connection.commit()
    check_read_only_access(member, connection, storage, subject, member_token, former_upload, check)
    check(member.request('route=file&id=' + str(uploaded[0]) + '&download=1')[2] == contents, 'Contas compartilham os mesmos documentos')
    check_material_management(admin, member, connection, storage, subject, token, member_token, uploaded[0], original_id, check)
    check_subject_management(admin, member, connection, storage, token, member_token, check)
    check_profile_photos(admin, member, connection, storage, token, member_token, check)
    initial = 'Primeiro-Acesso-123!'
    check(admin.request('route=create-user', {'csrf': token, 'name': 'Nova Pessoa', 'login': 'nova.pessoa@example.com', 'password': initial, 'role': 'member'})[0] == 303, 'Administrador cria conta')
    fresh = Client(base)
    status, headers, response = fresh.login('nova.pessoa@example.com', initial)
    check(status == 303 and '/minha-conta' in headers['Location'], 'Primeiro acesso exige troca de senha')
    check('/minha-conta' in fresh.request('route=file&id=' + str(uploaded[0]))[1]['Location'], 'Senha temporária não dá acesso aos materiais')
    check('/minha-conta' in fresh.multipart('route=update-photo', {'csrf': fresh.csrf('route=password'), 'action': 'upload'}, [('foto.png', 'image/png', photo_png())], 'photo')[1]['Location'], 'Troca de senha obrigatoria antecede a edicao da foto')
    fresh_token = fresh.csrf('route=password')
    check(fresh.request('route=password', {'csrf': fresh_token, 'current_password': initial, 'password': 'Senha-Pessoal-Nova-123!', 'password_confirmation': 'Senha-Pessoal-Nova-123!'})[0] == 303, 'Troca de senha no primeiro acesso')
    check(fresh.request('route=home')[0] == 200, 'Conta acessa portal depois de trocar senha')
    check(b'class="user-menu-email">nova.pessoa@example.com</p>' in fresh.request('route=home')[2], 'Menu do usuario exibe o login quando for um e-mail')
    new_id = connection.execute('SELECT id FROM hc_portal_users WHERE login = ?', ('nova.pessoa@example.com',)).fetchone()[0]
    check(admin.request('route=update-user', {'csrf': token, 'id': new_id, 'action': 'reset', 'password': 'Outra-Temporaria-123!'})[0] == 303, 'Administrador redefine senha')
    check('/entrar' in fresh.request('route=home')[1]['Location'], 'Redefinição invalida sessões anteriores')
    member_id = connection.execute('SELECT id FROM hc_portal_users WHERE login = ?', ('aluno',)).fetchone()[0]
    check(admin.request('route=update-user', {'csrf': token, 'id': member_id, 'action': 'toggle'})[0] == 303, 'Administrador desativa conta')
    check('/entrar' in member.request('route=home')[1]['Location'], 'Desativação encerra acesso de uma sessão ativa')
    check('/entrar' in member.request('route=photo')[1]['Location'], 'Conta desativada perde acesso a foto')
    check(admin.request('route=update-user', {'csrf': token, 'id': 1, 'action': 'toggle'})[0] == 400, 'Administrador não pode desativar a própria conta')
    check(admin.request('route=logout')[0] == 405, 'Logout exige POST')
    check(admin.request('route=logout', {'csrf': token})[0] == 303, 'Logout encerra sessão')
    check(admin.request('route=home')[0] == 303, 'Sessão encerrada não acessa materiais')
    attacker = Client(base)
    for attempt in range(8):
        check(attacker.login('usuario-inexistente', 'errada')[0] == 401, 'Tentativa inválida contabilizada ' + str(attempt + 1))
    check(attacker.login('usuario-inexistente', 'errada')[0] == 429, 'Limite de tentativas de login aplicado')
    return passed


def check_profile_photos(admin, member, connection, storage, admin_token, token, check):
    guest = Client(member.base)
    check(guest.request('route=photo')[0] == 303, 'Foto exige autenticacao')
    check(guest.request('route=update-photo', {'csrf': token, 'action': 'remove'})[0] == 303, 'Alterar foto exige autenticacao')
    check(member.request('route=photo')[0] == 404, 'Conta sem foto retorna 404 e usa iniciais')
    check(member.request('route=update-photo')[0] == 405, 'Alterar foto exige POST')
    check(member.multipart('route=update-photo', {'csrf': 'invalido', 'action': 'upload'}, [('foto.png', 'image/png', photo_png())], 'photo')[0] == 403, 'Upload de foto valida CSRF')
    check(member.request('route=update-photo', {'csrf': token, 'action': 'upload'})[0] == 400, 'Foto obrigatoria no envio')
    check(member.request('route=update-photo', {'csrf': token, 'action': 'invalida'})[0] == 400, 'Acao de foto desconhecida recusada')
    tables_before = {t: connection.execute('SELECT * FROM ' + t + ' ORDER BY id').fetchall() for t in ['hc_portal_users', 'hc_portal_subjects', 'hc_portal_files']}
    photo = photo_png()
    admin_photo = photo_png((190, 70, 90))
    check(admin.multipart('route=update-photo', {'csrf': admin_token, 'action': 'upload'}, [('admin.png', 'image/png', admin_photo)], 'photo')[0] == 303, 'Administrador envia sua foto')
    check(member.multipart('route=update-photo', {'csrf': token, 'action': 'upload', 'id': 1, 'user_id': 1, 'role': 'admin'}, [('foto.png', 'image/png', photo)], 'photo')[0] == 303, 'Usuario normal envia foto apenas para a propria conta')
    status, headers, body = member.request('route=photo&id=1&user_id=1')
    check(status == 200 and body == photo and headers['Content-Type'] == 'image/png', 'Foto servida corresponde a sessao e ignora outro id')
    check('no-store' in headers['Cache-Control'] and headers['X-Content-Type-Options'] == 'nosniff' and 'sandbox' in headers['Content-Security-Policy'], 'Foto privada possui protecoes de cache e conteudo')
    check(admin.request('route=photo')[2] == admin_photo, 'Foto de outra pessoa permanece intacta')
    for route, expected in [('route=home', 2), ('route=password', 3)]:
        body = member.request(route)[2]
        check(body.count(b'class="profile-photo"') == expected, 'Foto na sidebar e header: ' + route)
    invalid = [('script.svg', 'image/svg+xml', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'), ('falsa.png', 'image/png', b'<?php echo "invalido"; ?>'), ('foto.php', 'image/png', photo), ('grande.png', 'image/png', photo + b'0' * (2 * 1024 * 1024)), ('larga.png', 'image/png', photo_png(width=4097))]
    before = {p.name: p.read_bytes() for p in storage.iterdir() if p.is_file()}
    for filename, mime, content in invalid:
        check(member.multipart('route=update-photo', {'csrf': token, 'action': 'upload'}, [(filename, mime, content)], 'photo')[0] == 400, 'Foto invalida recusada: ' + filename)
    check({p.name: p.read_bytes() for p in storage.iterdir() if p.is_file()} == before, 'Falhas de foto preservam as fotos anteriores e nao deixam temporarios')
    replacement = photo_png((50, 80, 200))
    check(member.multipart('route=update-photo', {'csrf': token, 'action': 'upload'}, [('nova.png', 'image/png', replacement)], 'photo')[0] == 303, 'Foto pode ser substituida')
    check(member.request('route=photo')[2] == replacement and len(list(storage.glob('avatar-*.image'))) == 2, 'Substituicao atualiza binario sem acumular fotos antigas')
    another_session = Client(member.base)
    check(another_session.login('aluno', MEMBER_PASSWORD)[0] == 303 and another_session.request('route=photo')[2] == replacement, 'Foto persiste em outra sessao')
    check(member.request('route=update-photo', {'csrf': 'invalido', 'action': 'remove'})[0] == 403, 'Remocao de foto valida CSRF')
    check(member.request('route=update-photo', {'csrf': token, 'action': 'remove', 'id': 1})[0] == 303, 'Pessoa pode remover apenas sua foto')
    check(member.request('route=photo')[0] == 404 and admin.request('route=photo')[2] == admin_photo, 'Remocao volta as iniciais sem afetar outra pessoa')
    check(b'class="profile-photo"' not in member.request('route=home')[2], 'Iniciais restauradas na sidebar e no header')
    check(admin.request('route=update-photo', {'csrf': admin_token, 'action': 'remove'})[0] == 303, 'Administrador remove propria foto')
    check(not list(storage.glob('avatar-*.image')), 'Remocao nao deixa arquivos de foto')
    check({t: connection.execute('SELECT * FROM ' + t + ' ORDER BY id').fetchall() for t in tables_before} == tables_before, 'Fotos nao alteram contas nem materiais no banco')


def check_read_only_access(member, connection, storage, subject, token, own_id, check):
    def snapshot():
        tables = {table: connection.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall() for table in ['hc_portal_users', 'hc_portal_subjects', 'hc_portal_files']}
        binaries = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in storage.iterdir() if path.is_file()}
        return tables, binaries

    before = snapshot()
    for route in ['create-subject', 'edit-subject', 'update-subject', 'delete-subject', 'upload', 'edit-material', 'update-material', 'delete-material', 'users', 'create-user', 'update-user']:
        check(member.request('route=' + route + '&id=' + str(own_id))[0] == 403, 'Usuario normal: URL direta bloqueada para ' + route)
    check(member.request('route=create-subject', {'csrf': token, 'name': 'Materia indevida', 'role': 'admin'})[0] == 403, 'Usuario normal nao cria materia mesmo forjando perfil')
    check(member.multipart('route=upload', {'csrf': token, 'subject_id': subject, 'role': 'admin'}, [('negado.txt', 'text/plain', b'Upload proibido')], 'documents[]')[0] == 403, 'Usuario normal nao envia arquivos mesmo forjando perfil')
    revision = connection.execute('SELECT revision FROM hc_portal_files WHERE id = ?', (own_id,)).fetchone()[0]
    values = {'csrf': token, 'id': own_id, 'revision': revision, 'subject_id': subject, 'title': 'Alteracao proibida', 'role': 'admin'}
    check(member.request('route=update-material', values)[0] == 403, 'Usuario normal nao edita arquivo de sua autoria anterior')
    check(member.multipart('route=update-material', values, [('troca.txt', 'text/plain', b'Substituicao proibida')])[0] == 403, 'Usuario normal nao substitui arquivo de sua autoria anterior')
    check(member.request('route=delete-material', dict(values, confirm=1))[0] == 403, 'Usuario normal nao exclui arquivo de sua autoria anterior')
    check(member.request('route=update-user', {'csrf': token, 'id': 1, 'action': 'reset', 'password': 'Tentativa-Indevida-123!'})[0] == 403, 'Usuario normal nao altera contas')
    check(member.request('/trab/api.php')[0] == 200, 'Usuario normal pode consultar a API legada')
    check(member.request('/trab/api.php', {'csrf': token, 'acao': 'comentario'})[0] == 403, 'Usuario normal nao grava na API legada mesmo com CSRF valido')
    check(snapshot() == before, 'Tentativas bloqueadas preservam contas, materias, materiais e binarios')
    for route in ['route=home', 'route=subject&id=' + str(subject), 'route=subject&id=' + str(subject) + '&q=inexistente', 'route=view&id=' + str(own_id)]:
        status, _, body = member.request(route)
        check(status == 200, 'Usuario normal consulta ' + route)
        check(not any(marker in body for marker in [b'data-open="subject-dialog"', b'data-open="upload-dialog"', b'/editar', b'/materiais/atualizar', b'/materiais/excluir', b'id="subject-dialog"', b'id="upload-dialog"', b'id="delete-material-dialog"', b'/contas']), 'Pagina sem controles nem formularios de gestao: ' + route)
    check(member.request('route=file&id=' + str(own_id))[0] == 200, 'Usuario normal visualiza arquivo de sua autoria anterior')
    check(member.request('route=file&id=' + str(own_id) + '&download=1')[2] == b'Material enviado antes da restricao', 'Usuario normal baixa arquivo de sua autoria anterior')


def check_material_management(admin, member, connection, storage, subject, token, member_token, upload_id, legacy_id, check):
    def row(file_id):
        cursor = connection.execute('SELECT * FROM hc_portal_files WHERE id = ?', (file_id,))
        return dict(zip([column[0] for column in cursor.description], cursor.fetchone()))

    def values(client_token, file_id, **extra):
        return dict(csrf=client_token, id=file_id, revision=row(file_id)['revision'], **extra)

    own_id = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'aluno.txt'").fetchone()[0]
    check(member.request('route=edit-material&id=' + str(upload_id))[0] == 403, 'Estudante não edita material de outra pessoa')
    check(member.request('route=edit-material&id=' + str(legacy_id))[0] == 403, 'Originais são gerenciados pelo administrador')
    check(b'Editar material' not in member.request('route=view&id=' + str(upload_id))[2], 'Controles de edição exclusivos de administradores')
    other_values = values(member_token, upload_id, title='Indevido', subject_id=subject)
    check(member.request('route=update-material', other_values)[0] == 403, 'POST de edição verifica permissão')
    check(member.request('route=delete-material', values(member_token, upload_id, confirm=1))[0] == 403, 'POST de exclusão verifica permissão')
    check(admin.request('route=update-material&id=' + str(upload_id))[0] == 405, 'Edição não altera dados por GET')
    check(admin.request('route=delete-material&id=' + str(upload_id))[0] == 405, 'Exclusão não altera dados por GET')
    check(admin.request('route=update-material', values('invalido', upload_id, title='Teste', subject_id=subject))[0] == 403, 'Edição valida CSRF')
    check(admin.request('route=delete-material', values('invalido', upload_id, confirm=1))[0] == 403, 'Exclusão valida CSRF')
    check(admin.request('route=delete-material', values(token, upload_id))[0] == 400, 'Exclusão exige confirmação explícita')
    check(admin.request('route=edit-material&id=' + str(own_id))[0] == 200, 'Administrador pode abrir a edição de qualquer autor')
    new_subject = connection.execute('SELECT id FROM hc_portal_subjects WHERE id <> ? LIMIT 1', (subject,)).fetchone()[0]
    old = row(own_id)
    stale = values(token, own_id, title='Formulário antigo', subject_id=subject)
    check(admin.request('route=update-material', values(token, own_id, title='Resumo revisado', subject_id=new_subject))[0] == 303, 'Administrador altera título e matéria sem substituir arquivo')
    edited = row(own_id)
    check(edited['title'] == 'Resumo revisado' and edited['subject_id'] == new_subject and edited['stored_path'] == old['stored_path'], 'Edição mantém o arquivo e muda os campos solicitados')
    check(admin.request('route=update-material', stale)[0] == 409, 'Formulário antigo não sobrescreve edição mais recente')
    invalid = values(token, own_id, title='Não salvar', subject_id=new_subject)
    bins_before = sorted(path.name for path in storage.iterdir())
    check(admin.multipart('route=update-material', invalid, [('executavel.php', 'text/plain', b'<?php echo 1;')])[0] == 400, 'Substituição rejeita arquivo executável')
    check(admin.multipart('route=update-material', invalid, [('falso.pdf', 'application/pdf', b'nao e pdf')])[0] == 400, 'Substituição valida conteúdo do arquivo')
    check(admin.multipart('route=update-material', invalid, [('grande.txt', 'text/plain', b'A' * (25 * 1024 * 1024 + 1))])[0] == 400, 'Substituição respeita limite de tamanho')
    check(row(own_id) == edited and sorted(path.name for path in storage.iterdir()) == bins_before, 'Substituição inválida preserva metadados e armazenamento')
    check(admin.request('route=update-material', values(token, own_id, title='Inválido', subject_id=999999))[0] == 400, 'Edição valida matéria de destino')
    check(admin.request('route=update-material', values(token, own_id, title='', subject_id=new_subject))[0] == 400, 'Edição exige título')
    new_content = b'Versao nova do resumo do aluno.\n'
    check(admin.multipart('route=update-material', values(token, own_id, title='Versão nova', subject_id=subject), [('novo.txt', 'text/plain', new_content)])[0] == 303, 'Administrador substitui arquivo de outro autor')
    replacement = row(own_id)
    check(replacement['uploaded_by'] == old['uploaded_by'] and replacement['stored_path'] != old['stored_path'] and not (storage / old['stored_path']).exists(), 'Substituição preserva autoria e remove somente o binário anterior do upload')
    check(member.request('route=file&id=' + str(own_id) + '&download=1')[2] == new_content, 'Mesmo link entrega os bytes da nova versão')
    check(admin.request('route=delete-material', values(token, own_id, confirm=1))[0] == 303, 'Administrador exclui material de qualquer autor')
    check(row(own_id)['deleted_at'] is not None and not (storage / replacement['stored_path']).exists(), 'Material excluído fica indisponível e binário enviado é removido')
    check(admin.request('route=view&id=' + str(own_id))[0] == 404 and admin.request('route=file&id=' + str(own_id) + '&download=1')[0] == 404, 'Material excluído não pode ser visualizado nem baixado')
    own_subject = row(own_id)['subject_id']
    check(f'/materiais/{own_id}"'.encode() not in admin.request(f'route=subject&id={own_subject}&q=' + urllib.parse.quote('Versão nova'))[2], 'Busca não lista material excluído')
    # Lista, totais e contadores devem concordar após a exclusão.
    visible = connection.execute('SELECT COUNT(*) FROM hc_portal_files WHERE deleted_at IS NULL AND subject_id = ?', (own_subject,)).fetchone()[0]
    check(card_count(admin.request('route=home')[2], f'/materias/{own_subject}') == visible, 'Card da matéria conta somente materiais disponíveis')
    legacy = row(legacy_id)
    original = storage.parent / 'legacy' / legacy['stored_path']
    digest_before = hashlib.sha256(original.read_bytes()).hexdigest()
    html = b'<!doctype html><html><body>Nova versao HTML</body></html>'
    check(admin.multipart('route=update-material', values(token, legacy_id, title='Original atualizado', subject_id=subject), [('novo.html', 'text/html', html)])[0] == 303, 'Administrador substitui material original sem alterar o original físico')
    updated_legacy = row(legacy_id)
    status, headers, body = admin.request('/' + urllib.parse.quote(legacy['stored_path']))
    check(status == 200 and body == html and 'sandbox' in headers['Content-Security-Policy'] and 'allow-same-origin' not in headers['Content-Security-Policy'], 'Link antigo abre substituição HTML com isolamento de upload')
    check(hashlib.sha256(original.read_bytes()).hexdigest() == digest_before and updated_legacy['trusted_app'] == 0, 'Original físico preservado e nova versão não herda confiança')
    check(admin.request('route=delete-material', values(token, legacy_id, confirm=1))[0] == 303 and admin.request('/' + urllib.parse.quote(legacy['stored_path']))[0] == 404, 'Excluir original substituído bloqueia também seu link antigo')
    untouched = connection.execute("SELECT id FROM hc_portal_files WHERE legacy_path = 'trab/index.php'").fetchone()[0]
    trab = storage.parent / 'legacy/trab/index.php'
    trab_hash = hashlib.sha256(trab.read_bytes()).hexdigest()
    check(admin.request('route=delete-material', values(token, untouched, confirm=1))[0] == 303, 'Administrador exclui material legado do catálogo')
    check(admin.request('/trab/')[0] == 404 and admin.request('/trab/api.php')[0] == 404, 'Exclusão bloqueia pasta antiga e API vinculada')
    check(hashlib.sha256(trab.read_bytes()).hexdigest() == trab_hash, 'Excluir do portal preserva arquivo legado original')


def check_subject_management(admin, member, connection, storage, token, member_token, check):
    def subject_row(id):
        cursor = connection.execute('SELECT * FROM hc_portal_subjects WHERE id = ?', (id,))
        values = cursor.fetchone()
        return dict(zip([c[0] for c in cursor.description], values)) if values else None

    def file_row(id):
        cursor = connection.execute('SELECT * FROM hc_portal_files WHERE id = ?', (id,))
        return dict(zip([c[0] for c in cursor.description], cursor.fetchone()))

    def values(**extra):
        return dict(csrf=token, id=subject, revision=subject_row(subject)['revision'], **extra)

    def binaries():
        return {str(p.relative_to(storage.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for root in [storage, storage.parent / 'legacy'] for p in root.rglob('*') if p.is_file()}

    def snapshot():
        return [connection.execute('SELECT * FROM ' + table + ' ORDER BY id').fetchall() for table in ['hc_portal_subjects', 'hc_portal_files']], binaries()

    check(admin.request('route=create-subject', {'csrf': token, 'name': 'Materia de teste de exclusao', 'color': 'teal'})[0] == 303, 'Cria materia para testar edicao e exclusao')
    subject = connection.execute("SELECT id FROM hc_portal_subjects WHERE name = 'Materia de teste de exclusao'").fetchone()[0]
    check(admin.upload(token, subject, [('preservar.txt', 'text/plain', b'Conteudo preservado ao excluir a materia'), ('antes-excluido.txt', 'text/plain', b'Material ja excluido')])[0] == 303, 'Prepara uploads na materia que sera excluida')
    upload_id = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'preservar.txt'").fetchone()[0]
    deleted_id = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'antes-excluido.txt'").fetchone()[0]
    connection.execute('UPDATE hc_portal_files SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?', (deleted_id,))
    legacy_content = b'<!doctype html><html><body><h1>Original preservado</h1></body></html>'
    legacy_path = storage.parent / 'legacy/subject-original.html'
    legacy_path.write_bytes(legacy_content)
    legacy_id = connection.execute("INSERT INTO hc_portal_files (subject_id,title,original_name,stored_path,legacy_path,source,extension,mime,size,sha256,trusted_app) VALUES (?,?,?,?,?,'legacy','html','text/html',?,?,1)", (subject, 'Original da materia excluida', 'subject-original.html', 'subject-original.html', 'subject-original.html', len(legacy_content), hashlib.sha256(legacy_content).hexdigest())).lastrowid
    connection.commit()
    before = snapshot()
    guest = Client(admin.base)
    for route in ['edit-subject', 'update-subject', 'delete-subject']:
        check(guest.request('route=' + route + '&id=' + str(subject))[0] == 303, 'Materia exige autenticacao: ' + route)
        check(member.request('route=' + route + '&id=' + str(subject))[0] == 403, 'Usuario normal nao gerencia materia: ' + route)
    check(member.request('route=update-subject', dict(values(name='Indevida', description='', color='blue'), csrf=member_token, role='admin'))[0] == 403, 'Edicao de materia recusa perfil forjado')
    check(member.request('route=delete-subject', dict(values(confirm=1), csrf=member_token, role='admin'))[0] == 403, 'Exclusao de materia recusa perfil forjado')
    for route in ['update-subject', 'delete-subject']:
        check(admin.request('route=' + route + '&id=' + str(subject))[0] == 405, 'Materia nao muda por GET: ' + route)
        check(admin.request('route=' + route, dict(values(name='Teste', color='blue', confirm=1), csrf='invalido'))[0] == 403, 'Materia valida CSRF: ' + route)
    check(admin.request('route=delete-subject', values())[0] == 400, 'Exclusao de materia exige confirmacao')
    check(admin.request('route=edit-subject', values())[0] == 405, 'Formulario de edicao de materia aceita somente GET')
    check(admin.request('route=edit-subject&id=999999')[0] == 404, 'Edicao de materia inexistente retorna 404')
    check(admin.request('route=delete-subject', dict(values(confirm=1), id=999999))[0] == 404, 'Exclusao de materia inexistente retorna 404')
    for changes in [dict(name=''), dict(name='N' * 121), dict(description='D' * 256), dict(color='invalida'), dict(color=['blue'])]:
        data = dict(values(), name='Nome valido', description='Descricao', color='blue')
        data.update(changes)
        check(admin.request('route=update-subject', data)[0] == 400, 'Campos de materia invalidos recusados: ' + str(list(changes)))
    check(snapshot() == before, 'Operacoes negadas preservam materia, materiais e binarios')
    stale = values(confirm=1)
    escaped_name = 'Materia revisada <img src=x onerror=alert(1)>'
    check(admin.request('route=update-subject', values(name=escaped_name, description='<script>descricao</script>', color='rose'))[0] == 303, 'Administrador edita nome, descricao e cor')
    edited = subject_row(subject)
    check(edited['name'] == escaped_name and edited['color'] == 'rose' and edited['revision'] == int(stale['revision']) + 1, 'Edicao de materia salva campos e incrementa revisao')
    check(snapshot()[0][1] == before[0][1] and binaries() == before[1], 'Editar materia preserva registros e arquivos dos materiais')
    page = admin.request('route=subject&id=' + str(subject))[2]
    check(b'&lt;img src=x onerror=alert(1)&gt;' in page and b'<img src=x onerror=alert(1)>' not in page and b'&lt;script&gt;descricao&lt;/script&gt;' in page, 'Nome e descricao de materia escapados na interface')
    check(f'/materias/{subject}/editar'.encode() in page and b'id="delete-subject-dialog"' in page, 'Administrador recebe controles de materia')
    member_page = member.request('route=subject&id=' + str(subject))[2]
    check(f'/materias/{subject}/editar'.encode() not in member_page and b'/materias/excluir' not in member_page, 'Usuario normal nao recebe controles de materia')
    duplicate = connection.execute('SELECT name FROM hc_portal_subjects WHERE id <> ? LIMIT 1', (subject,)).fetchone()[0]
    check(admin.request('route=update-subject', values(name=duplicate, description='', color='teal'))[0] == 303 and subject_row(subject) == edited, 'Nome duplicado tratado sem alterar a materia')
    check(admin.request('route=update-subject', dict(stale, name='Antigo', description='', color='teal'))[0] == 409, 'Edicao antiga da materia recusada')
    check(admin.request('route=delete-subject', stale)[0] == 409 and subject_row(subject) == edited, 'Exclusao antiga nao remove materia alterada')
    stale_material = dict(csrf=token, id=upload_id, revision=file_row(upload_id)['revision'], title='Tentativa antiga', subject_id='')
    before_delete = snapshot()
    old_files = {id: file_row(id) for id in [upload_id, deleted_id, legacy_id]}
    connection.execute("CREATE TRIGGER fail_subject_delete BEFORE DELETE ON hc_portal_subjects WHEN OLD.id = " + str(subject) + " BEGIN SELECT RAISE(ABORT, 'subject deletion test'); END")
    connection.commit()
    check(admin.request('route=delete-subject', values(confirm=1))[0] == 500, 'Falha simulada na exclusao nao conclui parcialmente')
    check(snapshot() == before_delete, 'Transacao desfaz desvinculacao se exclusao falhar')
    connection.execute('DROP TRIGGER fail_subject_delete')
    connection.commit()
    check(admin.request('route=delete-subject', values(confirm=1))[0] == 303 and subject_row(subject) is None, 'Administrador exclui materia')
    check(binaries() == before_delete[1], 'Exclusao de materia preserva todos os binarios, inclusive originais')
    for id, old in old_files.items():
        current = file_row(id)
        check(current['subject_id'] is None and current['revision'] == old['revision'] + 1 and {k: v for k, v in current.items() if k not in ['subject_id', 'revision']} == {k: v for k, v in old.items() if k not in ['subject_id', 'revision']}, 'Desvinculacao preserva todos os demais metadados: ' + str(id))
    check(member.request('route=view&id=' + str(deleted_id))[0] == 404, 'Excluir materia nao restaura material anteriormente excluido')
    check(admin.request('route=subject&id=' + str(subject))[0] == 404 and admin.request('route=edit-subject&id=' + str(subject))[0] == 404, 'Materia excluida deixa de ser acessivel')
    check(admin.request('route=update-material', stale_material)[0] == 409, 'Exclusao de materia invalida formulario antigo de material')
    visible = connection.execute('SELECT COUNT(*) FROM hc_portal_files WHERE deleted_at IS NULL AND subject_id IS NULL').fetchone()[0]
    check(card_count(member.request('route=home')[2], '/materiais/sem-materia') == visible, 'Card Sem materia conta os materiais preservados')
    for client in [admin, member]:
        status, headers, body = client.request('route=unassigned')
        check(status == 200 and f'/materiais/{upload_id}"'.encode() in body and f'/materiais/{legacy_id}"'.encode() in body, 'Sem materia lista uploads e originais para todas as contas')
        check(client.request('route=view&id=' + str(upload_id))[0] == 200 and client.request('route=file&id=' + str(upload_id) + '&download=1')[2] == b'Conteudo preservado ao excluir a materia', 'Upload preservado continua acessivel pelos mesmos links')
        check(client.request('route=file&id=' + str(legacy_id) + '&download=1')[2] == legacy_content and client.request('/subject-original.html')[0] == 200, 'Original preservado conserva download e link antigo')
    check(b'/materiais/sem-materia' in member.request('route=view&id=' + str(upload_id))[2], 'Voltar ao material sem materia leva a lista correta')
    check(f'/materiais/{upload_id}"'.encode() in member.request('route=unassigned&q=preservar')[2], 'Busca em Sem materia encontra material preservado')
    check(not re.search(rb'href="/materias/[0-9]+/editar"', admin.request('route=unassigned')[2]), 'Sem materia nao pode ser editada nem excluida como materia real')
    destination = connection.execute('SELECT id FROM hc_portal_subjects ORDER BY id LIMIT 1').fetchone()[0]
    data = dict(csrf=token, id=upload_id, revision=file_row(upload_id)['revision'], title=old_files[upload_id]['title'], subject_id=destination)
    check(member.request('route=update-material', dict(data, csrf=member_token))[0] == 403, 'Somente administrador pode realocar material')
    check(admin.request('route=update-material', data)[0] == 303 and file_row(upload_id)['subject_id'] == destination, 'Administrador realoca material preservado')
    check(f'/materiais/{upload_id}"'.encode() in admin.request('route=subject&id=' + str(destination))[2] and f'/materiais/{upload_id}"'.encode() not in admin.request('route=unassigned')[2], 'Realocacao atualiza listas e contadores')
    data.update(subject_id='', revision=file_row(upload_id)['revision'])
    check(admin.request('route=update-material', data)[0] == 303 and file_row(upload_id)['subject_id'] is None, 'Administrador pode manter material sem materia')
    check(admin.request('route=create-subject', {'csrf': token, 'name': escaped_name, 'color': 'blue'})[0] == 303, 'Nome de materia excluida pode ser reutilizado')
    recreated = connection.execute('SELECT id FROM hc_portal_subjects WHERE name = ?', (escaped_name,)).fetchone()[0]
    check(file_row(upload_id)['subject_id'] is None, 'Recriar materia nao realoca material automaticamente')
    check(admin.request('route=delete-subject', {'csrf': token, 'id': recreated, 'revision': subject_row(recreated)['revision'], 'confirm': 1})[0] == 303, 'Exclusao de materia vazia tambem funciona')
    status, headers, body = admin.request('route=delete-material', {'csrf': token, 'id': upload_id, 'revision': file_row(upload_id)['revision'], 'confirm': 1})
    check(status == 303 and '/materiais/sem-materia' in headers['Location'], 'Excluir material sem materia retorna a lista correta')


def capture_previews(base, browser, output):
    from playwright.sync_api import expect, sync_playwright
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser_instance = playwright.chromium.launch(executable_path=browser, headless=True)
        page = browser_instance.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1, reduced_motion='reduce')
        # Exercise toggle persistence from an explicit light preference.
        page.add_init_script('if (!localStorage.getItem("humcode.theme.v2")) localStorage.setItem("humcode.theme.v2", "light");')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/index.php?route=login')
        page.screenshot(path=str(output / 'login-desktop.png'), full_page=True)
        page.get_by_label('Usuário', exact=True).fill('admin')
        page.get_by_label('Senha', exact=True).fill(ADMIN_PASSWORD)
        page.get_by_role('button', name='Entrar no portal').click()
        page.wait_for_url('**/biblioteca')
        menu = page.locator('[data-sidebar-toggle]')
        sidebar = page.locator('#sidebar')
        # A biblioteca mostra cards; os materiais ficam na página de cada matéria.
        subject_page = base + page.locator('.subject-card a').first.get_attribute('href')

        def open_first_material(target):
            target.goto(subject_page)
            target.goto(base + target.locator('.material-title').first.get_attribute('href'))

        def check_menu(expanded):
            expect(menu).to_be_visible()
            expect(menu).to_have_attribute('aria-expanded', str(expanded).lower())
            assert sidebar.evaluate('(node) => node.inert') is not expanded
            if expanded:
                expect(sidebar).to_be_visible()
            else:
                expect(sidebar).not_to_be_visible()

        check_menu(True)
        menu.click()
        check_menu(False)
        assert page.locator('.workspace').bounding_box()['x'] == 68
        page.set_viewport_size({'width': 1920, 'height': 1080})
        check_menu(False)
        page.screenshot(path=str(output / 'sidebar-recolhida.png'), full_page=True)
        open_first_material(page)
        check_menu(False)
        menu.click()
        check_menu(True)
        page.frame_locator('.document-viewer iframe').locator('h1').click()
        check_menu(False)
        page.reload()
        check_menu(False)
        menu.focus()
        page.keyboard.press('Enter')
        check_menu(True)
        page.reload()
        check_menu(True)
        assert page.locator('.workspace').bounding_box()['x'] == sidebar.bounding_box()['width']
        page.goto(base + '/index.php?route=home')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.screenshot(path=str(output / 'portal-desktop.png'), full_page=True)
        sidebar.locator('.sidebar-caption').first.click()
        check_menu(True)
        page.locator('.page-heading h1').click()
        check_menu(False)
        page.reload()
        check_menu(False)
        menu.click()
        check_menu(True)
        theme = page.locator('[data-theme-toggle]')
        user_toggle = page.locator('[data-user-toggle]')
        user_menu = page.locator('[data-user-menu]')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        expect(theme.locator('.theme-moon')).to_be_visible()
        theme.click()
        check_menu(False)
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        expect(theme).to_have_attribute('aria-pressed', 'true')
        expect(theme.locator('.theme-sun')).to_be_visible()
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        open_first_material(page)
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.goto(base + '/index.php?route=home')
        user_toggle.click()
        expect(user_menu).to_be_visible()
        expect(user_toggle).to_have_attribute('aria-expanded', 'true')
        expect(user_menu.locator('strong')).to_have_text('Admin Teste')
        expect(user_menu.locator('.user-menu-email')).to_have_text('E-mail não informado')
        assert user_menu.bounding_box()['y'] >= user_toggle.bounding_box()['y'] + user_toggle.bounding_box()['height']
        user_menu.locator('strong').click()
        expect(user_menu).to_be_visible()
        page.screenshot(path=str(output / 'portal-tema-escuro.png'), full_page=True)
        page.keyboard.press('Escape')
        expect(user_menu).not_to_be_visible()
        expect(user_toggle).to_be_focused()
        user_toggle.click()
        page.locator('.page-heading h1').click()
        expect(user_menu).not_to_be_visible()
        theme.click()
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
        assert page.locator('#upload-dialog').is_visible()
        page.screenshot(path=str(output / 'upload-desktop.png'))
        page.locator('#upload-dialog').get_by_role('button', name='Fechar', exact=True).click()
        open_first_material(page)
        page.get_by_role('link', name='Editar material', exact=True).click()
        assert page.get_by_label('Título', exact=True).input_value()
        assert page.locator('input[name="replacement"]').count() == 1
        page.screenshot(path=str(output / 'editar-material.png'), full_page=True)
        page.get_by_role('link', name='Voltar ao material', exact=True).click()
        page.wait_for_load_state()
        page.get_by_role('button', name='Excluir material', exact=True).click()
        assert page.locator('#delete-material-dialog').is_visible()
        page.screenshot(path=str(output / 'excluir-material.png'))
        page.locator('#delete-material-dialog').get_by_role('button', name='Cancelar', exact=True).click()
        page.goto(base + '/index.php?route=home')
        check_menu(False)
        page.set_viewport_size({'width': 390, 'height': 844})
        check_menu(False)
        page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().right <= 0')
        page.screenshot(path=str(output / 'portal-celular.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Página excede a largura do celular'
        expect(user_toggle).to_be_visible()
        expect(theme).to_be_visible()
        page.set_viewport_size({'width': 320, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Header excede a largura de 320px'
        page.set_viewport_size({'width': 390, 'height': 844})
        user_toggle.click()
        expect(user_menu).to_be_visible()
        page.screenshot(path=str(output / 'menu-usuario-celular.png'))
        assert user_menu.bounding_box()['x'] >= 0
        page.keyboard.press('Escape')
        page.get_by_role('button', name='Abrir menu').click()
        check_menu(True)
        assert page.locator('body').evaluate("node => node.classList.contains('sidebar-open')")
        sidebar.locator('.sidebar-caption').first.click()
        check_menu(True)
        page.keyboard.press('Escape')
        check_menu(False)
        expect(menu).to_be_focused()
        menu.click()
        page.get_by_role('button', name='Fechar menu').click()
        check_menu(False)
        menu.click()
        page.set_viewport_size({'width': 761, 'height': 844})
        check_menu(False)
        assert not page.locator('.sidebar-shade').is_visible()
        assert page.locator('body').evaluate('(node) => getComputedStyle(node).overflow') != 'hidden'
        menu.click()
        check_menu(True)
        page.set_viewport_size({'width': 760, 'height': 844})
        check_menu(False)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        check_menu(True)
        blocked_context = browser_instance.new_context(storage_state=page.context.storage_state(), viewport={'width': 1440, 'height': 1000})
        storage_blocked = blocked_context.new_page()
        storage_blocked.on('pageerror', lambda error: errors.append(str(error)))
        storage_blocked.add_init_script('Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new Error("Storage blocked"); };')
        storage_blocked.goto(base + '/index.php?route=home')
        blocked_menu = storage_blocked.locator('[data-sidebar-toggle]')
        expect(blocked_menu).to_have_attribute('aria-expanded', 'true')
        blocked_menu.click()
        expect(blocked_menu).to_have_attribute('aria-expanded', 'false')
        storage_blocked.locator('[data-theme-toggle]').click()
        expect(storage_blocked.locator('html')).to_have_attribute('data-theme', 'light')
        blocked_context.close()
        member_context = browser_instance.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        member_page = member_context.new_page()
        member_page.on('pageerror', lambda error: errors.append(str(error)))
        member_page.goto(base + '/index.php?route=login')
        member_page.get_by_label('Usuário', exact=True).fill('aluno')
        member_page.get_by_label('Senha', exact=True).fill(MEMBER_PASSWORD)
        member_page.get_by_role('button', name='Entrar no portal').click()
        member_page.wait_for_url('**/biblioteca')

        def check_read_only_controls():
            assert member_page.locator('[data-open="subject-dialog"], [data-open="upload-dialog"], .subject-card-new, .subject-toolbar, .material-toolbar, #subject-dialog, #upload-dialog, #delete-material-dialog, #delete-subject-dialog').count() == 0
            assert member_page.locator('a[href$="/editar"], a[href="/contas"]').count() == 0
            for action in member_page.locator('.row-actions a').all():
                assert action.get_attribute('title') in ['Visualizar', 'Baixar']

        check_read_only_controls()
        member_page.screenshot(path=str(output / 'usuario-normal-desktop.png'), full_page=True)
        open_first_material(member_page)
        check_read_only_controls()
        expect(member_page.get_by_role('link', name='Baixar arquivo', exact=True)).to_be_visible()
        member_page.locator('.back-link').click()
        check_read_only_controls()
        member_page.goto(subject_page + '?q=sem-resultados-para-teste')
        check_read_only_controls()
        member_page.goto(base + '/index.php?route=home')
        member_page.set_viewport_size({'width': 390, 'height': 844})
        member_page.locator('[data-sidebar-toggle]').click()
        expect(member_page.locator('#sidebar')).to_be_visible()
        check_read_only_controls()
        member_page.screenshot(path=str(output / 'usuario-normal-celular.png'))
        member_page.keyboard.press('Escape')
        member_page.goto(base + '/index.php?route=password')
        expect(member_page.locator('.photo-picker')).to_be_visible()
        with member_page.expect_navigation():
            member_page.get_by_label('Selecionar foto', exact=True).set_input_files({'name': 'foto.png', 'mimeType': 'image/png', 'buffer': photo_png()})
        expect(member_page.get_by_text('Sua foto foi atualizada.', exact=True)).to_be_visible()
        assert member_page.locator('.profile-photo').count() == 3
        for image in member_page.locator('.profile-photo').all():
            expect(image).to_have_js_property('complete', True)
            assert image.evaluate('(node) => node.naturalWidth') == 2
        member_page.screenshot(path=str(output / 'minha-conta-foto-celular.png'), full_page=True)
        member_page.goto(base + '/index.php?route=home')
        expect(member_page.locator('.topbar-avatar .profile-photo')).to_be_visible()
        member_page.locator('[data-sidebar-toggle]').click()
        expect(member_page.locator('.sidebar-profile .profile-photo')).to_be_visible()
        member_page.screenshot(path=str(output / 'foto-perfil-celular.png'))
        member_page.set_viewport_size({'width': 1440, 'height': 1000})
        member_page.reload()
        if member_page.locator('[data-sidebar-toggle]').get_attribute('aria-expanded') == 'false':
            member_page.locator('[data-sidebar-toggle]').click()
        expect(member_page.locator('[data-sidebar-toggle]')).to_have_attribute('aria-expanded', 'true')
        expect(member_page.locator('.sidebar-profile .profile-photo')).to_be_in_viewport()
        expect(member_page.locator('.topbar-avatar .profile-photo')).to_be_in_viewport()
        member_page.screenshot(path=str(output / 'foto-perfil-desktop.png'), full_page=True)
        member_page.locator('[data-user-toggle]').click()
        member_page.locator('[data-user-menu]').get_by_role('link', name='Minha conta', exact=True).click()
        for extension, mime in [('jpg', 'image/jpeg'), ('webp', 'image/webp')]:
            encoded = member_page.evaluate('''mime => { const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32; const ctx = canvas.getContext('2d'); ctx.fillStyle = '#42998a'; ctx.fillRect(0, 0, 32, 32); return canvas.toDataURL(mime).split(',')[1]; }''', mime)
            with member_page.expect_navigation():
                member_page.get_by_label('Selecionar foto', exact=True).set_input_files({'name': 'foto.' + extension, 'mimeType': mime, 'buffer': base64.b64decode(encoded)})
            expect(member_page.get_by_text('Sua foto foi atualizada.', exact=True)).to_be_visible()
            expect(member_page.locator('.topbar-avatar .profile-photo')).to_have_js_property('complete', True)
            assert member_page.locator('.topbar-avatar .profile-photo').evaluate('(node) => node.naturalWidth') == 32
        member_page.get_by_role('button', name='Remover foto', exact=True).click()
        expect(member_page.get_by_text('Essa ação não pode ser desfeita', exact=True)).to_be_visible()
        member_page.get_by_role('button', name='Sim', exact=True).click()
        expect(member_page.get_by_text('Sua foto foi removida.', exact=True)).to_be_visible()
        assert member_page.locator('.profile-photo').count() == 0
        expect(member_page.locator('.topbar-avatar')).to_contain_text('AT')
        member_page.locator('[data-user-toggle]').click()
        member_page.locator('[data-user-menu]').get_by_role('button', name='Sair da conta', exact=True).click()
        member_page.wait_for_url('**/entrar')
        member_context.close()
        page.goto(base + '/index.php?route=home')
        page.get_by_role('button', name='Nova matéria', exact=True).click()
        subject_dialog = page.locator('#subject-dialog')
        subject_dialog.get_by_label('Nome da matéria', exact=True).fill('Materia temporaria do teste visual')
        subject_dialog.get_by_label('Descrição', exact=False).fill('Descricao da materia de teste')
        subject_dialog.get_by_role('button', name='Criar matéria', exact=True).click()
        page.wait_for_url('**/materias/*')
        page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
        page.locator('#upload-dialog input[type="file"]').set_input_files({'name': 'material-da-materia.txt', 'mimeType': 'text/plain', 'buffer': b'Conteudo da materia preservado'})
        page.locator('#upload-dialog').get_by_role('button', name='Enviar materiais', exact=True).click()
        expect(page.locator('.material-title')).to_have_text('material-da-materia')
        page.get_by_role('link', name='Editar matéria', exact=True).click()
        page.locator('main').get_by_label('Nome da matéria', exact=True).fill('Materia revisada do teste visual')
        page.locator('main textarea[name="description"]').fill('Materiais preservados depois da exclusao')
        page.locator('main label.color-rose').click()
        expect(page.locator('main').get_by_label('Verde névoa', exact=True)).to_be_checked()
        page.screenshot(path=str(output / 'editar-materia-desktop.png'), full_page=True)
        page.get_by_role('button', name='Salvar alterações', exact=True).click()
        expect(page.locator('.page-heading h1')).to_have_text('Materia revisada do teste visual')
        expect(page.locator('.material-title')).to_have_text('material-da-materia')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='Excluir matéria', exact=True).click()
        delete_subject = page.locator('#delete-subject-dialog')
        expect(delete_subject).to_contain_text('Seus materiais serão preservados')
        page.screenshot(path=str(output / 'excluir-materia-celular.png'))
        delete_subject.get_by_role('button', name='Cancelar', exact=True).click()
        expect(page.locator('.page-heading h1')).to_have_text('Materia revisada do teste visual')
        page.get_by_role('button', name='Excluir matéria', exact=True).click()
        delete_subject.get_by_role('checkbox').check()
        delete_subject.get_by_role('button', name='Excluir matéria', exact=True).click()
        page.wait_for_url('**/materiais/sem-materia')
        expect(page.locator('.page-heading h1')).to_have_text('Sem matéria')
        expect(page.locator('.material-title')).to_have_text('material-da-materia')
        assert page.locator('.subject-toolbar, #delete-subject-dialog').count() == 0
        page.screenshot(path=str(output / 'sem-materia-celular.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.screenshot(path=str(output / 'sem-materia-desktop.png'), full_page=True)
        page.goto(base + page.locator('.material-title').get_attribute('href'))
        expect(page.frame_locator('.document-viewer iframe').locator('body')).to_contain_text('Conteudo da materia preservado')
        expect(page.locator('.back-link')).to_have_text('Sem matéria')
        page.get_by_role('link', name='Editar material', exact=True).click()
        expect(page.locator('main select[name="subject_id"]')).to_have_value('')
        page.locator('main select[name="subject_id"]').select_option(index=1, force=True)
        page.screenshot(path=str(output / 'realocar-material-desktop.png'), full_page=True)
        page.get_by_role('button', name='Salvar alterações', exact=True).click()
        expect(page.locator('.back-link')).not_to_have_text('Sem matéria')
        page.get_by_role('button', name='Excluir material', exact=True).click()
        page.locator('#delete-material-dialog').get_by_role('checkbox').check()
        page.locator('#delete-material-dialog').get_by_role('button', name='Excluir do portal', exact=True).click()
        page.wait_for_url('**/materias/*')
        page.goto(base + '/index.php?route=unassigned')
        assert page.locator('.material-title').count() == 0
        user_toggle.click()
        user_menu.get_by_role('button', name='Sair da conta', exact=True).click()
        page.wait_for_url('**/entrar')
        browser_instance.close()
        assert not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser')
    args = parser.parse_args()
    php = Path(args.php)
    with tempfile.TemporaryDirectory(prefix='humcode-portal-test-') as temporary:
        folder = Path(temporary)
        connection, config, storage, manifest = create_fixture(folder, php)
        sessions = folder / 'sessions'
        sessions.mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        command = [str(php), '-n', '-d', 'display_errors=0', '-d', 'extension_dir=' + str(php.parent / 'ext'), '-d', 'extension=pdo_sqlite', '-d', 'extension=fileinfo', '-d', 'session.save_path=' + str(sessions), '-d', 'upload_tmp_dir=' + str(folder), '-d', 'upload_max_filesize=26M', '-d', 'post_max_size=30M', '-S', '127.0.0.1:' + str(port), '-t', str(ROOT), str(ROOT / 'tools/dev-router.php')]
        environment = dict(os.environ, HUMCODE_CONFIG_FILE=str(config))
        base = 'http://127.0.0.1:' + str(port)
        with (folder / 'php.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for attempt in range(50):
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2): break
                    except OSError: time.sleep(.1)
                if args.browser:
                    capture_previews(base, args.browser, ROOT / 'artifacts')
                passed = run_checks(base, connection, storage, manifest)
                report = {'passed': len(passed), 'checks': passed, 'php': subprocess.check_output([str(php), '-n', '-r', 'echo PHP_VERSION;']).decode(), 'database': 'SQLite temporário; produção não alterada', 'original_documents': len(manifest['files']), 'subjects': len(manifest['subjects']), 'browser_checked': bool(args.browser)}
                artifacts = ROOT / 'artifacts'
                artifacts.mkdir(exist_ok=True)
                (artifacts / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print(json.dumps({key: value for key, value in report.items() if key != 'checks'}, ensure_ascii=True))
            except Exception:
                print((folder / 'php.log').read_text(encoding='utf-8', errors='replace')[-12000:])
                raise
            finally:
                process.terminate()
                process.wait(timeout=10)
                connection.close()


if __name__ == '__main__':
    main()
