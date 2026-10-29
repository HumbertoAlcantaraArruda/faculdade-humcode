"""Valida Select2 pela interface, incluindo diálogos e filtros que trocam o DOM."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
import test_portal as portal
from test_runtime_fixes import test_server


def verify_select2(base, browser_path, login, password, output):
    checks = []
    output.mkdir(parents=True, exist_ok=True)

    def check(condition, label):
        assert condition, label
        checks.append(label)

    def complete(page):
        check(page.locator('select').count() == page.locator('select.select2-hidden-accessible').count(), 'Todos os selects da tela estão aprimorados')
        check(page.locator('.select2-container:not(.select2-container--open)').count() == page.locator('select').count(), 'Cada select tem uma única instância')

    def choose(page, label, option):
        page.get_by_role('combobox', name=label, exact=True).click()
        page.get_by_role('option', name=option, exact=True).click()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_path, headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/entrar')
            page.get_by_label('Usuário', exact=True).fill(login)
            page.get_by_label('Senha', exact=True).fill(password)
            page.get_by_role('button', name='Entrar no portal', exact=True).click()
            page.wait_for_url('**/biblioteca')
            # A biblioteca mostra cards; os filtros ficam nas listas de materiais.
            page.goto(base + '/materiais/sem-materia')
            complete(page)
            marker = page.evaluate('window.select2Marker = Math.random()')
            subject = page.locator('[data-subject-filter] option').nth(1).text_content()
            page.get_by_role('combobox', name='Filtrar por matéria', exact=True).click()
            search = page.locator('.select2-container--open .select2-search__field')
            expect(search).to_be_focused()
            search.fill('termo-que-nao-existe-select2')
            expect(page.get_by_text('Nenhum resultado encontrado', exact=True)).to_be_visible()
            checks.append('Busca e mensagem de ausência de resultados em português')
            search.fill(subject)
            page.get_by_role('option', name=subject, exact=True).click()
            expect(page.locator('[data-library-filter]')).to_have_attribute('data-route', 'subject')
            check(page.evaluate('window.select2Marker') == marker, 'Escolher matéria atualiza sem recarregar')
            complete(page)
            expect(page.locator('#upload-dialog select[name="subject_id"] + .select2 .select2-selection__rendered')).to_have_text(subject)
            checks.append('Destino visual do upload acompanha a matéria filtrada')
            choose(page, 'Filtrar por formato', 'HTML interativo')
            expect(page.locator('[data-library-filter] select[name="type"]')).to_have_value('html')
            expect(page.locator('[data-library-page]')).not_to_have_attribute('aria-busy', 'true')
            complete(page)
            choose(page, 'Ordenar materiais', 'Título: A–Z')
            expect(page.locator('[data-library-filter] select[name="sort"]')).to_have_value('title')
            expect(page.locator('[data-library-page]')).not_to_have_attribute('aria-busy', 'true')
            complete(page)
            page.get_by_role('combobox', name='Ordenar materiais', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.locator('.select2-dropdown')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('.select2-dropdown')).to_have_count(0)
            checks.append('Controle abre e fecha pelo teclado')
            for width in (320, 390, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 844})
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Sem rolagem horizontal: ' + str(width))
            page.get_by_role('combobox', name='Filtrar por matéria', exact=True).click()
            page.screenshot(path=str(output / 'select2-biblioteca.png'))
            page.keyboard.press('Escape')
            page.goto(base + '/biblioteca')
            page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
            dialog = page.locator('#upload-dialog')
            select = dialog.locator('select[name="subject_id"]')
            check(not select.evaluate('n => n.reportValidity()'), 'Matéria obrigatória continua sendo validada')
            expect(dialog.get_by_role('combobox', name='Matéria', exact=True)).to_have_attribute('aria-invalid', 'true')
            expect(dialog.locator('.select2-dropdown')).to_be_visible()
            check(page.locator('body > .select2-container--open').count() == 0, 'Lista de opções permanece dentro do diálogo')
            dialog.locator('.select2-search__field').fill(subject)
            dialog.get_by_role('option', name=subject, exact=True).click()
            check(select.evaluate('n => n.validity.valid'), 'Selecionar matéria resolve a validação obrigatória')
            expected_subject = select.input_value()
            check(select.evaluate('n => new FormData(n.form).get("subject_id")') == expected_subject, 'Select2 conserva os valores enviados pelo formulário')
            dialog.get_by_role('combobox', name='Matéria', exact=True).click()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(output / 'select2-upload-celular.png'))
            page.keyboard.press('Escape')
            expect(dialog).to_be_visible()
            expect(dialog.locator('.select2-dropdown')).to_have_count(0)
            checks.append('Escape fecha as opções e mantém o diálogo aberto')
            dialog.get_by_role('button', name='Cancelar', exact=True).click()
            page.goto(base + '/contas')
            complete(page)
            page.get_by_role('button', name='Nova conta', exact=True).click()
            choose(page, 'Tipo de acesso', 'Administrador')
            expect(page.locator('#user-dialog select[name="role"]')).to_have_value('admin')
            checks.append('Tipo de acesso usa Select2 dentro do diálogo de contas')
            page.locator('#user-dialog').get_by_role('button', name='Cancelar', exact=True).click()
            page.goto(base + '/biblioteca')
            page.goto(base + page.locator('.subject-card a').first.get_attribute('href'))
            material = page.locator('.material-title').first.get_attribute('href')
            page.goto(base + material + '/editar')
            complete(page)
            choose(page, 'Matéria', 'Sem matéria')
            expect(page.locator('main select[name="subject_id"]')).to_have_value('')
            checks.append('Edição de material permite escolher Sem matéria')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.get_by_role('combobox', name='Matéria', exact=True).click()
            page.screenshot(path=str(output / 'select2-editar-material.png'))
            page.keyboard.press('Escape')
            page.locator('[data-theme-toggle]').click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'light')
            page.get_by_role('combobox', name='Matéria', exact=True).click()
            check(page.locator('.select2-dropdown').evaluate('n => getComputedStyle(n).backgroundColor') == 'rgb(255, 255, 255)', 'Select2 acompanha o tema claro')
            check(not errors, 'Nenhum erro JavaScript: ' + repr(errors))
        finally:
            browser.close()
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    with test_server(Path(args.php)) as fixture:
        checks = verify_select2(fixture[0], args.browser, 'admin', portal.ADMIN_PASSWORD, portal.ROOT / 'artifacts')
    files = ['portal/src/views.php', 'portal/assets/app.js', 'portal/assets/app.css', 'portal/assets/vendor/jquery-3.7.1.min.js', 'portal/assets/vendor/select2-4.1.0.min.js', 'portal/assets/vendor/select2-4.1.0.min.css', 'portal/assets/vendor/select2-pt-BR.js']
    report = {'status': 'passed', 'verified_at': datetime.now(timezone.utc).isoformat(), 'checks_count': len(checks), 'checks': checks, 'sha256': {name: hashlib.sha256((portal.ROOT / name).read_bytes()).hexdigest() for name in files}}
    (portal.ROOT / 'artifacts/select2-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
