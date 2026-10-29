"""Chrome: estudo manual, privacidade, leitura, temas, teclado e ausência de JS."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); parser.add_argument('--browser',required=True); args=parser.parse_args()
    checks,errors=[],[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,_,_,_,_):
        admin=portal.Client(base); admin.login(); token=admin.csrf()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.browser,headless=True)
            for width in [1440,390,320]:
                subject=int(admin.request('/materias/criar',dict(csrf=token,name='Estudo Chrome '+str(width),color='teal'))[1]['Location'].rsplit('/',1)[1])
                admin.upload(token,subject,[('estudo.txt','text/plain',b'Estudo Chrome')])
                file=db.execute('SELECT id FROM hc_portal_files WHERE subject_id=?',(subject,)).fetchone()[0]
                db.execute('INSERT INTO hc_portal_videos (subject_id,title,youtube_id) VALUES (?, ?, ?)',(subject,'Vídeo Chrome '+str(width),'dQw4w9WgXcQ')); db.commit()
                context=browser.new_context(viewport=dict(width=width,height=1000)); page=context.new_page()
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill('aluno'); page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
                page.goto(base+'/materias/'+str(subject))
                check(page.locator('[data-study-progress=all]').get_attribute('data-study-done')=='0',f'{width}: estudo começa pendente')
                check(page.locator('[data-study-progress=all]').get_attribute('data-study-total')=='2',f'{width}: dois conteúdos disponíveis')
                check(page.locator('[data-video-frame] iframe').count()==0,f'{width}: progresso não abre player automaticamente')
                page.get_by_role('checkbox',name='Marcar como assistido: Vídeo Chrome '+str(width),exact=True).click()
                check(page.get_by_role('checkbox',name='Desmarcar: Vídeo Chrome '+str(width),exact=True).get_attribute('aria-checked')=='true',f'{width}: marcar vídeo altera estado acessível')
                check(page.locator('[data-study-progress=video]').get_attribute('data-study-done')=='1',f'{width}: total de vídeos atualizado')
                page.goto(base+'/materiais/'+str(file))
                check(page.get_by_role('checkbox',name='Marcar como estudado: estudo',exact=True).get_attribute('aria-checked')=='false',f'{width}: abrir material não comprova estudo')
                page.get_by_role('checkbox',name='Marcar como estudado: estudo',exact=True).click()
                check(page.get_by_role('checkbox',name='Desmarcar: estudo',exact=True).get_attribute('aria-checked')=='true',f'{width}: material marcado pela interface')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: leitura marcada cabe na tela')
                page.goto(base+'/materias/'+str(subject))
                check(page.locator('[data-study-progress=all]').get_attribute('data-study-done')=='2',f'{width}: total combinado atualizado')
                check('100%' in page.locator('[data-study-progress=all]').inner_text(),f'{width}: percentual combinado correto')
                check(page.locator('.study-badge').count()==1,f'{width}: lista mostra material estudado')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: matéria marcada cabe na tela')
                page.screenshot(path=str(portal.ROOT/f'artifacts/study-subject-{width}.png'),full_page=True)
                page.evaluate("document.documentElement.dataset.theme='light'")
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tema claro sem overflow')
                page.screenshot(path=str(portal.ROOT/f'artifacts/study-light-{width}.png'),full_page=True)
                button=page.get_by_role('checkbox',name='Desmarcar: Vídeo Chrome '+str(width),exact=True); button.focus(); button.press('Space')
                check(page.locator('[data-study-progress=video]').get_attribute('data-study-done')=='0',f'{width}: desmarcação pelo teclado')
                check(page.locator('[data-study-progress=all]').get_attribute('data-study-done')=='1',f'{width}: desmarcação atualiza total combinado')
                second=browser.new_page(viewport=dict(width=width,height=1000)); second.goto(base+'/entrar'); second.get_by_label('Usuário',exact=True).fill('admin'); second.get_by_label('Senha',exact=True).fill(portal.ADMIN_PASSWORD); second.get_by_role('button',name='Entrar no portal').click(); second.wait_for_url('**/biblioteca'); second.goto(base+'/materias/'+str(subject))
                check(second.locator('[data-study-progress=all]').get_attribute('data-study-done')=='0',f'{width}: administrador só vê progresso próprio')
                second.close(); context.close()
            context=browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000)); page=context.new_page()
            page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill('aluno'); page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
            page.goto(base+'/materiais/'+str(file)); page.get_by_role('checkbox',name='Desmarcar: estudo',exact=True).click()
            check(page.get_by_role('checkbox',name='Marcar como estudado: estudo',exact=True).get_attribute('aria-checked')=='false','Sem JavaScript desmarca estudo')
            page.get_by_role('checkbox',name='Marcar como estudado: estudo',exact=True).click()
            page.goto(base+'/materias/'+str(subject))
            check(page.locator('[data-study-progress=all]').get_attribute('data-study-done')=='1','Sem JavaScript marca e atualiza total')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Sem JavaScript cabe em 320 px')
            check(not errors,'Nenhum erro JavaScript no estudo')
            context.close(); browser.close()
    paths=['portal/src/study.php','portal/src/views.php','portal/assets/app.css']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/study-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Estudo Chrome:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
