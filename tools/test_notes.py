"""Anotações: dono, revisões, limites Unicode, paginação e matéria excluída."""
import argparse
from datetime import datetime, timezone
import hashlib,json,re
from pathlib import Path
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); args=parser.parse_args(); checks=[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,_,_,_,_):
        member,admin=portal.Client(base),portal.Client(base); member.login('aluno',portal.MEMBER_PASSWORD); admin.login(); mt,at=member.csrf(),admin.csrf()
        owner=db.execute("SELECT id FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
        subject=int(admin.request('/materias/criar',dict(csrf=at,name='Notas HTTP',color='teal'))[1]['Location'].rsplit('/',1)[1])
        baseline=db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        def create(expected=303,client=member,**options):
            response=client.request('/anotacoes/criar',dict(dict(csrf=mt,title='Resumo privado',body='Primeira linha\nSegunda linha',subject_id=subject),**options))
            check(response[0]==expected,'Criar anotação HTTP '+str(expected))
            return int(response[1]['Location'].rsplit('/',1)[1]) if expected==303 else None
        note=create(); another=create(title='Outra nota na mesma matéria')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=? AND subject_id=?',(owner,subject)).fetchone()[0]==2,'Várias notas por matéria permitidas')
        check(member.request('/anotacoes/'+str(note))[0]==200,'Dono lê anotação')
        check(admin.request('/anotacoes/'+str(note))[0]==404,'Administrador não lê nota alheia')
        check(admin.request('/anotacoes/'+str(note)+'/editar')[0]==404,'Administrador não abre edição alheia')
        update=dict(csrf=mt,id=note,revision=1,title='Resumo atualizado',body='Conteúdo atualizado',subject_id=subject)
        check(admin.request('/anotacoes/atualizar',dict(update,csrf=at))[0]==404,'Administrador não altera nota alheia')
        check(admin.request('/anotacoes/excluir',dict(csrf=at,id=note,revision=1,confirm=1))[0]==404,'Administrador não exclui nota alheia')
        check(b'data-note-total="0"' in admin.request('/anotacoes')[2],'Contagem de notas privada para administrador')
        check(b'data-note-count="0"' in admin.request('/materias/'+str(subject))[2],'Contagem na matéria também privada')
        check(b'data-note-count="2"' in member.request('/materias/'+str(subject))[2],'Notas do dono exibidas dentro da matéria')
        check(b'data-note-total="0"' in admin.request('/anotacoes?user_id='+str(owner))[2],'Parâmetro de dono não revela notas')
        check(member.request('/anotacoes/atualizar',dict(update,csrf='invalid'))[0]==403,'Edição exige CSRF')
        check(member.request('/anotacoes/criar')[0]==405,'Criação exige POST')
        check(member.request('/anotacoes/atualizar')[0]==405,'Edição exige POST')
        check(member.request('/anotacoes/excluir')[0]==405,'Exclusão exige POST')
        check(member.request('/anotacoes/atualizar',update)[0]==303,'Dono edita nota')
        check(member.request('/anotacoes/atualizar',update)[0]==409,'Formulário antigo é recusado')
        check(member.request('/anotacoes/excluir',dict(csrf=mt,id=note,revision=1,confirm=1))[0]==409,'Exclusão exige revisão atual')
        check(member.request('/anotacoes/excluir',dict(csrf=mt,id=note,revision=2))[0]==400,'Exclusão exige confirmação')
        create(expected=400,title=''); create(expected=400,body=''); create(expected=400,title='x'*181); create(expected=400,body='x'*20001)
        create(expected=400,subject_id=999999)
        check(member.request('/anotacoes/criar',dict(csrf=mt,title='Nota',body='Texto',**{'subject_id[]':'1'}))[0]==400,'Matéria estruturada é recusada')
        escaped=create(title='<img src=x onerror=alert(1)>',body='<script>alert(1)</script>\nTexto & aspas "')
        body=member.request('/anotacoes/'+str(escaped))[2]
        check(b'&lt;script&gt;alert(1)&lt;/script&gt;' in body and b'<script>alert(1)</script>' not in body,'HTML da nota escapado')
        check(b'&lt;img src=x onerror=alert(1)&gt;' in body and b'<img src=x onerror=alert(1)>' not in body,'Título escapado')
        long=create(title='Texto Unicode longo',body='\U0001f4da'*20000)
        check(len(db.execute('SELECT body FROM hc_portal_notes WHERE id=?',(long,)).fetchone()[0])==20000,'Limite aceita 20 mil caracteres Unicode sem perda')
        no_subject=create(subject_id='',title='Nota sem matéria')
        check(b'data-note-row="'+str(no_subject).encode()+b'"' in member.request('/anotacoes?subject_id=0')[2],'Lista pessoal inclui notas sem matéria')
        for i in range(21):
            db.execute('INSERT INTO hc_portal_notes (user_id,subject_id,title,body) VALUES (?, ?, ?, ?)',(owner,subject,'Paginação '+str(i),'Texto'))
        db.commit()
        body=member.request('/anotacoes?subject_id='+str(subject))[2]
        check(body.count(b'data-note-row=')==12 and b'Pr\xc3\xb3xima' in body and b'data-notes-table' in body,'Listagem de notas paginada de doze em doze')
        body=member.request('/anotacoes?subject_id='+str(subject)+'&pagina=3')[2]
        check(body.count(b'data-note-row=')==1 and b'Anterior' in body,'Última página preserva filtro e restantes')
        body=member.request('/materias/'+str(subject))[2]
        check(body.count(b'data-note-row=')==5 and b'data-note-count="25"' in body,'Matéria limita notas exibidas com contagem privada completa')
        check(member.request('/anotacoes?subject_id[]=1')[0]==400,'Filtro estruturado recusado')
        check(member.request('/anotacoes/nova?subject_id=999999')[0]==404,'Nova nota recusa matéria inexistente')
        check(member.request('/anotacoes/'+str(note)+'?id='+str(no_subject))[2].find(b'Resumo atualizado')>=0,'ID do caminho prevalece sobre query')
        # anotações importantes: até cinco por matéria, importantes primeiro, dados paginados em JSON
        ids=[r[0] for r in db.execute('SELECT id FROM hc_portal_notes WHERE user_id=? AND subject_id=? ORDER BY id',(owner,subject))]
        def mark(note_id,value='1',client=member,token=None,expected=303):
            response=client.request('/anotacoes/importante',dict(csrf=token or (mt if client is member else at),id=note_id,important=value))
            check(response[0]==expected,'Marcar importante '+str(value)+' -> '+str(expected)); return response
        def important_in(group):
            sql='SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=? AND important=1 AND '+('subject_id IS NULL' if group is None else 'subject_id=?')
            return db.execute(sql,(owner,) if group is None else (owner,group)).fetchone()[0]
        for item in ids[:5]: mark(item)
        check(important_in(subject)==5,'Cinco anotações importantes na matéria')
        refused=mark(ids[5],expected=409)
        check(b'j\xc3\xa1 tem 5' in refused[2] and important_in(subject)==5,'Sexta importante da matéria é recusada sem alterar nada')
        mark(ids[5],'0',expected=303); mark(ids[0],'0'); mark(ids[5])
        check(important_in(subject)==5 and not db.execute('SELECT important FROM hc_portal_notes WHERE id=?',(ids[0],)).fetchone()[0],'Remover libera vaga para outra importante')
        mark(no_subject)
        check(important_in(None)==1,'Notas sem matéria têm grupo próprio de importantes')
        check(member.request('/anotacoes/importante',dict(id=ids[0],important='1'))[0]==403,'Marcar importante exige CSRF')
        check(member.request('/anotacoes/importante')[0]==405,'Marcar importante exige POST')
        check(member.request('/anotacoes/importante',dict(csrf=mt,id=ids[0],important='talvez'))[0]==400,'Valor inválido de importância é recusado')
        mark(ids[0],expected=404,client=admin)
        check(db.execute('SELECT important FROM hc_portal_notes WHERE id=?',(ids[0],)).fetchone()[0]==0,'Outro usuário não altera importância alheia')
        data=json.loads(member.request('/anotacoes/dados?page=1&size=12')[2])
        total=db.execute('SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=?',(owner,)).fetchone()[0]
        check(len(data['data'])==12 and data['total']==total and data['last_page']==-(-total//12),'Dados JSON paginam de doze em doze')
        check([row['important'] for row in data['data'][:6]]==[True]*6 and not any(row['important'] for row in data['data'][6:]),'Importantes vêm primeiro nos dados')
        check(set(data['data'][0])=={'id','title','subject','date','excerpt','important','url'},'Dados JSON expõem só os campos do card')
        last=json.loads(member.request('/anotacoes/dados?page='+str(data['last_page'])+'&size=12')[2])
        check(len(last['data'])==total-12*(data['last_page']-1),'Última página traz o restante')
        check(len(json.loads(member.request('/anotacoes/dados?page=1&size=500')[2])['data'])==12,'Tamanho de página é limitado a doze')
        only=json.loads(member.request('/anotacoes/dados?subject_id='+str(subject))[2])
        check(only['total']==db.execute('SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=? AND subject_id=?',(owner,subject)).fetchone()[0] and all(row['subject']=='Notas HTTP' for row in only['data']),'Dados JSON respeitam o filtro de matéria')
        check(json.loads(admin.request('/anotacoes/dados')[2])['total']==0,'Dados JSON não vazam notas de outro usuário')
        check(portal.Client(base).request('/anotacoes/dados')[0]==303,'Dados JSON exigem autenticação')
        check(member.request('/anotacoes/dados?subject_id[]=1')[0]==400,'Dados JSON recusam filtro estruturado')
        check(b'note-important-button' in member.request('/anotacoes/'+str(ids[1])+'?modal=1')[2],'Detalhe oferece o botão de estrela')
        # mover uma importante para matéria já cheia é recusado
        other=int(admin.request('/materias/criar',dict(csrf=at,name='Outra matéria cheia',color='blue'))[1]['Location'].rsplit('/',1)[1])
        for i in range(5):
            db.execute('INSERT INTO hc_portal_notes (user_id,subject_id,title,body,important) VALUES (?,?,?,?,1)',(owner,other,'Cheia '+str(i),'Texto'))
        db.commit()
        marked=[r[0] for r in db.execute('SELECT id FROM hc_portal_notes WHERE user_id=? AND subject_id=? AND important=1',(owner,subject))][0]
        current=db.execute('SELECT title,body,revision FROM hc_portal_notes WHERE id=?',(marked,)).fetchone()
        move=member.request('/anotacoes/atualizar',dict(csrf=mt,id=marked,revision=current[2],title=current[0],body=current[1],subject_id=other))
        check(move[0]==409 and db.execute('SELECT subject_id FROM hc_portal_notes WHERE id=?',(marked,)).fetchone()[0]==subject,'Mover importante para matéria cheia é recusado')
        old_revision=db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(note,)).fetchone()[0]
        check(admin.request('/materias/excluir',dict(csrf=at,id=subject,revision=1,confirm=1))[0]==303,'Excluir matéria com notas privadas')
        row=db.execute('SELECT subject_id,revision,body FROM hc_portal_notes WHERE id=?',(note,)).fetchone()
        check(row==(None,old_revision+1,'Conteúdo atualizado'),'Exclusão preserva texto e incrementa revisão')
        check(important_in(None)==5,'Excluir matéria mantém no máximo cinco importantes sem matéria')
        check(member.request('/anotacoes/atualizar',dict(update,revision=old_revision,subject_id=''))[0]==409,'Formulário anterior à exclusão da matéria é recusado')
        check(b'Sem mat\xc3\xa9ria' in member.request('/anotacoes/'+str(note))[2],'Nota preservada continua acessível sem matéria')
        check(b'data-note-total="26"' in member.request('/anotacoes?subject_id=0')[2],'Lista pessoal mantém todas as notas da matéria excluída')
        check(member.request('/anotacoes/atualizar',dict(update,revision=old_revision+1,subject_id=''))[0]==303,'Nota preservada pode ser editada')
        check(member.request('/anotacoes/excluir',dict(csrf=mt,id=note,revision=old_revision+2,confirm=1))[0]==303,'Dono exclui anotação')
        check(member.request('/anotacoes/'+str(note))[0]==404,'Nota excluída não acessível')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()==baseline,'Anotações não alteram materiais compartilhados')
        guest=portal.Client(base); check(guest.request('/anotacoes/'+str(another))[0]==303,'Nota exige autenticação')
        check(guest.login('aluno',portal.MEMBER_PASSWORD)[1]['Location']=='/anotacoes/'+str(another),'Login retoma anotação privada solicitada')
    paths=['portal/src/notes.php','portal/src/subjects.php','portal/src/views.php','portal/src/migrations.php','portal/schema.sql']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/notes-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Anotações:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
