"""Chrome: notas privadas, formulário, edição, exclusão e sem JavaScript."""
import argparse
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); parser.add_argument('--browser',required=True); args=parser.parse_args(); checks,errors=[],[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,_,_,_,_):
        admin=portal.Client(base); admin.login(); token=admin.csrf()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.browser,headless=True)
            for width in [1440,390,320]:
                subject=int(admin.request('/materias/criar',dict(csrf=token,name='Notas Chrome '+str(width),color='teal'))[1]['Location'].rsplit('/',1)[1])
                page=browser.new_page(viewport=dict(width=width,height=1000)); page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill('aluno'); page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
                page.goto(base+'/materias/'+str(subject)); page.get_by_role('button',name='Nova anotação',exact=True).click(); dialog=page.locator('#note-dialog'); dialog.wait_for(state='visible'); check(page.url.endswith('/materias/'+str(subject)),f'{width}: nova nota abre modal sem trocar de página')
                check(dialog.locator('[name=subject_id]').input_value()==str(subject),f'{width}: nova nota herda matéria')
                check(dialog.locator('[name=subject_id] + .select2').count()==1,f'{width}: matéria usa Select2')
                title='Resumo Chrome '+str(width); body='Primeira linha\nSegunda linha com <script>alert(1)</script>\n'+'x'*180
                dialog.get_by_label('Título',exact=True).fill(title); dialog.get_by_label('Conteúdo',exact=True).fill(body)
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: formulário sem overflow')
                check(dialog.evaluate("d=>{const r=d.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&Math.abs(r.left-(innerWidth-r.right))<=1}"),f'{width}: modal centralizado')
                pdf=b'%PDF-1.4 1 0 obj<<>>endobj trailer<<>> %%EOF'; attach=page.locator('[data-note-attachments]')
                check(attach.count()==1 and page.get_by_text('Até 3 arquivos por anotação',exact=False).is_visible(),f'{width}: formulário oferece anexos')
                attach.set_input_files([dict(name=f'aula{i}.pdf',mimeType='application/pdf',buffer=pdf) for i in range(4)])
                check(page.locator('[data-note-files-error]').is_visible() and attach.evaluate('e=>e.files.length')==3 and dialog.locator('[data-selected-name]').count()==3,f'{width}: quatro arquivos: três ficam na lista e aparece aviso')
                page.screenshot(path=str(portal.ROOT/f'artifacts/notes-attachments-error-{width}.png'),full_page=True)
                for _ in range(3): dialog.locator('[data-selected-remove]').first.click()
                check(dialog.locator('[data-selected-name]').count()==0 and attach.evaluate('e=>e.files.length')==0 and not page.locator('[data-note-files-error]').is_visible(),f'{width}: lixo remove arquivos escolhidos')
                attach.set_input_files([dict(name='aula.pdf',mimeType='application/pdf',buffer=pdf)]); attach.set_input_files([dict(name='texto.html',mimeType='text/html',buffer=b'<!doctype html><p>nota</p>')])
                check(dialog.locator('[data-selected-name]').all_inner_texts()==['aula.pdf','texto.html'] and attach.evaluate('e=>e.files.length')==2 and not page.locator('[data-note-files-error]').is_visible(),f'{width}: segunda escolha soma à primeira')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: formulário com anexos sem overflow')
                dialog.get_by_role('button',name='Salvar anotação',exact=True).click(); page.wait_for_url('**/anotacoes/*'); note=int(page.url.rsplit('/',1)[1])
                check(page.get_by_role('heading',name=title,exact=True).is_visible(),f'{width}: nota criada')
                check(page.locator('.note-files').is_visible() and page.get_by_role('heading',name='Arquivos',exact=True).is_visible() and page.get_by_text('aula.pdf',exact=True).is_visible() and page.get_by_text('texto.html',exact=True).is_visible(),f'{width}: nota exibe os anexos')
                check(page.get_by_role('link',name='Baixar').count()==2 and page.get_by_role('link',name='Abrir').count()==2,f'{width}: ações abrir e baixar por arquivo')
                check(page.locator('.note-body').inner_text()==body,f'{width}: conteúdo e quebras de linha preservados')
                check(page.locator('.note-body script').count()==0,f'{width}: HTML não executado')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: texto longo cabe na tela')
                page.screenshot(path=str(portal.ROOT/f'artifacts/notes-detail-{width}.png'),full_page=True)
                page.get_by_role('link',name='Editar anotação',exact=True).click(); page.get_by_label('Título',exact=True).fill(title+' editado'); page.get_by_label('Conteúdo',exact=True).fill(body+'\nObservação editada'); page.get_by_role('button',name='Salvar anotação',exact=True).click()
                check(page.get_by_role('heading',name=title+' editado',exact=True).is_visible(),f'{width}: edição pela interface')
                page.goto(base+'/materias/'+str(subject)); check(page.locator('[data-note-row="'+str(note)+'"]').count()==1,f'{width}: nota aparece dentro da matéria')
                check(page.locator('[data-note-count]').get_attribute('data-note-count')=='1',f'{width}: contagem privada na matéria')
                page.get_by_role('link',name='Ver todas as anotações desta matéria (1)',exact=True).click()
                check(page.locator('.notes-filter-form [name=subject_id]').input_value()==str(subject),f'{width}: lista mantém filtro da matéria')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: lista cabe na tela')
                page.evaluate("document.documentElement.dataset.theme='light'"); page.screenshot(path=str(portal.ROOT/f'artifacts/notes-list-light-{width}.png'),full_page=True)
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tema claro sem overflow')
                second=browser.new_page(); second.goto(base+'/entrar'); second.get_by_label('Usuário',exact=True).fill('admin'); second.get_by_label('Senha',exact=True).fill(portal.ADMIN_PASSWORD); second.get_by_role('button',name='Entrar no portal').click(); second.wait_for_url('**/biblioteca'); second.goto(base+'/materias/'+str(subject))
                check(second.locator('[data-note-count]').get_attribute('data-note-count')=='0',f'{width}: administrador não vê notas de aluno')
                second.close()
                page.goto(base+'/anotacoes/'+str(note)); page.get_by_role('button',name='Excluir anotação',exact=True).click(); page.wait_for_selector('.swal2-popup')
                check('Essa ação não pode ser desfeita' in page.locator('.swal2-popup').inner_text(),f'{width}: exclusão pede confirmação em modal')
                page.get_by_role('button',name='Não',exact=True).click(); page.wait_for_selector('.swal2-popup',state='detached'); check(page.url.endswith('/anotacoes/'+str(note)),f'{width}: cancelar mantém a anotação')
                page.get_by_role('button',name='Excluir anotação',exact=True).click(); page.wait_for_selector('.swal2-popup')
                with page.expect_navigation(): page.get_by_role('button',name='Sim',exact=True).click()
                check(page.locator('[data-note-total]').get_attribute('data-note-total')=='0',f'{width}: exclusão pela interface com confirmação')
                page.close()
            # lista de /anotacoes com Tabulator: doze por página, importantes primeiro e identificadas
            member_id=db.execute("SELECT id FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
            db.execute('DELETE FROM hc_portal_notes WHERE user_id=?',(member_id,))
            for i in range(14):
                db.execute('INSERT INTO hc_portal_notes (user_id,subject_id,title,body,important,updated_at) VALUES (?,?,?,?,?,?)',(member_id,None,'Tabela %02d'%i,'Texto da tabela %d'%i,1 if i in (3,7) else 0,'2032-01-%02d 10:00:00'%(i+1)))
            db.commit()
            for width in [1440,390]:
                page=browser.new_page(viewport=dict(width=width,height=1000)); page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill('aluno'); page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
                page.goto(base+'/anotacoes'); page.locator('.tabulator-row').first.wait_for()
                check(page.locator('.tabulator-row').count()==12,f'{width}: tabela mostra doze anotações por página')
                check(page.locator('.tabulator-row [data-note-important]').count()==2 and page.locator('.tabulator-row').nth(0).locator('[data-note-important]').count()==1 and page.locator('.tabulator-row').nth(1).locator('[data-note-important]').count()==1 and page.locator('.tabulator-row').nth(2).locator('[data-note-important]').count()==0,f'{width}: importantes vêm primeiro e têm identificador')
                check(page.locator('.tabulator-row').nth(0).locator('.note-card-title').inner_text()=='Tabela 07' and page.locator('.tabulator-row').nth(2).locator('.note-card-title').inner_text()=='Tabela 13',f'{width}: ordem por importância e data')
                check([x.inner_text() for x in page.locator('.tabulator-paginator button').all()]==['«','‹','1','2','›','»'],f'{width}: paginação « ‹ 1 2 › »')
                check(page.locator('.tabulator-page.active').inner_text()=='1' and page.locator('.tabulator-page[data-page=first]').is_disabled(),f'{width}: primeira página ativa')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tabela de anotações sem overflow')
                page.locator('.tabulator-page[data-page=next]').click()
                page.locator('.tabulator-page.active',has_text='2').wait_for()
                check(page.locator('.tabulator-row').count()==2 and page.locator('.tabulator-row [data-note-important]').count()==0,f'{width}: segunda página traz o restante')
                first_button=page.locator('.tabulator-page[data-page=first]'); (first_button if first_button.is_visible() else page.locator('.tabulator-page[data-page=prev]')).click(); page.locator('.tabulator-page.active',has_text='1').wait_for()
                page.locator('.tabulator-row').first.get_by_role('link').click(); page.wait_for_selector('#detail-dialog[open]')
                check(page.locator('#detail-dialog .note-important-button.is-active').count()==1 and page.url.endswith('/anotacoes'),f'{width}: card abre em modal com estrela ativa')
                with page.expect_navigation(): page.locator('#detail-dialog .note-important-button').click()
                page.wait_for_selector('#detail-dialog[open]')
                check(db.execute('SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=? AND important=1',(member_id,)).fetchone()[0]==1 and page.locator('#detail-dialog .note-important-button.is-active').count()==0,f'{width}: estrela remove a importância e reabre o modal')
                page.locator('#detail-dialog [data-close]').first.click()
                db.execute('UPDATE hc_portal_notes SET important=1 WHERE title=?',('Tabela 07',)); db.commit()
                page.close()
            db.execute('DELETE FROM hc_portal_notes WHERE user_id=?',(member_id,)); db.commit()
            context=browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000)); page=context.new_page()
            page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill('aluno'); page.get_by_label('Senha',exact=True).fill(portal.MEMBER_PASSWORD); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
            page.goto(base+'/anotacoes/nova'); page.get_by_label('Título',exact=True).fill('Sem JavaScript'); page.get_by_label('Conteúdo',exact=True).fill('Nota privada sem matéria.'); page.get_by_role('button',name='Salvar anotação',exact=True).click()
            check(page.get_by_role('heading',name='Sem JavaScript',exact=True).is_visible(),'Sem JavaScript cria anotação')
            check('Sem matéria' in page.locator('.page-heading').inner_text(),'Nota sem associação identificada')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Sem JavaScript sem overflow em 320 px')
            page.get_by_label('Confirmo a exclusão desta anotação.').check(); page.get_by_role('button',name='Excluir anotação',exact=True).click()
            check(page.locator('[data-note-total]').get_attribute('data-note-total')=='0','Sem JavaScript exclui anotação')
            check(not errors,'Nenhum erro JavaScript nas anotações'); context.close(); browser.close()
    paths=['portal/src/notes.php','portal/src/views.php','portal/assets/app.css']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/notes-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n'); print('Anotações Chrome:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
