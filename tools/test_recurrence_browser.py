"""Recorrência no Chrome: formulários, Select2, escopos, tarefas e celular."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    checks, errors = [], []
    def check(value, label):
        assert value, label
        checks.append(label)
    def choose(page, name, option, scope=''):
        page.locator(scope + '[name=' + name + '] + .select2 .select2-selection').click()
        page.get_by_role('option', name=option, exact=True).click()
    with test_server(Path(args.php)) as (base, db, _, _, _, _, _):
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        day = str(today+timedelta(days=7))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.browser, headless=True)
            for width in [1440,390,320]:
                page = browser.new_page(viewport=dict(width=width,height=1000))
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base+'/entrar')
                page.get_by_label('Usuário',exact=True).fill('aluno')
                page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD)
                page.get_by_role('button',name='Entrar no portal').click()
                page.wait_for_url('**/biblioteca')
                page.goto(base+'/agenda/novo?dia='+day)
                check(page.locator('[data-recurrence-options]').is_hidden(),f'{width}: cadastro avulso começa sem opções de repetição')
                title = 'Série Chrome '+str(width)
                page.get_by_label('Título',exact=True).fill(title)
                choose(page,'category','Curso')
                choose(page,'recurrence','Semanalmente')
                check(page.locator('[data-recurrence-weekdays]').is_visible(),f'{width}: repetição semanal mostra dias')
                check(page.locator('[name="recurrence_days[]"]:checked').count()==1,f'{width}: dia inicial pré-selecionado')
                choose(page,'recurrence','Mensalmente')
                check(page.locator('[data-recurrence-weekdays]').is_hidden(),f'{width}: repetição mensal dispensa dias da semana')
                check(page.locator('[name=recurrence_interval]').get_attribute('max')=='12',f'{width}: intervalo mensal limitado a 12')
                page.get_by_label('Quantidade de ocorrências',exact=True).fill('3')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: formulário recorrente cabe na tela')
                page.screenshot(path=str(portal.ROOT/f'artifacts/recurrence-form-{width}.png'),full_page=True)
                page.get_by_role('button',name='Salvar evento',exact=True).click()
                page.wait_for_url('**/agenda/eventos/*')
                event = int(page.url.rsplit('/',1)[1])
                series = db.execute('SELECT recurrence_id FROM hc_portal_events WHERE id = ?',(event,)).fetchone()[0]
                check(db.execute('SELECT COUNT(*) FROM hc_portal_events WHERE recurrence_id = ?',(series,)).fetchone()[0]==3,f'{width}: formulário cria três eventos')
                check(page.locator('.event-detail .recurrence-badge').inner_text()=='Recorrente',f'{width}: detalhe identifica repetição')
                page.get_by_role('link',name='Nova tarefa neste evento',exact=True).click()
                page.locator('#detail-dialog [data-event-form]').wait_for()
                check(page.locator('[data-recurrence-fields]').is_hidden(),f'{width}: tarefa vinculada acompanha evento sem segunda regra concorrente')
                task_title = 'Preparar '+str(width)
                page.get_by_label('Título',exact=True).fill(task_title)
                page.get_by_label('Data',exact=True).fill(str(today+timedelta(days=6)))
                page.get_by_role('button',name='Salvar tarefa',exact=True).click()
                page.locator('#detail-dialog .event-detail').wait_for()
                task = db.execute('SELECT id FROM hc_portal_tasks WHERE title = ? ORDER BY id',(task_title,)).fetchone()[0]
                check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE recurrence_id = ?',(series,)).fetchone()[0]==3,f'{width}: tarefa se repete com os três eventos')
                button = page.get_by_role('checkbox',name='Concluir tarefa '+task_title,exact=True)
                button.focus()
                button.press('Enter')
                page.get_by_role('checkbox',name='Reabrir tarefa '+task_title,exact=True).wait_for()
                check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE recurrence_id = ? AND completed_at IS NOT NULL',(series,)).fetchone()[0]==1,f'{width}: teclado conclui apenas uma ocorrência')
                page.locator('#detail-dialog').get_by_role('link',name='Editar',exact=True).click()
                page.locator('#detail-dialog [data-event-form] [name=recurrence_scope] + .select2').wait_for(state='visible')
                check(page.locator('#detail-dialog [data-event-form] [name=recurrence_scope] + .select2').count()==1,f'{width}: alcance de edição usa Select2')
                choose(page,'recurrence_scope','Série inteira','#detail-dialog [data-event-form] ')
                page.get_by_label('Título',exact=True).fill(task_title+' pendentes')
                page.get_by_role('button',name='Salvar tarefa',exact=True).click()
                page.locator('#detail-dialog .event-detail').wait_for()
                check(db.execute('SELECT title FROM hc_portal_tasks WHERE id = ?',(task,)).fetchone()[0]==task_title,f'{width}: edição da série preserva tarefa concluída')
                check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE recurrence_id = ? AND title = ?',(series,task_title+' pendentes')).fetchone()[0]==2,f'{width}: edição da série altera as duas pendentes')
                page.goto(base+'/agenda/eventos/'+str(event))
                page.get_by_role('link',name='Editar',exact=True).click()
                choose(page,'recurrence_scope','Somente esta ocorrência','#detail-dialog [data-event-form] ')
                page.get_by_label('Título',exact=True).fill(title+' exceção')
                page.get_by_role('button',name='Salvar evento',exact=True).click()
                page.locator('#detail-dialog .event-detail').wait_for()
                check('Exceção' in page.locator('#detail-dialog .event-detail .recurrence-badge').inner_text(),f'{width}: alteração individual aparece como exceção')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: detalhe recorrente com tarefa cabe na tela')
                page.goto(base+'/agenda/eventos/'+str(event))
                page.screenshot(path=str(portal.ROOT/f'artifacts/recurrence-event-{width}.png'),full_page=True)
                page.locator('[data-theme-toggle]').click()
                check(page.locator('html').get_attribute('data-theme')=='light' and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tema claro sem overflow')
                page.get_by_role('button',name='Excluir evento',exact=True).click()
                check(page.locator('#delete-event-dialog [name=recurrence_scope] + .select2').count()==1,f'{width}: alcance de exclusão usa Select2 dentro do diálogo')
                choose(page,'recurrence_scope','Esta e as próximas')
                page.locator('#delete-event-dialog [name=confirm]').check()
                page.locator('#delete-event-dialog [type=submit]').click()
                page.wait_for_url('**/agenda?*')
                check(db.execute('SELECT COUNT(*) FROM hc_portal_events WHERE recurrence_id = ?',(series,)).fetchone()[0]==0,f'{width}: exclusão desta e próximas inclui a exceção selecionada')
                check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE recurrence_id = ?',(series,)).fetchone()[0]==3,f'{width}: excluir eventos preserva tarefas')
                page.close()
            context = browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000))
            page = context.new_page()
            page.goto(base+'/entrar')
            page.get_by_label('Usuário',exact=True).fill('aluno')
            page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD)
            page.get_by_role('button',name='Entrar no portal').click()
            page.wait_for_url('**/biblioteca')
            page.goto(base+'/agenda/novo?dia=2032-01-31')
            page.get_by_label('Título',exact=True).fill('Série sem JavaScript')
            page.locator('[name=category]').select_option('curso')
            page.locator('[name=recurrence]').select_option('monthly')
            page.locator('[name=recurrence_count]').fill('3')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Formulário recorrente sem JavaScript cabe em 320 px')
            page.get_by_role('button',name='Salvar evento',exact=True).click()
            page.wait_for_url('**/agenda/eventos/*')
            event = int(page.url.rsplit('/',1)[1])
            series = db.execute('SELECT recurrence_id FROM hc_portal_events WHERE id = ?',(event,)).fetchone()[0]
            check([r[0] for r in db.execute('SELECT event_date FROM hc_portal_events WHERE recurrence_id = ? ORDER BY event_date',(series,))]==['2032-01-31','2032-02-29','2032-03-31'],'Sem JavaScript cria série mensal com último dia e ano bissexto')
            check(not errors,'Nenhum erro JavaScript nos fluxos de recorrência')
            context.close(); browser.close()
    paths=['portal/src/recurrence.php','portal/src/agenda-views.php','portal/src/task-views.php','portal/assets/app.css','portal/assets/app.js']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/recurrence-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Recorrência Chrome:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
