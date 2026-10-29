"""Verifica a biblioteca e a leitura em Chrome com dados locais temporários."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.parse

from playwright.sync_api import sync_playwright, expect
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    checks = []
    output = portal.ROOT / 'artifacts'

    def check(condition, label):
        assert condition, label
        checks.append(label)

    def record(label):
        checks.append(label)

    def choose(page, label, option):
        page.get_by_role('combobox', name=label, exact=True).click()
        page.get_by_role('option', name=option, exact=True).click()

    with test_server(Path(args.php)) as (base, connection, _, storage, _, _, _):
        admin = portal.Client(base)
        check(admin.login()[0] == 303, 'Administrador autentica')
        # Os filtros ficam na página da matéria; ED II passa de 12 materiais com o HTML de teste.
        ed2 = connection.execute("SELECT id FROM hc_portal_subjects WHERE name = 'Estruturas de Dados II'").fetchone()[0]
        listing = f'route=subject&id={ed2}'
        for key in ['type', 'sort']:
            check(admin.request(listing + '&' + key + '=invalid')[0] == 400, 'Filtro inválido recusado: ' + key)
            check(admin.request(listing + '&' + key + '[]=pdf')[0] == 400, 'Filtro não escalar recusado: ' + key)
        for kind in ['pdf', 'html', 'office', 'image', 'text', 'archive']:
            check(admin.request(listing + '&type=' + kind)[0] == 200, 'Filtro de formato: ' + kind)
        subject = connection.execute('SELECT id FROM hc_portal_subjects WHERE id <> ? ORDER BY id LIMIT 1', [ed2]).fetchone()[0]
        check(admin.upload(admin.csrf(), ed2, [('frontend-sandbox.html', 'text/html', b'<!doctype html><html><body><h1>Conteudo interativo</h1></body></html>')])[0] == 303, 'HTML de teste enviado')
        html_id = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'frontend-sandbox.html'").fetchone()[0]
        expected = [str(row[0]) for row in connection.execute('SELECT id FROM hc_portal_files WHERE deleted_at IS NULL AND subject_id = ? AND folder_id IS NULL ORDER BY title, id LIMIT 12', [ed2])]
        body = admin.request(listing + '&sort=title')[2]
        check(re.findall(rb'data-material-row="(\d+)"', body) == [value.encode() for value in expected], 'Ordenação A–Z aplicada no servidor')
        check(b'sort=title' in body, 'Paginação conserva ordenação')
        pdf_count = connection.execute("SELECT COUNT(*) FROM hc_portal_files WHERE extension='pdf' AND deleted_at IS NULL AND subject_id = ? AND folder_id IS NULL", [ed2]).fetchone()[0]
        check(f'data-library-count="{pdf_count}"'.encode() in admin.request(listing + '&type=pdf')[2], 'Filtro PDF conta os resultados reais')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            errors = []
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/index.php?route=login')
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            record('Tema escuro é o padrão no login')
            page.screenshot(path=str(output / 'frontend-login.png'))
            page.get_by_label('Usuário', exact=True).fill('admin')
            page.get_by_label('Senha', exact=True).fill(portal.ADMIN_PASSWORD)
            page.get_by_role('button', name='Entrar no portal', exact=True).click()
            page.wait_for_url('**/biblioteca')
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            record('Biblioteca inicia no tema escuro')
            expect(page.locator('.library-heading h1')).to_have_text('Biblioteca')
            check(page.locator('[data-library-filter], .materials-table').count() == 0, 'Biblioteca mostra somente os cards das matérias')
            page.screenshot(path=str(output / 'frontend-desktop.png'))
            ed2_card = page.locator('.subject-card a', has_text='Estruturas de Dados II')
            check(ed2_card.bounding_box()['y'] < 600, 'Cards das matérias aparecem sem rolagem no desktop')
            page.evaluate('window.frontendNavigationMarker = 1')
            ed2_card.click()
            page.wait_for_url(f'**/materias/{ed2}')
            expect(page.locator('.library-heading h1')).to_have_text('Estruturas de Dados II')
            check(page.evaluate('window.frontendNavigationMarker') == 1, 'Card leva à matéria sem recarregar')
            page.get_by_role('link', name='Próxima', exact=False).click()
            expect(page.locator('.pagination')).to_contain_text('2 /')
            check(page.evaluate('window.frontendNavigationMarker') == 1, 'Paginação atualiza a lista sem recarregar')
            page.go_back()
            expect(page.locator('.pagination')).to_contain_text('1 /')
            record('Histórico do navegador restaura a página da lista')
            search = page.locator('[data-library-filter] input[name="q"]')
            search.fill('Ponteiros')
            expect(page.locator('.material-title')).to_have_text(['Ponteiros em C — Estruturas de Dados II'])
            check(search.evaluate('(node) => node === document.activeElement'), 'Busca mantém o foco ao atualizar')
            check(page.evaluate('window.frontendNavigationMarker') == 1, 'Busca atualiza sem recarregar')
            # Hold an older response after the fetch, then issue a newer query.
            page.evaluate('''() => {
              const original = window.fetch;
              window.frontendOriginalFetch = original;
              window.fetch = (...args) => original(...args).then(response => {
                if (new URL(args[0], location.href).searchParams.get('q')?.trim() !== 'Ponteiros') return response;
                window.frontendSlowResponse = true;
                return new Promise(resolve => setTimeout(() => { window.frontendSlowFinished = true; resolve(response); }, 650));
              });
            }''')
            search.fill('Ponteiros ')
            page.wait_for_function('() => window.frontendSlowResponse === true')
            search.fill('Aval')
            page.wait_for_function('() => window.frontendSlowFinished === true')
            aval_count = connection.execute("SELECT COUNT(*) FROM hc_portal_files WHERE deleted_at IS NULL AND subject_id = ? AND (title LIKE '%Aval%' OR original_name LIKE '%Aval%')", [ed2]).fetchone()[0]
            expect(page.locator('.library-summary')).to_have_attribute('data-library-count', str(aval_count))
            expect(search).to_have_value('Aval')
            record('Resposta antiga não substitui uma busca mais recente')
            page.evaluate('window.fetch = window.frontendOriginalFetch')
            rows_before_failure = page.locator('[data-material-row]').count()
            failure_pattern = f'**/materias/{ed2}?*q=connection-failure*'
            page.route(failure_pattern, lambda route: route.abort())
            search.fill('connection-failure')
            expect(page.locator('[data-library-status]')).to_be_visible()
            expect(page.locator('[data-library-status]')).to_contain_text('Não foi possível atualizar')
            check(page.locator('[data-material-row]').count() == rows_before_failure, 'Falha de conexão preserva os resultados anteriores')
            page.unroute(failure_pattern)
            search.fill('Nada-encontrado-frontend')
            expect(page.get_by_text('Nenhum material encontrado', exact=True)).to_be_visible()
            record('Busca sem resultados orienta a ajustar filtros')
            page.get_by_role('link', name='Limpar filtros', exact=False).click()
            expect(page.locator('.material-title')).to_have_count(12)
            choose(page, 'Filtrar por formato', 'PDF')
            expect(page.locator('.file-badge')).to_have_text(['PDF'] * pdf_count)
            record('Filtro de formato atualiza a lista no navegador')
            choose(page, 'Filtrar por formato', 'Todos os formatos')
            expect(page.locator('.material-title')).to_have_count(12)
            choose(page, 'Ordenar materiais', 'Título: A–Z')
            expect(page.locator('[data-material-row]').first).to_have_attribute('data-material-row', expected[0])
            record('Ordenação atualiza a lista no navegador')
            page.locator('[data-library-filter] input[name="q"]').fill('frontend-sandbox')
            expect(page.locator('.material-title')).to_have_count(1)
            page.locator('.open-material').click()
            expect(page.locator('[data-library-preview] iframe')).to_be_visible()
            iframe = page.locator('[data-library-preview] iframe')
            expect(page.frame_locator('[data-library-preview] iframe').get_by_text('Conteudo interativo', exact=True)).to_be_visible()
            check('allow-same-origin' not in iframe.get_attribute('sandbox'), 'Prévia mantém o isolamento do HTML enviado')
            check(f'/materias/{ed2}' in page.url, 'Prévia conserva a URL e os filtros da matéria')
            page.screenshot(path=str(output / 'frontend-previa.png'))
            page.get_by_role('button', name='Fechar prévia', exact=True).click()
            expect(page.locator('[data-library-preview]')).to_be_hidden()
            record('Fechar prévia conserva o material filtrado')
            page.get_by_role('link', name='Limpar filtros', exact=False).click()
            expect(page.locator('.material-title')).to_have_count(12)
            choose(page, 'Filtrar por matéria', connection.execute('SELECT name FROM hc_portal_subjects WHERE id=?', [subject]).fetchone()[0])
            expect(page.locator('[data-library-filter]')).to_have_attribute('data-route', 'subject')
            expect(page.locator('#upload-dialog select[name="subject_id"]')).to_have_value(str(subject))
            record('Filtro de matéria atualiza o destino do upload')
            page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
            upload = page.locator('#upload-dialog')
            upload.locator('input[type="file"]').set_input_files({'name': 'frontend-upload.txt', 'mimeType': 'text/plain', 'buffer': b'Arquivo do teste visual'})
            upload.get_by_role('button', name='Enviar materiais', exact=True).click()
            expect(page.locator('.material-title').first).to_have_text('frontend-upload')
            record('Upload com progresso conclui e mostra o novo material')
            page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
            upload.locator('input[type="file"]').set_input_files({'name': 'recusado.php', 'mimeType': 'application/x-php', 'buffer': b'<?php echo 1;'})
            upload.get_by_role('button', name='Enviar materiais', exact=True).click()
            expect(upload.locator('[data-upload-error]')).not_to_be_empty()
            expect(upload.get_by_role('button', name='Enviar materiais', exact=True)).to_be_enabled()
            record('Erro de upload mantém o diálogo e permite corrigir o arquivo')
            upload.get_by_role('button', name='Cancelar', exact=True).click()

            for width in [320, 390, 768, 1024, 1440]:
                page.set_viewport_size({'width': width, 'height': 844})
                check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Sem rolagem horizontal: ' + str(width))
            page.set_viewport_size({'width': 390, 'height': 844})
            check(page.locator('.material-title').first.evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)') >= 15, 'Título do material legível no celular')
            check(page.locator('.open-material').first.bounding_box()['height'] >= 44, 'Ações com área de toque de 44 px')
            page.screenshot(path=str(output / 'frontend-celular.png'), full_page=True)
            page.locator('.material-title').first.click()
            page.wait_for_url('**/materiais/*')
            expect(page.locator('.document-viewer iframe')).to_be_visible()
            page.get_by_role('button', name='Expandir leitura', exact=True).click()
            expect(page.locator('body')).to_have_class(re.compile('reading-expanded'))
            page.screenshot(path=str(output / 'frontend-leitura-celular.png'))
            page.keyboard.press('Escape')
            expect(page.locator('body')).not_to_have_class(re.compile('reading-expanded'))
            page.locator('[data-reading-back]').click()
            expect(page.locator('.library-heading')).to_be_visible()
            check('/materias/' in page.url, 'Voltar da leitura conserva a matéria')

            page.set_viewport_size({'width': 1440, 'height': 1000})
            if page.locator('html').get_attribute('data-theme') == 'dark':
                page.locator('[data-theme-toggle]').click()
                expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            page.locator('[data-theme-toggle]').click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            page.screenshot(path=str(output / 'frontend-escuro.png'))
            record('Tema escuro funciona na nova biblioteca')
            member_context = browser.new_context(viewport={'width': 390, 'height': 844})
            member = member_context.new_page()
            member.on('pageerror', lambda error: errors.append(str(error)))
            member.goto(base + '/index.php?route=login')
            member.get_by_label('Usuário', exact=True).fill('aluno')
            member.get_by_label('Senha', exact=True).fill(portal.MEMBER_PASSWORD)
            member.get_by_role('button', name='Entrar no portal', exact=True).click()
            member.wait_for_url('**/biblioteca')
            check(member.locator('[data-open="upload-dialog"], a[href$="/editar"], a[href="/contas"], #upload-dialog').count() == 0, 'Estudante conserva acesso somente de consulta')
            check(member.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Cards sem rolagem horizontal no celular')
            member.locator('.subject-card a', has_text='Estruturas de Dados II').click()
            member.wait_for_url(f'**/materias/{ed2}')
            member.locator('.material-menu summary').first.click()
            expect(member.locator('.material-menu[open]')).to_contain_text('Baixar arquivo')
            check('Editar' not in member.locator('.material-menu[open]').inner_text(), 'Menu do estudante oferece apenas download')
            check(member.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Matéria sem rolagem horizontal no celular')
            member_context.close()
            fallback = browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 844}, storage_state=context.storage_state())
            fallback_page = fallback.new_page()
            fallback_page.goto(base + '/index.php?route=home')
            expect(fallback_page.locator('html')).to_have_attribute('data-theme', 'dark')
            record('Tema escuro funciona também sem JavaScript')
            fallback_page.locator('.subject-card a', has_text='Estruturas de Dados II').click()
            fallback_page.wait_for_url(f'**/materias/{ed2}')
            record('Card leva à matéria também sem JavaScript')
            fallback_page.locator('[data-library-filter] input[name="q"]').fill('Ponteiros')
            fallback_page.locator('[data-library-filter] button[aria-label="Buscar"]').click()
            expect(fallback_page.locator('.material-title')).to_have_text(['Ponteiros em C — Estruturas de Dados II'])
            fallback_page.locator('.material-title').click()
            expect(fallback_page.locator('.document-viewer iframe')).to_be_visible()
            record('Busca e leitura funcionam também sem JavaScript')
            fallback.close()
            for blocked in [False, True]:
                default_context = browser.new_context()
                if blocked:
                    default_context.add_init_script('Storage.prototype.getItem = Storage.prototype.setItem = () => { throw new Error("Storage blocked"); };')
                else:
                    default_context.add_init_script('localStorage.setItem("humcode.theme", "light"); localStorage.removeItem("humcode.theme.v2");')
                default_page = default_context.new_page()
                default_page.on('pageerror', lambda error: errors.append(str(error)))
                default_page.goto(base + '/index.php?route=login')
                expect(default_page.locator('html')).to_have_attribute('data-theme', 'dark')
                record('Tema escuro com armazenamento bloqueado' if blocked else 'Preferência antiga não mantém o tema claro anterior')
                default_context.close()
            browser.close()
            check(not errors, 'Nenhum erro JavaScript: ' + repr(errors))

    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed', 'checks_count': len(checks), 'checks': checks, 'environment': 'Chrome headless; PHP local; SQLite temporário', 'sha256': {name: hashlib.sha256((portal.ROOT / name).read_bytes()).hexdigest() for name in ['portal/assets/app.css', 'portal/assets/app.js', 'portal/assets/theme.js', 'portal/assets/favicon.svg', 'portal/src/views.php', 'portal/src/controller.php']}}
    (output / 'frontend-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
