"""Chrome: adicionar/remover vínculos, Select2, conteúdo herdado e acessibilidade."""
import argparse
from datetime import datetime, timezone
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
    def choose(page, name, label):
        page.locator('[name='+name+'] + .select2 .select2-selection').click()
        page.get_by_role('option', name=label, exact=True).click()
    with test_server(Path(args.php)) as (base, db, _, _, _, _, _):
        member = portal.Client(base)
        member.login('aluno', portal.MEMBER_PASSWORD)
        token = member.csrf()
        subject = db.execute('SELECT id FROM hc_portal_subjects LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO hc_portal_videos (subject_id,title,youtube_id) VALUES (?, ?, ?)', (subject, 'Vídeo Chrome', 'dQw4w9WgXcQ'))
        db.execute('INSERT INTO hc_portal_folders (subject_id,name) VALUES (?, ?)', (subject, 'Pasta Chrome'))
        db.commit()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.browser, headless=True)
            for width in [1440,390,320]:
                values = dict(csrf=token,title='Vínculos Chrome '+str(width),description='',event_date='2032-01-31',all_day='1',priority='media',category='curso',subject_id='')
                event = int(member.request('/agenda/eventos/criar',values)[1]['Location'].rsplit('/',1)[1])
                task = int(member.request('/agenda/tarefas/criar',dict(values,event_id=event))[1]['Location'].rsplit('/',1)[1])
                page = browser.new_page(viewport=dict(width=width,height=1000))
                page.on('pageerror',lambda error: errors.append(str(error)))
                page.goto(base+'/entrar')
                page.get_by_label('Usuário',exact=True).fill('aluno')
                page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD)
                page.get_by_role('button',name='Entrar no portal').click()
                page.wait_for_url('**/biblioteca')
                page.goto(base+'/agenda/eventos/'+str(event))
                page.get_by_role('link',name='Gerenciar vínculos').click()
                check(page.locator('[name=content_id] + .select2').count()==1,f'{width}: seletor de conteúdo usa Select2')
                page.get_by_label('Buscar conteúdo ou matéria').fill('Gatilhos')
                page.get_by_role('button',name='Buscar conteúdo',exact=True).click()
                check(page.locator('[name=content_id] option').count()>0,f'{width}: busca encontra arquivo')
                page.get_by_role('button',name='Vincular conteúdo',exact=True).click()
                check(page.get_by_role('heading',name='Vínculos próprios').is_visible(),f'{width}: vínculo criado pela interface')
                own = page.locator('.content-link-row')
                title = own.locator('strong').first.inner_text()
                check(own.count()==1,f'{width}: um arquivo vinculado')
                choose(page,'type','Vídeo')
                page.get_by_label('Buscar conteúdo ou matéria').fill('Vídeo Chrome')
                page.get_by_role('button',name='Buscar conteúdo',exact=True).click()
                page.get_by_role('button',name='Vincular conteúdo',exact=True).click()
                check(page.locator('.content-link-row').count()==2,f'{width}: vídeo vinculado')
                choose(page,'type','Pasta')
                page.get_by_label('Buscar conteúdo ou matéria').fill('Pasta Chrome')
                page.get_by_role('button',name='Buscar conteúdo',exact=True).click()
                page.get_by_role('button',name='Vincular conteúdo',exact=True).click()
                check(page.locator('.content-link-row').count()==3,f'{width}: pasta vinculada')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: gerenciar vínculos cabe na tela')
                page.screenshot(path=str(portal.ROOT/f'artifacts/content-links-manage-{width}.png'),full_page=True)
                page.goto(base+'/agenda/tarefas/'+str(task))
                check(page.get_by_role('heading',name='Conteúdos do evento').is_visible(),f'{width}: tarefa mostra conteúdo herdado')
                check(page.locator('.content-link-row').count()==3,f'{width}: tarefa herda três referências')
                page.goto(base+'/agenda/conteudos?kind=task&item_id='+str(task))
                page.get_by_role('button',name='Vincular conteúdo',exact=True).click()
                page.goto(base+'/agenda/tarefas/'+str(task))
                check(page.locator('.content-link-row').count()==4,f'{width}: tarefa mostra vínculo próprio e herdados')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tarefa com vínculos cabe na tela')
                page.screenshot(path=str(portal.ROOT/f'artifacts/content-links-task-{width}.png'),full_page=True)
                page.goto(base+'/agenda/conteudos?kind=event&item_id='+str(event))
                page.get_by_role('button',name='Remover vínculo: '+title,exact=True).click()
                check(page.locator('.content-link-row').count()==2,f'{width}: remoção pela interface')
                page.evaluate("document.documentElement.dataset.theme='light'")
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tema claro cabe na tela')
                page.get_by_label('Buscar conteúdo ou matéria').focus()
                check(page.get_by_label('Buscar conteúdo ou matéria').evaluate('(e)=>e===document.activeElement'),f'{width}: campo acessível por foco')
                page.close()
            context = browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000))
            page = context.new_page()
            page.goto(base+'/entrar')
            page.get_by_label('Usuário',exact=True).fill('aluno')
            page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD)
            page.get_by_role('button',name='Entrar no portal').click()
            page.wait_for_url('**/biblioteca')
            page.goto(base+'/agenda/conteudos?kind=event&item_id='+str(event))
            page.get_by_label('Tipo de conteúdo').select_option('file')
            page.get_by_role('button',name='Buscar conteúdo',exact=True).click()
            page.get_by_role('button',name='Vincular conteúdo',exact=True).click()
            check(page.locator('.content-link-row').count()==3,'Sem JavaScript adiciona arquivo')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Sem JavaScript cabe em 320 px')
            check(not errors,'Nenhum erro JavaScript nos vínculos')
            context.close(); browser.close()
    paths=['portal/src/content-links.php','portal/src/agenda-views.php','portal/src/task-views.php','portal/assets/app.css','portal/src/views.php']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/content-links-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Conteúdos Chrome:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
