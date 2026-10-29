"""Meu dia no Chrome: menu, paginação, teclado, temas e telas pequenas."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server
from test_my_day import seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    checks, errors = [], []
    def check(value, label):
        assert value, label
        checks.append(label)
    with test_server(Path(args.php)) as (base, db, _, _, _, _, _):
        owner = db.execute("SELECT id FROM hc_portal_users WHERE login = 'aluno'").fetchone()[0]
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.browser, headless=True)
            for width in [1440, 390, 320]:
                page = browser.new_page(viewport=dict(width=width, height=1000))
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/entrar')
                page.get_by_label('Usuário', exact=True).fill('aluno')
                page.get_by_label('Senha', exact=True).fill(portal.MEMBER_PASSWORD)
                page.get_by_role('button', name='Entrar no portal').click()
                page.wait_for_url('**/biblioteca')
                check(page.get_by_role('heading', name='Biblioteca', exact=True).is_visible(), f'{width}: login continua na biblioteca')
                if width < 800: page.locator('[data-sidebar-toggle]').click()
                page.locator('.main-nav').get_by_role('link', name='Meu dia', exact=True).click()
                page.wait_for_url('**/meu-dia')
                check(page.locator('.main-nav .active').text_content().strip() == 'Meu dia', f'{width}: menu abre e destaca Meu dia')
                check(page.locator('.agenda-empty').count() == 4, f'{width}: estados vazios acessíveis')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: painel vazio cabe na tela')
                seed(db, owner, today)
                page.reload()
                check(page.locator('[data-my-day-count=tarefas]').inner_text() == '14', f'{width}: contagem real de pendências')
                check(page.locator('#tarefas > [data-task-row]').count() == 10, f'{width}: lista limita volume')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: painel com conteúdo cabe na tela')
                page.screenshot(path=str(portal.ROOT / f'artifacts/my-day-{width}.png'), full_page=True)
                page.locator('#tarefas > .my-day-pagination').get_by_role('link', name='Próxima', exact=True).click()
                page.wait_for_url('**/meu-dia?tarefas=2#tarefas')
                check(page.locator('#tarefas > [data-task-row]').count() == 4, f'{width}: segunda página mostra restante')
                title = page.locator('#tarefas > [data-task-row] .task-title').first.inner_text()
                button = page.get_by_role('checkbox', name='Concluir tarefa ' + title, exact=True)
                button.focus()
                check(button.evaluate('node => node === document.activeElement'), f'{width}: botão de conclusão aceita foco')
                with page.expect_navigation(): button.press('Enter')
                check('tarefas=2' in page.url and page.locator('[data-my-day-count=tarefas]').inner_text() == '13', f'{width}: teclado conclui e conserva paginação')
                page.goto(base + '/meu-dia?concluidas=2')
                check(page.locator('#concluidas').get_attribute('open') is not None, f'{width}: página de concluídas permanece aberta')
                # The newly completed title can be on either completed page, ordered by title.
                for completed_page in [1, 2]:
                    page.goto(base + '/meu-dia?concluidas=' + str(completed_page))
                    if page.get_by_role('checkbox', name='Reabrir tarefa ' + title, exact=True).count(): break
                with page.expect_navigation(): page.get_by_role('checkbox', name='Reabrir tarefa ' + title, exact=True).click()
                check(page.locator('[data-my-day-count=tarefas]').inner_text() == '14', f'{width}: reabertura atualiza listas e contagens')
                page.get_by_role('link', name='Nova tarefa', exact=True).click()
                page.locator('#detail-dialog [data-event-form]').wait_for()
                check(page.locator('[name=event_date]').input_value() == str(today), f'{width}: atalho nova tarefa usa hoje')
                page.keyboard.press('Escape')
                page.locator('#detail-dialog').wait_for(state='hidden')
                page.get_by_role('link', name='Novo evento', exact=True).click()
                page.locator('#detail-dialog [data-event-form]').wait_for()
                check(page.locator('[name=event_date]').input_value() == str(today), f'{width}: atalho novo evento usa hoje')
                page.keyboard.press('Escape')
                page.locator('#detail-dialog').wait_for(state='hidden')
                page.get_by_role('link', name='Agenda completa', exact=True).click()
                page.wait_for_url('**/agenda')
                check(page.get_by_role('heading', name='Minha agenda', exact=True).is_visible(), f'{width}: atalho agenda completa')
                page.go_back()
                page.locator('[data-theme-toggle]').click()
                check(page.locator('html').get_attribute('data-theme') == 'light', f'{width}: tema claro funciona')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: tema claro cabe na tela')
                page.screenshot(path=str(portal.ROOT / f'artifacts/my-day-light-{width}.png'), full_page=True)
                page.locator('[data-theme-toggle]').click()
                check(page.locator('html').get_attribute('data-theme') == 'dark', f'{width}: volta ao tema escuro')
                page.close()
                db.execute('DELETE FROM hc_portal_tasks')
                db.execute('DELETE FROM hc_portal_events')
                db.commit()
            context = browser.new_context(java_script_enabled=False, viewport=dict(width=320, height=1000))
            page = context.new_page()
            page.goto(base + '/meu-dia')
            page.get_by_label('Usuário', exact=True).fill('aluno')
            page.get_by_label('Senha', exact=True).fill(portal.MEMBER_PASSWORD)
            page.get_by_role('button', name='Entrar no portal').click()
            page.wait_for_url('**/meu-dia')
            check(page.get_by_role('heading', name='Meu dia', exact=True).is_visible(), 'Painel acessível sem JavaScript e login retoma o destino')
            seed(db, owner, today)
            page.reload()
            title = page.locator('#tarefas > [data-task-row] .task-title').first.inner_text()
            page.get_by_role('checkbox', name='Concluir tarefa ' + title, exact=True).click()
            page.wait_for_url('**/meu-dia')
            check(page.locator('[data-my-day-count=tarefas]').inner_text() == '13', 'Conclusão funciona sem JavaScript')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Painel sem JavaScript cabe em 320 px')
            check(not errors, 'Sem erros JavaScript no painel')
            context.close()
            browser.close()
    paths = ['portal/src/my-day.php','portal/src/views.php','portal/assets/app.css','portal/assets/app.js']
    report = dict(status='verified', checks=len(checks), results=checks, tested_at=datetime.now(timezone.utc).isoformat(), sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/my-day-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Meu dia Chrome:', len(checks), 'verificações aprovadas')


if __name__ == '__main__': main()
