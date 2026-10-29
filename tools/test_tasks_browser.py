"""Tarefas no Chrome: agenda, checklist do evento e formulários em telas pequenas."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server

parser = argparse.ArgumentParser()
parser.add_argument('--php', required=True)
parser.add_argument('--browser', required=True)
args = parser.parse_args()
checks, errors = [], []

def check(value, label):
    assert value, label
    checks.append(label)

with test_server(Path(args.php)) as (base, db, config, storage, manifest, scratch, env):
    member = portal.Client(base)
    member.login('aluno', portal.MEMBER_PASSWORD)
    token = member.csrf()
    today = datetime.now(timezone(timedelta(hours=-3))).date()
    subject = db.execute('SELECT id FROM hc_portal_subjects ORDER BY id LIMIT 1').fetchone()[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser, headless=True)
        for width in [1440, 390, 320]:
            event = int(member.request('/agenda/eventos/criar', dict(csrf=token, title='Evento tarefas ' + str(width), event_date=str(today), all_day='0', starts_at='10:00', ends_at='11:00', priority='urgente', category='faculdade', subject_id=subject))[1]['Location'].rsplit('/', 1)[1])
            page = browser.new_page(viewport=dict(width=width, height=1000))
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/entrar')
            page.get_by_label('Usuário', exact=True).fill('aluno')
            page.get_by_label('Senha', exact=True).fill(portal.MEMBER_PASSWORD)
            page.get_by_role('button', name='Entrar no portal').click()
            page.wait_for_url('**/biblioteca')
            page.goto(base + '/agenda/eventos/' + str(event))
            page.get_by_role('link', name='Nova tarefa neste evento', exact=True).click()
            page.locator('#detail-dialog [data-event-form]').wait_for()
            for name, value in [('event_id',str(event)),('category','faculdade'),('subject_id',str(subject)),('priority','urgente'),('event_date',str(today)),('starts_at','10:00'),('ends_at','11:00'),('title','')]:
                check(page.locator('[name=' + name + ']').input_value() == value, f'{width}: formulário herda {name} corretamente')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: formulário vinculado cabe na tela')
            title = 'Preparar atividade ' + str(width)
            page.get_by_label('Título', exact=True).fill(title)
            page.get_by_role('button', name='Salvar tarefa', exact=True).click()
            page.locator('#detail-dialog .event-detail').wait_for()
            task = db.execute('SELECT id FROM hc_portal_tasks WHERE title = ?', (title,)).fetchone()[0]
            check(db.execute('SELECT event_id, starts_at, ends_at FROM hc_portal_tasks WHERE id = ?', (task,)).fetchone() == (event,'10:00','11:00'), f'{width}: tarefa criada com vínculo e horário coincidente')
            page.goto(base + '/agenda/tarefas/' + str(task))
            page.locator('[data-notification-menu] > summary').click()
            check(page.locator('.notification-popover [data-notification-kind=task]').count() == 1, f'{width}: sino inclui aviso da tarefa')
            page.keyboard.press('Escape')
            with page.expect_navigation():
                page.get_by_role('checkbox', name='Concluir tarefa ' + title, exact=True).click()
            check(page.get_by_role('checkbox', name='Reabrir tarefa ' + title, exact=True).get_attribute('aria-checked') == 'true', f'{width}: conclusão atualiza checkbox')
            page.goto(base + '/agenda/eventos/' + str(event))
            check(page.locator('[data-task-progress]').inner_text() == '1 de 1 concluídas', f'{width}: evento apresenta progresso concluído')
            page.screenshot(path=str(portal.ROOT / f'artifacts/tasks-event-{width}.png'), full_page=True)
            with page.expect_navigation():
                page.get_by_role('checkbox', name='Reabrir tarefa ' + title, exact=True).click()
            check(page.locator('[data-task-progress]').inner_text() == '0 de 1 concluídas', f'{width}: reabertura no checklist atualiza progresso')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: checklist cabe na tela')
            page.goto(base + '/agenda')
            check(page.locator('[data-task-row]').count() == 1 and page.locator('[data-event-row]').count() == 1, f'{width}: dia apresenta evento e tarefa')
            check('☐ ' + title in page.locator('.calendar-grid').text_content(), f'{width}: calendário diferencia tarefas')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'{width}: agenda com tarefas cabe na tela')
            page.screenshot(path=str(portal.ROOT / f'artifacts/tasks-agenda-{width}.png'), full_page=True)
            page.locator('[data-notification-menu] > summary').click()
            check(page.locator('.notification-popover [data-notification-kind=task]').count() == 0, f'{width}: conclusão encerra aviso e reabertura preserva leitura')
            page.keyboard.press('Escape')
            page.get_by_role('link', name='Nova tarefa', exact=True).click()
            page.locator('#detail-dialog [data-event-form]').wait_for()
            check(page.locator('[name=event_id]').input_value() == '', f'{width}: cadastro avulso sem vínculo obrigatório')
            check(page.locator('[data-event-times]').is_hidden(), f'{width}: tarefa avulsa começa em dia inteiro')
            page.get_by_label('Título', exact=True).fill('Avulsa ' + str(width))
            page.locator('[name=category] + .select2 .select2-selection').click()
            page.get_by_role('option', name='Curso', exact=True).click()
            page.locator('[name=all_day] + .select2 .select2-selection').click()
            page.get_by_role('option', name='Com horário de início e fim', exact=True).click()
            page.get_by_label('Início', exact=True).fill('10:00')
            page.get_by_label('Fim', exact=True).fill('11:00')
            page.get_by_role('button', name='Salvar tarefa', exact=True).click()
            page.locator('#detail-dialog .event-detail').wait_for()
            standalone = db.execute('SELECT id FROM hc_portal_tasks WHERE title = ?', ('Avulsa ' + str(width),)).fetchone()[0]
            check(db.execute('SELECT event_id, category, starts_at FROM hc_portal_tasks WHERE id = ?', (standalone,)).fetchone() == (None,'curso','10:00'), f'{width}: tarefa avulsa permite sobreposição de horário')
            page.goto(base + '/agenda/tarefas/' + str(task))
            page.get_by_role('link', name='Editar', exact=True).click()
            page.get_by_label('Data', exact=True).fill(str(today + timedelta(days=1)))
            page.get_by_role('button', name='Salvar tarefa', exact=True).click()
            page.locator('#detail-dialog .event-detail').wait_for()
            check(db.execute('SELECT task_date FROM hc_portal_tasks WHERE id = ?', (task,)).fetchone()[0] == str(today+timedelta(days=1)), f'{width}: edição permite data própria')
            page.goto(base + '/agenda/eventos/' + str(event))
            check(page.locator('[data-task-row]').count() == 1, f'{width}: evento mantém checklist de tarefa em outro dia')
            page.get_by_role('button', name='Excluir evento', exact=True).click()
            page.locator('#delete-event-dialog [name=confirm]').check()
            page.locator('#delete-event-dialog [type=submit]').click()
            page.wait_for_url('**/agenda?*')
            page.goto(base + '/agenda/tarefas/' + str(task))
            check('Tarefa avulsa' in page.locator('.event-detail').inner_text(), f'{width}: excluir evento preserva tarefa acessível')
            for item in [task, standalone]:
                page.goto(base + '/agenda/tarefas/' + str(item))
                page.get_by_role('button', name='Excluir tarefa', exact=True).click()
                page.locator('#delete-task-dialog [name=confirm]').check()
                page.locator('#delete-task-dialog [type=submit]').click()
                page.wait_for_url('**/agenda?*')
                check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE id = ?', (item,)).fetchone()[0] == 0, f'{width}: exclusão confirmada remove tarefa {item}')
            page.close()
        check(not errors, 'Nenhum erro JavaScript nos fluxos de tarefas')
        browser.close()
paths = ['portal/src/task-views.php','portal/src/agenda-views.php','portal/src/views.php','portal/assets/app.css','portal/assets/app.js']
report = dict(status='verified', checks=len(checks), results=checks, tested_at=datetime.now(timezone.utc).isoformat(), sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
(portal.ROOT/'artifacts/tasks-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Tarefas Chrome:',len(checks),'verificações aprovadas')
