"""Convites: destinatários, privacidade, respostas, cancelamento, limites e e-mail."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib,json,re,secrets,urllib.parse
from pathlib import Path
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); args=parser.parse_args(); checks=[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,_,_,folder,_):
        member,admin=portal.Client(base),portal.Client(base); member.login('aluno',portal.MEMBER_PASSWORD); admin.login(); mt,at=member.csrf(),admin.csrf()
        owner=db.execute("SELECT id FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
        admin_id=db.execute("SELECT id FROM hc_portal_users WHERE login='admin'").fetchone()[0]
        hashed=db.execute("SELECT password_hash FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
        recipients=[]
        for i in range(12):
            db.execute('INSERT INTO hc_portal_users (login,name,password_hash,role,must_change_password) VALUES (?, ?, ?, ?, 0)',('guest'+str(i),'Convidado '+str(i),hashed,'member'))
            recipients.append(db.execute('SELECT last_insert_rowid()').fetchone()[0])
        db.commit()
        guest,twin=portal.Client(base),portal.Client(base); guest.login('guest0',portal.MEMBER_PASSWORD); twin.login('guest0',portal.MEMBER_PASSWORD); gt,tt=guest.csrf(),twin.csrf()
        subject=db.execute('SELECT id FROM hc_portal_subjects LIMIT 1').fetchone()[0]
        baseline=db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        defaults=dict(csrf=mt,title='Evento para convite',description='Descrição privada do evento',event_date='2032-01-31',all_day='0',starts_at='10:00',ends_at='11:00',category='curso',priority='urgente',subject_id=subject)
        def create(**options):
            response=member.request('/agenda/eventos/criar',dict(defaults,**options)); check(response[0]==303,'Criar evento de origem'); return int(response[1]['Location'].rsplit('/',1)[1])
        def row(table,id):
            cur=db.execute('SELECT * FROM hc_portal_'+table+' WHERE id=?',(id,)); item=cur.fetchone(); return dict(zip([c[0] for c in cur.description],item)) if item else None
        def send(event,ids,expected=303,client=member,token=mt,**options):
            data=dict(csrf=token,event_id=event,revision=row('events',event)['revision'],**{'recipient_ids[]':[str(i) for i in ids]}); data.update(options)
            response=client.request('/convites/enviar',urllib.parse.urlencode(data,doseq=True).encode()); check(response[0]==expected,'Enviar convites HTTP '+str(expected)); return response
        def invitation(event,recipient):
            return db.execute('SELECT id FROM hc_portal_invitations WHERE source_event_id=? AND recipient_id=? ORDER BY id DESC',(event,recipient)).fetchone()[0]
        def answer(id,choice='accepted',expected=303,client=guest,token=gt,**options):
            data=dict(csrf=token,id=id,revision=row('invitations',id)['revision'],choice=choice); data.update(options)
            response=client.request('/convites/responder',data); check(response[0]==expected,'Responder '+choice+' HTTP '+str(expected)); return response
        event=create()
        send(event,[recipients[0],admin_id]); send(event,[recipients[0],admin_id])
        check(db.execute('SELECT COUNT(*) FROM hc_portal_invitations WHERE source_event_id=?',(event,)).fetchone()[0]==2,'Vários destinatários e repetição sem duplicação')
        invite=invitation(event,recipients[0]); other=invitation(event,admin_id)
        check(db.execute('SELECT COUNT(*) FROM hc_portal_events WHERE user_id=?',(recipients[0],)).fetchone()[0]==0,'Convite não adiciona evento automaticamente')
        check(b'data-notification-kind="invitation"' in guest.request('/notificacoes')[2],'Convite aparece nos avisos do destinatário')
        check(b'Convite:' in guest.request('/biblioteca')[2],'Convite aparece no sino')
        check(member.request('/convites/'+str(invite))[0]==200,'Remetente consulta estado de seu convite')
        check(guest.request('/agenda/eventos/'+str(event))[0]==404,'Convite não abre agenda do remetente')
        stranger=portal.Client(base); stranger.login('guest1',portal.MEMBER_PASSWORD); st=stranger.csrf()
        check(stranger.request('/convites/'+str(invite))[0]==404,'Terceiro não lê convite')
        answer(invite,expected=404,client=admin,token=at)
        answer(invite,expected=404,client=member,token=mt)
        answer(invite,expected=403,csrf='invalid')
        answer(invite,choice='invalid',expected=400)
        check(guest.request('/convites/responder')[0]==405,'Resposta exige POST')
        check(guest.request('/notificacoes/convites/ler',dict(csrf=gt,id=invite))[0]==303,'Destinatário marca aviso como lido')
        check(row('invitations',invite)['state']=='pending','Ler aviso não aceita convite')
        check(admin.request('/notificacoes/convites/ler',dict(csrf=at,id=invite))[0]==404,'Administrador não lê aviso de outra conta')
        data=dict(csrf=gt,id=invite,revision=1,choice='accepted')
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda pair:pair[0].request('/convites/responder',dict(data,csrf=pair[1]))[0],[(guest,gt),(twin,tt)]))
        check(statuses==[303,303],'Aceitação simultânea é idempotente')
        accepted=row('invitations',invite); copy=row('events',accepted['accepted_event_id'])
        check(accepted['state']=='accepted' and copy['user_id']==recipients[0],'Aceite cria evento do destinatário')
        check(copy['title']==defaults['title'] and copy['description']==defaults['description'] and copy['starts_at']=='10:00' and copy['priority']=='urgente','Cópia conserva campos do evento convidado')
        check(copy['recurrence_id'] is None,'Cópia aceita independente de recorrência')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_events WHERE user_id=?',(recipients[0],)).fetchone()[0]==1,'Aceitações concorrentes criam somente uma cópia')
        answer(invite,revision=1); answer(invite,choice='declined',expected=409)
        answer(other,choice='declined',client=admin,token=at); answer(other,choice='declined',client=admin,token=at,revision=1)
        check(row('invitations',other)['accepted_event_id'] is None,'Recusa não cria evento')
        check(b'data-accepted-event=' not in member.request('/convites/'+str(invite))[2],'Remetente não recebe link para agenda privada do destinatário')

        mfrag = member.request('/convites/' + str(invite) + '?modal=1')
        check(mfrag[0] == 200 and b'data-detail-fragment' in mfrag[2] and b'<html' not in mfrag[2] and b'back-link' not in mfrag[2], 'Detalhe do convite em modal devolve só o fragmento')
        check(stranger.request('/convites/' + str(invite) + '?modal=1')[0] == 404, 'Fragmento do convite não vaza para outro usuário')
        check(b'<html' in member.request('/convites/' + str(invite))[2], 'Página completa do convite continua disponível')
        check(member.request('/convites?direction=sent')[2].count(b'data-invitation-row=')==2,'Remetente lista seus envios')
        check(b'data-invitation-total="0"' in stranger.request('/convites?recipient_id='+str(recipients[0]))[2],'Contagem privada ignora dono forjado')
        send(event,[owner],expected=400); send(event,[],expected=400); send(event,[recipients[1]]*2,expected=400); send(event,recipients[:11],expected=400); send(event,[999999],expected=400)
        db.execute('UPDATE hc_portal_users SET active=0 WHERE id=?',(recipients[2],)); db.commit()
        send(event,[recipients[2]],expected=400)
        check(b'name="recipient_ids[]"' not in member.request('/agenda/convidar?event_id='+str(event)+'&q=guest2')[2],'Busca oculta conta inativa')
        send(event,[recipients[1]],expected=404,client=admin,token=at)
        send(event,[recipients[1]],expected=409,revision=0)
        send(event,[recipients[1]],expected=403,csrf='invalid')
        check(member.request('/agenda/convidar?event_id='+str(event)+'&q[]=x')[0]==400,'Busca estruturada é recusada')
        check(admin.request('/agenda/convidar?event_id='+str(event))[0]==404,'Seleção de destinatários protege evento')
        send(event,[recipients[1]])
        pending=invitation(event,recipients[1])
        update=dict(defaults,id=event,revision=1,title='Evento alterado',all_day='0')
        check(member.request('/agenda/eventos/atualizar',update)[0]==303,'Alterar evento original')
        check(row('invitations',pending)['state']=='canceled','Alteração cancela convite pendente')
        check(row('events',copy['id'])['title']==defaults['title'],'Alterar original não sincroniza cópia aceita')
        send(event,[recipients[1]])
        check(invitation(event,recipients[1])!=pending,'Nova versão pode ser convidada sem reabrir convite anterior')
        renewed=invitation(event,recipients[1]); answer(renewed,expected=404)
        answer(pending,expected=409,client=stranger,token=st)
        check(member.request('/agenda/eventos/excluir',dict(csrf=mt,id=event,revision=2,confirm=1))[0]==303,'Excluir original com convites')
        check(row('invitations',renewed)['state']=='canceled' and row('invitations',renewed)['source_event_id'] is None,'Excluir original cancela pendentes e preserva histórico')
        check(row('events',copy['id']) is not None,'Excluir original preserva cópia aceita')
        expired=create(); send(expired,[recipients[0]]); old=invitation(expired,recipients[0])
        db.execute("UPDATE hc_portal_invitations SET event_date='2000-01-01' WHERE id=?",(old,)); db.commit()
        answer(old,expected=409)
        check(row('invitations',old)['state']=='canceled','Data passada cancela e bloqueia aceite')
        past=create(event_date='2000-01-01'); send(past,[recipients[0]],expected=400)
        recipient_off=create(); send(recipient_off,[recipients[3]])
        off=invitation(recipient_off,recipients[3]); db.execute('UPDATE hc_portal_users SET active=0 WHERE id=?',(recipients[3],)); db.commit()
        member.request('/convites?direction=sent')
        check(row('invitations',off)['state']=='canceled','Destinatário inativo cancela convite')
        db.execute('UPDATE hc_portal_users SET active=1 WHERE id=?',(recipients[3],)); db.commit()
        inactive=create(); send(inactive,[recipients[0]]); canceled=invitation(inactive,recipients[0])
        db.execute('UPDATE hc_portal_users SET active=0 WHERE id=?',(owner,)); db.commit(); answer(canceled,expected=409)
        check(row('invitations',canceled)['state']=='canceled','Remetente inativo cancela convite')
        db.execute('UPDATE hc_portal_users SET active=1 WHERE id=?',(owner,)); db.commit()
        # Repetição cobre uma ocorrência; tarefas, vínculos e notas não acompanham.
        recurring=create(recurrence='monthly',recurrence_interval=1,recurrence_count=3,recurrence_key=secrets.token_hex(16)); send(recurring,[recipients[0]]); ri=invitation(recurring,recipients[0])
        task=member.request('/agenda/tarefas/criar',dict(defaults,title='Tarefa privada',event_id=recurring,all_day='1'))
        check(task[0]==303,'Criar tarefa privada do evento recorrente')
        file=db.execute('SELECT id FROM hc_portal_files LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO hc_portal_event_files (event_id,file_id) VALUES (?, ?)',(recurring,file)); db.commit()
        check(member.request('/anotacoes/criar',dict(csrf=mt,title='Nota secreta do remetente',body='Texto privado',subject_id=subject))[0]==303,'Criar nota privada junto à matéria do convite')
        answer(ri)
        accepted_event=row('invitations',ri)['accepted_event_id']
        check(db.execute('SELECT COUNT(*) FROM hc_portal_tasks WHERE event_id=?',(accepted_event,)).fetchone()[0]==0,'Aceite não copia tarefas privadas')
        check(row('events',accepted_event)['recurrence_id'] is None,'Convite de série cobre só uma ocorrência')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_event_files WHERE event_id=?',(accepted_event,)).fetchone()[0]==0,'Aceite não copia vínculos do remetente')
        check(b'Nota secreta do remetente' not in guest.request('/materias/'+str(subject))[2],'Aceite não libera anotações do remetente')
        check(guest.request('/agenda/eventos/excluir',dict(csrf=gt,id=accepted_event,revision=1,confirm=1))[0]==303,'Destinatário pode excluir cópia aceita')
        answer(ri,revision=1)
        check(row('invitations',ri)['accepted_event_id'] is None,'Repetir aceite não recria cópia excluída pelo dono')
        ten=create(); active=[id for id in recipients if id!=recipients[2]][:10]; send(ten,active)
        check(db.execute('SELECT COUNT(*) FROM hc_portal_invitations WHERE source_event_id=?',(ten,)).fetchone()[0]==10,'Envio aceita exatamente dez destinatários ativos')
        changed_subject=int(admin.request('/materias/criar',dict(csrf=at,name='Matéria de convite',color='teal'))[1]['Location'].rsplit('/',1)[1])
        subject_event=create(subject_id=changed_subject); send(subject_event,[recipients[0]]); si=invitation(subject_event,recipients[0])
        check(admin.request('/materias/excluir',dict(csrf=at,id=changed_subject,revision=1,confirm=1))[0]==303,'Excluir matéria de evento convidado')
        check(row('invitations',si)['state']=='canceled','Alteração por exclusão da matéria cancela convite pendente')
        # Contato próprio, sem expor e-mail aos candidatos nem enviar mensagens.
        check(guest.request('/minha-conta/email',dict(csrf=gt,email='contato@example.test',id=owner))[0]==303,'Destinatário cadastra e-mail próprio')
        check(guest.request('/minha-conta/verificacao',dict(csrf=gt,action='confirm',code=portal.mail_code(folder,'contato@example.test')))[0]==303,'Destinatário confirma o e-mail com o código')
        check(db.execute('SELECT email FROM hc_portal_users WHERE id=?',(recipients[0],)).fetchone()[0]=='contato@example.test','E-mail pertence somente à conta autenticada')
        check(db.execute('SELECT email FROM hc_portal_users WHERE id=?',(owner,)).fetchone()[0] is None,'ID forjado não altera contato de outro usuário')
        check(b'contato@example.test' not in member.request('/agenda/convidar?event_id='+str(recurring)+'&q=guest0')[2],'Seleção não expõe e-mail de destinatário')
        check(guest.request('/minha-conta/email',dict(csrf=gt,email='invalido'))[0]==400,'E-mail inválido recusado')
        check(guest.request('/minha-conta/email',dict(csrf='invalid',email='x@example.test'))[0]==403,'Contato exige CSRF')
        check(guest.request('/minha-conta/email',dict(csrf=gt,email=''))[0]==303,'E-mail opcional pode ser removido')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()==baseline,'Convites não alteram materiais compartilhados')
        # Limite agregado: montar somente dados locais de teste.
        for i in range(50):
            db.execute('INSERT INTO hc_portal_invitations (sender_id,recipient_id,source_revision,state,title,description,event_date,category,priority) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)',(owner,recipients[0],'canceled','Limite','', '2032-01-01','curso','media'))
        db.commit(); limit=create(); send(limit,[recipients[0]],expected=429)
        check(member.request('/convites?direction=invalid')[0]==400,'Listagem rejeita direção inválida')
        check(member.request('/convites?state[]=pending')[0]==400,'Listagem rejeita estado estruturado')
    paths=['portal/src/invitations.php','portal/src/events.php','portal/src/recurrence.php','portal/src/subjects.php','portal/src/migrations.php','portal/schema.sql']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/invitations-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n'); print('Convites:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
