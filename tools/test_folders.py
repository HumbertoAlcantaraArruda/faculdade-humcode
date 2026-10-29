"""Mini-GED: integração HTTP, permissões, árvore e preservação de dados em SQLite."""
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
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    php = Path(args.php)
    checks = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with test_server(php) as (base, db, config, storage, manifest, scratch, environment):
        db.execute('PRAGMA foreign_keys = ON')
        initial = db.execute('SELECT COUNT(*) FROM hc_portal_files').fetchone()[0]
        check(db.execute("SELECT COUNT(*) FROM hc_portal_files WHERE kind = 'material' AND folder_id IS NULL").fetchone()[0] == initial, 'Legados começam como Material na raiz')
        admin, member, guest = [portal.Client(base) for _ in range(3)]
        check(admin.login()[0] == 303, 'Administrador autentica')
        check(member.login('aluno', portal.MEMBER_PASSWORD)[0] == 303, 'Estudante autentica')
        token, member_token = admin.csrf(), member.csrf()
        subjects = []
        for name in ['GED principal', 'GED outra matéria']:
            response = admin.request('/materias/criar', {'csrf': token, 'name': name, 'color': 'teal'})
            check(response[0] == 303, 'Criar matéria: ' + name)
            subjects.append(int(response[1]['Location'].rsplit('/', 1)[1]))
        subject, other = subjects

        def add(name, parent='', subject_id=subject, expected=303):
            response = admin.request('/pastas/criar', {'csrf': token, 'subject_id': subject_id, 'parent_id': parent, 'name': name})
            check(response[0] == expected, 'Criar pasta: ' + name + ' HTTP ' + str(expected))
            if expected == 303:
                return db.execute('SELECT MAX(id) FROM hc_portal_folders').fetchone()[0]

        def change(folder, parent='', name='Renomeada', expected=303, revision=None):
            revision = revision if revision is not None else db.execute('SELECT revision FROM hc_portal_folders WHERE id = ?', (folder,)).fetchone()[0]
            response = admin.request('/pastas/atualizar', {'csrf': token, 'id': folder, 'revision': revision, 'name': name, 'parent_id': parent})
            check(response[0] == expected, 'Renomear/mover pasta HTTP ' + str(expected))

        def remove(folder, expected=303, confirm='1'):
            revision = db.execute('SELECT revision FROM hc_portal_folders WHERE id = ?', (folder,)).fetchone()[0]
            response = admin.request('/pastas/excluir', {'csrf': token, 'id': folder, 'revision': revision, 'confirm': confirm})
            check(response[0] == expected, 'Excluir pasta HTTP ' + str(expected))

        root = add('Unidade Árvore')
        child = add('Segundo nível', root)
        third = add('Terceiro nível', child)
        leaf = add('Quarto nível', third)
        foreign = add('Outra matéria', subject_id=other)
        add('unidade árvore', expected=400)
        add('Segundo nível', root, expected=400)
        sibling = add('Segundo nível')
        add('Pai estrangeiro', foreign, expected=400)
        add('Pai ausente', 999999, expected=400)
        add('Nome inválido', 'abc', expected=400)
        add('   ', expected=400)
        add('x' * 121, expected=400)
        page = member.request('/pastas/' + str(leaf))[2].decode()
        breadcrumb = re.search(r'<nav class="folder-breadcrumb".*?</nav>', page).group()
        check(all(name in breadcrumb for name in ['GED principal', 'Unidade Árvore', 'Segundo nível', 'Terceiro nível', 'Quarto nível']), 'Breadcrumb tem os quatro níveis')
        change(root, root, expected=400)
        change(root, leaf, expected=400)
        change(root, foreign, expected=400)
        change(sibling, root, name='Segundo nível', expected=400)
        change(sibling, third, name='Movida')
        check(db.execute('SELECT parent_id, name, revision FROM hc_portal_folders WHERE id = ?', (sibling,)).fetchone() == (third, 'Movida', 2), 'Mover e renomear persistem juntos')
        change(sibling, revision=1, expected=409)
        edit = admin.request('/pastas/' + str(root) + '/editar')[2]
        parent_select = re.search(rb'<select name="parent_id">(.*?)</select>', edit, re.S).group(1)
        check(not re.search(rb'<option value="(?:' + b'|'.join(str(i).encode() for i in [root, child, third, leaf, sibling]) + rb')"', parent_select), 'Destinos excluem a própria pasta e descendentes')
        remove(root, 400)
        remove(leaf, 400, confirm='')
        remove(leaf)
        check(member.request('/pastas/' + str(leaf))[0] == 404, 'Pasta excluída retorna 404')
        check(admin.request('/pastas/999999/editar')[0] == 404, 'Edição inexistente retorna 404')
        for route in ['/pastas/criar', '/pastas/atualizar', '/pastas/excluir']:
            check(admin.request(route)[0] == 405, 'GET recusado: ' + route)
            check(admin.request(route, {'csrf': 'invalid'})[0] == 403, 'CSRF recusado: ' + route)
            check(member.request(route, {'csrf': member_token, 'id': root})[0] == 403, 'Estudante recusado: ' + route)
            check(guest.request(route, {'id': root})[0] == 303, 'Visitante redirecionado: ' + route)
        check(member.request('/pastas/' + str(root) + '/editar')[0] == 403, 'Estudante não edita pasta')
        check(guest.request('/pastas/' + str(root))[0] == 303, 'Visitante precisa autenticar para navegar')
        response = guest.login('aluno', portal.MEMBER_PASSWORD)
        check(response[1]['Location'].endswith('/pastas/' + str(root)), 'Login retoma a pasta')
        check(admin.request('route=folder&id=' + str(root), follow_canonical=False)[0] == 308, 'URL antiga redireciona para pasta amigável')

        def upload(name, folder='', kind='material', subject_id=subject, expected=303, defaults=False):
            fields = {'csrf': token, 'subject_id': subject_id, 'expected_files': 1}
            if not defaults:
                fields.update(folder_id=folder, kind=kind)
            result = admin.multipart('/materiais/enviar', fields, [(name + '.txt', 'text/plain', b'Conteudo GED')], 'documents[]')
            check(result[0] == expected, 'Upload ' + name + ' HTTP ' + str(expected))
            if expected == 303:
                return db.execute('SELECT MAX(id) FROM hc_portal_files').fetchone()[0]

        default = upload('Arquivo padrao', defaults=True)
        proof = upload('Prova na subpasta', third, 'prova')
        work = upload('Trabalho raiz', kind='trabalho')
        material = upload('Material na pasta', root)
        upload('Pasta estrangeira', foreign, expected=400)
        upload('Categoria inválida', kind='video', expected=400)
        upload('Pasta inválida', 'abc', expected=400)
        check(db.execute('SELECT folder_id, kind FROM hc_portal_files WHERE id = ?', (default,)).fetchone() == (None, 'material'), 'Upload sem campos começa como Material na raiz')
        check(db.execute('SELECT folder_id, kind FROM hc_portal_files WHERE id = ?', (proof,)).fetchone() == (third, 'prova'), 'Upload grava pasta e categoria')
        remove(root, 400)
        check(member.request('/materiais/' + str(proof) + '/download')[2] == b'Conteudo GED', 'Estudante baixa arquivo da subpasta')
        check(member.request('/materiais/' + str(proof))[0] == 200, 'Estudante visualiza arquivo da subpasta')
        check(b'kind-badge' in member.request('/materiais/' + str(proof))[2], 'Prévia exibe categoria de Prova')

        def ids(path):
            return set(map(int, re.findall(rb'data-material-row="(\d+)"', member.request(path)[2])))

        subject_path = '/materias/' + str(subject)
        check(ids(subject_path) == {default, work}, 'Raiz lista apenas seus arquivos')
        check(ids('/pastas/' + str(root)) == {material}, 'Pasta lista apenas seus arquivos')
        check(ids(subject_path + '?categoria=provas') == {proof}, 'Categoria busca provas em todas as pastas')
        flat = member.request('/pastas/' + str(root) + '?categoria=provas')[2]
        check(b'folder-column' in flat and b'data-folder-row=' not in flat, 'Modo plano mostra coluna Pasta e omite subpastas')
        check('Unidade Árvore › Segundo nível › Terceiro nível'.encode() in flat, 'Coluna Pasta mostra caminho completo')
        counts_page = member.request(subject_path)[2].decode()
        counts = dict(re.findall(r'>(Todos|Materiais|Trabalhos|Provas)<span>(\d+)</span>', counts_page))
        check(counts == {'Todos': '4', 'Materiais': '2', 'Trabalhos': '1', 'Provas': '1'}, 'Abas contam toda a matéria')
        check(ids(subject_path + '?q=Terceiro') == {proof}, 'Busca por nome da pasta em toda a matéria')
        check(ids('/pastas/' + str(root) + '?q=Trabalho') == {work}, 'Busca na pasta alcança raiz da matéria')
        check(ids(subject_path + '?categoria=provas&type=text&sort=title&page=2') == {proof}, 'Categoria combina formato, ordem e página')
        check(member.request(subject_path + '?categoria=qualquer')[0] == 400, 'Categoria inválida recusada')
        check(member.request(subject_path + '?categoria[]=provas')[0] == 400, 'Categoria em array recusada')

        def edit_file(file_id, **values):
            current = db.execute('SELECT revision, subject_id, folder_id, kind FROM hc_portal_files WHERE id = ?', (file_id,)).fetchone()
            fields = {'csrf': token, 'id': file_id, 'revision': current[0], 'subject_id': current[1] or '', 'folder_id': current[2] or '', 'kind': current[3], 'title': 'Arquivo editado'}
            fields.update(values)
            return admin.request('/materiais/atualizar', fields)

        check(edit_file(material, folder_id=third, kind='trabalho')[0] == 303, 'Editar pasta e categoria')
        check(edit_file(material, folder_id=foreign)[0] == 400, 'Edição recusa pasta estrangeira')
        check(edit_file(material, kind='outro')[0] == 400, 'Edição recusa categoria inválida')
        check(edit_file(material, subject_id=other, folder_id='')[0] == 303, 'Trocar matéria com raiz')
        check(db.execute('SELECT subject_id, folder_id, kind FROM hc_portal_files WHERE id = ?', (material,)).fetchone() == (other, None, 'trabalho'), 'Troca de matéria zera pasta e preserva categoria')
        check(edit_file(material, folder_id=foreign)[0] == 303, 'Selecionar pasta na nova matéria')
        check(edit_file(material, subject_id='', folder_id=foreign)[0] == 400, 'Sem matéria recusa pasta')
        check(edit_file(material, subject_id='', folder_id='')[0] == 303, 'Sem matéria aceita raiz')
        check(member.request('/materiais/' + str(proof) + '/editar')[0] == 403, 'Estudante não edita categoria ou pasta')
        check(member.request('/materiais/enviar', {'csrf': member_token})[0] == 403, 'Estudante não envia arquivos')
        revision = db.execute('SELECT revision FROM hc_portal_files WHERE id = ?', (proof,)).fetchone()[0]
        check(admin.request('/materiais/excluir', {'csrf': token, 'id': proof, 'revision': revision, 'confirm': 1})[0] == 303, 'Excluir logicamente arquivo de pasta')
        counts_page = member.request(subject_path)[2].decode()
        check('Provas<span>0</span>' in counts_page, 'Contagem ignora arquivos excluídos')
        remove(sibling)
        remove(third)
        check(db.execute('SELECT folder_id FROM hc_portal_files WHERE id = ?', (proof,)).fetchone()[0] is None, 'Excluir pasta limpa referência de arquivo já excluído')
        escaped = add('<img src=x onerror=alert(1)>')
        page = member.request(subject_path)[2]
        check(b'&lt;img src=x onerror=alert(1)&gt;' in page and b'<img src=x onerror' not in page, 'Nomes de pasta escapados')
        check(b'folder-add-dialog' not in page and b'delete-folder-' not in page, 'Estudante vê navegação sem gestão')
        video = {'csrf': token, 'subject_id': subject, 'title': 'Aula GED', 'url': 'https://youtu.be/aqz-KE-bpKQ'}
        check(admin.request('/videos/criar', video)[0] == 303, 'Vídeo de teste criado')
        check(b'id="videos"' in member.request(subject_path)[2], 'Vídeo aparece na raiz')
        check(b'id="videos"' not in member.request('/pastas/' + str(root))[2], 'Vídeo não aparece dentro de pasta')
        check(b'id="videos"' not in admin.request(subject_path + '?categoria=materiais')[2], 'Vídeo não aparece no modo plano')
        upload('Prova preservada', root, 'prova')
        for i in range(14):
            upload('Paginado ' + str(i), root)
        check(len(ids('/pastas/' + str(root))) == 12 and len(ids('/pastas/' + str(root) + '?page=2')) == 3, 'Paginação de arquivos dentro da pasta')
        revision = db.execute('SELECT revision FROM hc_portal_subjects WHERE id = ?', (subject,)).fetchone()[0]
        check(admin.request('/materias/excluir', {'csrf': token, 'id': subject, 'revision': revision, 'confirm': 1})[0] == 303, 'Excluir matéria com pastas aninhadas')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_folders WHERE subject_id = ?', (subject,)).fetchone()[0] == 0, 'Pastas da matéria removidas')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_videos WHERE subject_id = ?', (subject,)).fetchone()[0] == 0, 'Vídeos da matéria removidos')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_files WHERE subject_id IS NULL AND folder_id IS NOT NULL').fetchone()[0] == 0, 'Sem matéria nunca mantém pasta')
        check(db.execute("SELECT COUNT(*) FROM hc_portal_files WHERE subject_id IS NULL AND kind = 'prova' AND deleted_at IS NULL").fetchone()[0] == 1, 'Exclusão da matéria preserva categoria')
        check(not db.execute('PRAGMA foreign_key_check').fetchall(), 'Sem violações de chaves estrangeiras')
        # Schema readiness é portátil; a migração MySQL é exercitada duas vezes pelo atualizador.
        script = scratch / 'schema-check.php'
        script.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; echo json_encode([portal_schema_ready(), portal_schema_ready()]);', encoding='utf-8')
        command = [str(php), '-n', '-d', 'extension_dir=' + str(php.parent / 'ext'), '-d', 'extension=pdo_sqlite', str(script)]
        check(json.loads(subprocess.check_output(command, env=environment)) == [True, True], 'Esquema novo pronto em duas verificações')
        db.execute('ALTER TABLE hc_portal_files RENAME COLUMN kind TO kind_missing')
        db.commit()
        check(json.loads(subprocess.check_output(command, env=environment)) == [False, False], 'Esquema antigo incompleto detectado')
    report = {'status': 'passed', 'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': checks, 'count': len(checks), 'sha256': {str(path.relative_to(portal.ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in [portal.ROOT / 'portal/src/folders.php', portal.ROOT / 'portal/schema.sql']}}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'checks': len(checks)}))


if __name__ == '__main__':
    main()
