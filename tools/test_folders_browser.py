"""Verifica Mini-GED no Chrome, com dados e servidor PHP temporários."""
import argparse
import json
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server

parser = argparse.ArgumentParser()
parser.add_argument('--php', required=True)
parser.add_argument('--browser', required=True)
args = parser.parse_args()
php = Path(args.php)
checks = []
errors = []
def check(condition, label):
    assert condition, label
    checks.append(label)

with test_server(php) as (base, db, config, storage, manifest, scratch, env):
    admin = portal.Client(base)
    admin.login()
    token = admin.csrf()
    response = admin.request('/materias/criar', {'csrf': token, 'name': 'Mini-GED · Banco de Dados', 'color': 'teal'})
    subject = int(response[1]['Location'].rsplit('/', 1)[1])
    subject_path = '/materias/' + str(subject)
    for name, parent in [('Aulas e exercícios', ''), ('Semana 01', ''), ('Revisões', '')]:
        admin.request('/pastas/criar', {'csrf': token, 'subject_id': subject, 'parent_id': parent, 'name': name})
    folders = dict(db.execute('SELECT name, id FROM hc_portal_folders WHERE subject_id = ?', (subject,)).fetchall())
    root = folders['Aulas e exercícios']
    admin.request('/pastas/criar', {'csrf': token, 'subject_id': subject, 'parent_id': root, 'name': 'Consultas SQL'})
    child = db.execute('SELECT MAX(id) FROM hc_portal_folders').fetchone()[0]
    admin.request('/pastas/criar', {'csrf': token, 'subject_id': subject, 'name': 'x' * 120})
    for name, folder, kind in [('Introdução a SQL', '', 'material'), ('Lista de exercícios', root, 'trabalho'), ('Avaliação · Consultas', child, 'prova')]:
        admin.multipart('/materiais/enviar', {'csrf': token, 'subject_id': subject, 'folder_id': folder, 'kind': kind, 'expected_files': 1}, [(name + '.txt', 'text/plain', b'Conteudo da aula')], 'documents[]')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser, headless=True)
        for width in [1440, 390, 320]:
            context = browser.new_context(viewport={'width': width, 'height': 950}, device_scale_factor=1)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/entrar')
            page.locator('[name=login]').fill('admin')
            page.locator('[name=password]').fill(portal.ADMIN_PASSWORD)
            page.locator('button[type=submit]').click()
            page.wait_for_url('**/biblioteca')
            page.goto(base + subject_path)
            page.evaluate('window.gedNavigationMarker = 42')
            page.locator('[data-folder-row="' + str(root) + '"] .folder-link').click()
            page.wait_for_url('**/pastas/' + str(root))
            check(page.evaluate('window.gedNavigationMarker') == 42, f'{width}: pasta abre sem recarga')
            page.locator('.category-tabs a').filter(has_text='Provas').click()
            page.wait_for_url('**categoria=provas')
            check(page.locator('[data-material-row]').count() == 1 and page.locator('.folder-column').count() == 2, f'{width}: filtro mostra prova da matéria e caminho')
            page.locator('.heading-actions [data-open=upload-dialog]').click()
            check(page.locator('#upload-dialog [name=subject_id]').input_value() == str(subject), f'{width}: upload usa matéria atual')
            check(page.locator('#upload-dialog [name=folder_id]').input_value() == str(root), f'{width}: upload usa pasta aberta')
            check(page.locator('#upload-dialog [name=kind]').input_value() == 'prova', f'{width}: upload usa categoria filtrada')
            page.locator('#upload-dialog [name=folder_id] + .select2 .select2-selection').click()
            page.locator('#upload-dialog .select2-search__field').fill('Consultas')
            check(page.locator('#upload-dialog .select2-results__option--selectable').count() == 1, f'{width}: busca Select2 dentro do diálogo')
            page.locator('#upload-dialog .select2-results__option--selectable').click()
            page.locator('#upload-dialog .modal-heading [data-close]').click()
            page.go_back()
            page.wait_for_function("() => !location.search.includes('categoria') && document.querySelector('[data-library-filter]').dataset.kind === 'material'")
            check(page.locator('[data-folder-row]').count() == 1 and page.evaluate('window.gedNavigationMarker') == 42, f'{width}: voltar restaura pasta sem recarga')
            page.locator('[data-open=folder-add-dialog]').click()
            page.locator('#folder-add-dialog [name=name]').fill('Pasta pelo navegador ' + str(width))
            page.locator('#folder-add-dialog [type=submit]').click()
            page.wait_for_url('**/pastas/' + str(root))
            check(page.locator('.folder-link').filter(has_text='Pasta pelo navegador ' + str(width)).count() == 1, f'{width}: diálogo cria pasta')
            # Operar a edição e exclusão reais pelos controles da interface.
            new_folder = db.execute('SELECT id FROM hc_portal_folders WHERE name = ?', ('Pasta pelo navegador ' + str(width),)).fetchone()[0]
            page.locator('[data-folder-row="' + str(new_folder) + '"] a[aria-label^="Renomear"]').click()
            page.locator('form[action$="/pastas/atualizar"] [name=name]').fill('Pasta renomeada ' + str(width))
            page.locator('form[action$="/pastas/atualizar"] [type=submit]').click()
            page.wait_for_url('**/pastas/' + str(new_folder))
            check(page.locator('.folder-heading h2').inner_text() == 'Pasta renomeada ' + str(width), f'{width}: edição renomeia pasta')
            page.locator('.folder-heading [aria-label="Excluir pasta"]').click()
            page.locator('#delete-folder-' + str(new_folder) + ' [name=confirm]').check()
            page.locator('#delete-folder-' + str(new_folder) + ' [type=submit]').click()
            page.wait_for_url('**/pastas/' + str(root))
            check(db.execute('SELECT COUNT(*) FROM hc_portal_folders WHERE id = ?', (new_folder,)).fetchone()[0] == 0, f'{width}: confirmação exclui pasta vazia')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: pasta sem rolagem horizontal')
            page.screenshot(path=str(portal.ROOT / f'artifacts/folders-pasta-{width}.png'), full_page=True)
            page.goto(base + subject_path)
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: raiz e nomes longos sem rolagem horizontal')
            page.screenshot(path=str(portal.ROOT / f'artifacts/folders-raiz-{width}.png'), full_page=True)
            page.locator('.category-tabs a').filter(has_text='Provas').click()
            page.wait_for_url('**categoria=provas')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: modo plano sem rolagem horizontal')
            page.screenshot(path=str(portal.ROOT / f'artifacts/folders-provas-{width}.png'), full_page=True)
            check(page.locator('.folder-breadcrumb a').first.evaluate('(node) => node.tabIndex') == 0, f'{width}: breadcrumb acessível por teclado')
            page.locator('.heading-actions [data-open=upload-dialog]').click()
            page.locator('#upload-dialog input[type=file]').set_input_files({'name': 'Prova enviada pelo navegador ' + str(width) + '.txt', 'mimeType': 'text/plain', 'buffer': b'Prova via XHR'})
            page.locator('#upload-dialog [type=submit]').click()
            page.wait_for_url('**/materias/' + str(subject))
            uploaded = db.execute('SELECT folder_id, kind FROM hc_portal_files WHERE original_name = ?', ('Prova enviada pelo navegador ' + str(width) + '.txt',)).fetchone()
            check(uploaded == (None, 'prova'), f'{width}: upload XHR grava categoria e raiz selecionadas')
            # Retirar o arquivo temporário pela aplicação para não mudar as contagens do próximo viewport.
            file_id, revision = db.execute('SELECT id, revision FROM hc_portal_files WHERE original_name = ?', ('Prova enviada pelo navegador ' + str(width) + '.txt',)).fetchone()
            admin.request('/materiais/excluir', {'csrf': token, 'id': file_id, 'revision': revision, 'confirm': 1})
            page.goto(base + '/pastas/' + str(root))
            page.locator('.heading-actions [data-open=upload-dialog]').click()
            page.locator('#upload-dialog [name=folder_id] + .select2 .select2-selection').click()
            page.locator('#upload-dialog .select2-results__option--selectable').filter(has_text='Consultas SQL').click()
            page.locator('#upload-dialog [name=subject_id] + .select2 .select2-selection').click()
            other_name = db.execute('SELECT name FROM hc_portal_subjects WHERE id != ? ORDER BY id LIMIT 1', (subject,)).fetchone()[0]
            page.locator('#upload-dialog .select2-search__field').fill(other_name)
            page.get_by_role('option', name=other_name, exact=True).click()
            check(page.locator('#upload-dialog [name=folder_id]').input_value() == '', f'{width}: mudar matéria limpa pasta antiga')
            check(page.locator('#upload-dialog [name=folder_id] option[data-subject="' + str(subject) + '"]').count() == 0, f'{width}: pastas de outra matéria saem das opções')
            page.locator('#upload-dialog .modal-heading [data-close]').click()
            page.locator('.folder-heading [aria-label="Excluir pasta"]').click()
            page.locator('#delete-folder-' + str(root) + ' [name=confirm]').check()
            page.locator('#delete-folder-' + str(root) + ' [type=submit]').click()
            page.wait_for_url('**/pastas/excluir')
            check('subpastas e arquivos ativos' in page.locator('.error-card p').inner_text(), f'{width}: interface explica recusa de pasta não vazia')
            context.close()
        context = browser.new_context()
        page = context.new_page()
        page.goto(base + '/entrar')
        page.locator('[name=login]').fill('aluno')
        page.locator('[name=password]').fill(portal.MEMBER_PASSWORD)
        page.locator('button[type=submit]').click()
        page.wait_for_url('**/biblioteca')
        page.goto(base + '/pastas/' + str(root))
        check(page.locator('[data-open=folder-add-dialog]').count() == 0 and page.locator('.folder-link').count() > 0, 'Estudante navega sem controles de gestão')
        context.close()
        browser.close()
check(not errors, 'Sem erros JavaScript: ' + str(errors))
report = {'status': 'passed', 'verified_at': datetime.now(timezone.utc).isoformat(), 'count': len(checks), 'checks': checks, 'page_errors': errors, 'browser': 'Chrome headless / Playwright Python, SQLite temporário'}
(portal.ROOT / 'artifacts/folders-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': 'passed', 'browser_checks': len(checks)}))
