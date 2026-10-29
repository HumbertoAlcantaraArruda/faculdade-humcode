"""Chrome: envio múltiplo, sino, aceite/recusa, contato, temas e sem JS."""
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
    with test_server(Path(args.php)) as (base,db,_,_,_,folder,_):
        member=portal.Client(base); member.login('aluno',portal.MEMBER_PASSWORD); mt=member.csrf()
        hashed=db.execute("SELECT password_hash FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
        def create(title):
            values=dict(csrf=mt,title=title,description='Encontro de estudo\nDescrição do convite',event_date='2032-01-31',all_day='1',category='curso',priority='media',subject_id='')
            return int(member.request('/agenda/eventos/criar',values)[1]['Location'].rsplit('/',1)[1])
        def login(page,username,password):
            page.goto(base+'/entrar'); page.get_by_label('Usuário',exact=True).fill(username); page.get_by_label('Senha',exact=True).fill(password); page.get_by_role('button',name='Entrar no portal').click(); page.wait_for_url('**/biblioteca')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.browser,headless=True)
            for width in [1440,390,320]:
                login_name='recipient'+str(width); name='Convidado Chrome '+str(width)
                db.execute('INSERT INTO hc_portal_users (login,name,password_hash,role,must_change_password) VALUES (?, ?, ?, ?, 0)',(login_name,name,hashed,'member'))
                recipient=db.execute('SELECT last_insert_rowid()').fetchone()[0]; db.commit()
                title='Convite Chrome '+str(width); event=create(title)
                page=browser.new_page(viewport=dict(width=width,height=1000)); page.on('pageerror',lambda error:errors.append(str(error))); login(page,'aluno',portal.MEMBER_PASSWORD)
                page.goto(base+'/agenda/eventos/'+str(event)); page.get_by_role('link',name='Convidar usuários',exact=True).click()
                check(page.locator('.select2-selection--multiple').count()==1,f'{width}: destinatários usam Select2 múltiplo')
                for label in [name+' · '+login_name,'Admin Teste · admin']:
                    page.get_by_role('combobox',name='Destinatários',exact=True).click(); page.get_by_role('option',name=label,exact=True).click()
                check(page.locator('.select2-selection__choice').count()==2,f'{width}: duas pessoas selecionadas pela interface')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: formulário de convite sem overflow')
                page.screenshot(path=str(portal.ROOT/f'artifacts/invitations-send-{width}.png'),full_page=True)
                page.get_by_role('button',name='Enviar convites',exact=True).click()
                check(page.locator('[data-invitation-row]').count()==2,f'{width}: dois convites enviados')
                receiver=browser.new_page(viewport=dict(width=width,height=1000)); receiver.on('pageerror',lambda error:errors.append(str(error))); login(receiver,login_name,portal.MEMBER_PASSWORD)
                receiver.locator('.notification-menu summary').click(); check(receiver.get_by_role('link',name='Convite: '+title,exact=True).is_visible(),f'{width}: destinatário recebe aviso no sino')
                receiver.get_by_role('button',name='Marcar '+title+' como lida',exact=True).click()
                check(db.execute('SELECT state FROM hc_portal_invitations WHERE source_event_id=? AND recipient_id=?',(event,recipient)).fetchone()[0]=='pending',f'{width}: ler aviso mantém convite pendente')
                receiver.get_by_role('link',name='Convite: '+title,exact=True).click()
                check(receiver.get_by_role('button',name='Aceitar convite',exact=True).is_visible(),f'{width}: convite oferece aceite')
                check(receiver.get_by_role('button',name='Recusar convite',exact=True).is_visible(),f'{width}: convite oferece recusa')
                check(receiver.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: detalhe sem overflow')
                receiver.screenshot(path=str(portal.ROOT/f'artifacts/invitations-detail-{width}.png'),full_page=True)
                receiver.get_by_role('button',name='Aceitar convite',exact=True).click()
                check(receiver.locator('[data-invitation-state]').get_attribute('data-invitation-state')=='accepted',f'{width}: aceite muda estado')
                copy=int(receiver.locator('[data-accepted-event]').get_attribute('data-accepted-event'))
                receiver.get_by_role('link',name='Abrir na minha agenda',exact=True).click()
                receiver.locator('#detail-dialog .event-detail').wait_for()
                check(receiver.locator('#detail-dialog a[href$="/agenda/eventos/'+str(copy)+'/editar"]').count()==1,f'{width}: aceite abre evento próprio no mesmo modal')
                check(db.execute('SELECT user_id,recurrence_id FROM hc_portal_events WHERE id=?',(copy,)).fetchone()==(recipient,None),f'{width}: cópia independente do destinatário')
                receiver.goto(base+'/minha-conta'); receiver.get_by_label('E-mail',exact=True).fill(login_name+'@example.test'); receiver.get_by_role('button',name='Salvar e-mail',exact=True).click()
                # O novo e-mail só vale após o código enviado a ele.
                receiver.locator('[data-two-factor-pending="email"]').get_by_label('Código de verificação').fill(portal.mail_code(folder,login_name+'@example.test')); receiver.get_by_role('button',name='Confirmar código').click()
                check(receiver.get_by_label('E-mail',exact=True).input_value()==login_name+'@example.test',f'{width}: usuário salva contato próprio')
                other=browser.new_page(); login(other,'admin',portal.ADMIN_PASSWORD); other.goto(base+'/convites')
                other.get_by_role('link',name=title,exact=True).click(); other.locator('#detail-dialog').get_by_role('button',name='Recusar convite',exact=True).click()
                other.locator('#detail-dialog [data-invitation-state]').wait_for(); check(other.locator('#detail-dialog [data-invitation-state]').get_attribute('data-invitation-state')=='declined' and other.url.endswith('/convites'),f'{width}: outro destinatário recusa pelo modal e a lista é reaberta')
                other.close(); page.goto(base+'/agenda/eventos/'+str(event))
                check(page.locator('[data-invitation-state=accepted]').count()==1 and page.locator('[data-invitation-state=declined]').count()==1,f'{width}: remetente acompanha respostas distintas')
                page.evaluate("document.documentElement.dataset.theme='light'")
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'{width}: tema claro sem overflow')
                page.screenshot(path=str(portal.ROOT/f'artifacts/invitations-status-light-{width}.png'),full_page=True)
                receiver.close(); page.close()
            event=create('Convite sem JavaScript'); context=browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000)); page=context.new_page(); login(page,'aluno',portal.MEMBER_PASSWORD)
            page.goto(base+'/agenda/convidar?event_id='+str(event)); page.locator('select[name="recipient_ids[]"]').select_option(str(recipient)); page.get_by_role('button',name='Enviar convites',exact=True).click()
            check(page.locator('[data-invitation-row]').count()==1,'Sem JavaScript envia convite')
            second_context=browser.new_context(java_script_enabled=False,viewport=dict(width=320,height=1000)); page=second_context.new_page(); login(page,login_name,portal.MEMBER_PASSWORD); page.goto(base+'/convites'); page.get_by_role('link',name='Convite sem JavaScript',exact=True).click(); page.get_by_role('button',name='Aceitar convite',exact=True).focus(); page.keyboard.press('Enter')
            page.wait_for_function("document.querySelector('[data-invitation-state]')?.dataset.invitationState === 'accepted'")
            check(page.locator('[data-invitation-state]').get_attribute('data-invitation-state')=='accepted','Sem JavaScript aceita por teclado')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Sem JavaScript sem overflow em 320 px')
            check(not errors,'Nenhum erro JavaScript nos convites'); context.close(); second_context.close(); browser.close()
    paths=['portal/src/invitations.php','portal/src/agenda-views.php','portal/src/views.php','portal/assets/app.css','portal/assets/app.js']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/invitations-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n'); print('Convites Chrome:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
