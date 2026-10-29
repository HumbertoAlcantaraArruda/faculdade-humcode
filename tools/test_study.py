"""Progresso pessoal, totais, substituição, movimentação e concorrência HTTP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); args=parser.parse_args()
    checks=[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,_,_,_,_):
        member,admin,twin=[portal.Client(base) for _ in range(3)]
        member.login('aluno',portal.MEMBER_PASSWORD); admin.login(); twin.login('aluno',portal.MEMBER_PASSWORD)
        mt,at,tt=member.csrf(),admin.csrf(),twin.csrf()
        owners={r[0]:r[1] for r in db.execute('SELECT login,id FROM hc_portal_users')}
        subject=int(admin.request('/materias/criar',dict(csrf=at,name='Estudo HTTP',color='teal'))[1]['Location'].rsplit('/',1)[1])
        def progress(client,subject,**query):
            response=client.request('/materias/'+str(subject)+('?'+'&'.join(str(k)+'='+str(v) for k,v in query.items()) if query else ''))
            check(response[0]==200,'Matéria com progresso acessível')
            return {k.decode():(int(done),int(total)) for k,done,total in re.findall(rb'data-study-progress="([^"]+)" data-study-done="(\d+)" data-study-total="(\d+)"',response[2])}
        check(progress(member,subject)==dict(file=(0,0),video=(0,0),all=(0,0)),'Matéria vazia não inventa progresso')
        check('Sem conteúdo'.encode() in member.request('/materias/'+str(subject))[2],'Matéria vazia mostra Sem conteúdo')
        check(admin.upload(at,subject,[('a.txt','text/plain',b'Estudo A'),('b.txt','text/plain',b'Estudo B'),('c.txt','text/plain',b'Estudo C')])[0]==303,'Criar três arquivos de estudo')
        files=[r[0] for r in db.execute('SELECT id FROM hc_portal_files WHERE subject_id=? ORDER BY id',(subject,))]
        db.execute("UPDATE hc_portal_files SET kind='trabalho' WHERE id=?",(files[1],)); db.execute("UPDATE hc_portal_files SET kind='prova' WHERE id=?",(files[2],))
        db.execute('INSERT INTO hc_portal_videos (subject_id,title,youtube_id) VALUES (?, ?, ?)',(subject,'Vídeo HTTP','dQw4w9WgXcQ'))
        video=db.execute('SELECT last_insert_rowid()').fetchone()[0]; db.commit()
        baseline=db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        def values(type,id,state='1',**options):
            row=db.execute('SELECT revision FROM hc_portal_'+type+'s WHERE id=?',(id,)).fetchone()
            revision=row[0] if row else 1
            return dict(dict(csrf=mt,type=type,id=id,studied=state,content_revision=revision),**options)
        def mark(type,id,state='1',expected=303,client=member,**options):
            response=client.request('/estudo/marcar',values(type,id,state,**options))
            check(response[0]==expected,'Marcação '+type+' '+state+' HTTP '+str(expected))
            return response
        mark('file',files[0]); mark('file',files[0]); mark('file',files[1]); mark('video',video)
        check(progress(member,subject)==dict(file=(2,3),video=(1,1),all=(3,4)),'Totais separados e combinados incluem todas as categorias')
        check(progress(admin,subject)==dict(file=(0,3),video=(0,1),all=(0,4)),'Administrador não vê progresso do aluno')
        check(progress(admin,subject,user_id=owners['aluno'])['all']==(0,4),'Parâmetro de dono não altera privacidade')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_file_study WHERE file_id=?',(files[0],)).fetchone()[0]==1,'Repetição não duplica marcação')
        check(b'role="checkbox" aria-checked="true"' in member.request('/materiais/'+str(files[0]))[2],'Material estudado identificado na leitura')
        check(b'class="study-badge"' in member.request('/materias/'+str(subject))[2],'Lista identifica material estudado')
        mark('file',files[0],client=admin,csrf=at,user_id=owners['aluno'])
        check(db.execute('SELECT COUNT(*) FROM hc_portal_file_study WHERE file_id=?',(files[0],)).fetchone()[0]==2,'Duas contas podem estudar o mesmo arquivo independentemente')
        mark('file',files[0],'0'); mark('file',files[0],'0')
        check(progress(member,subject)['file']==(1,3),'Desmarcação atualiza somente dono')
        check(progress(admin,subject)['file']==(1,3),'Desmarcação de aluno preserva administrador')
        check(member.request('/estudo/marcar')[0]==405,'Marcação exige POST')
        mark('file',files[0],expected=403,csrf='invalid')
        mark('file',files[0],state='invalido',expected=400)
        check(member.request('/estudo/marcar',dict(csrf=mt,type='folder',id=files[0],studied='1'))[0]==400,'Pastas não são conteúdo estudável')
        check(member.request('/estudo/marcar',dict(csrf=mt,type='file',id=999999,studied='1',content_revision=1))[0]==404,'Conteúdo inexistente é recusado')
        response=mark('file',files[0],return_to='https://example.com')
        check(response[1]['Location']=='/materiais/'+str(files[0]),'Destino externo é ignorado')
        response=mark('file',files[0],return_to='/materias/'+str(subject)+'?categoria=trabalhos')
        check(response[1]['Location'].endswith('?categoria=trabalhos'),'Retorno local conserva filtro')
        data=values('file',files[2])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda pair: pair[0].request('/estudo/marcar',dict(data,csrf=pair[1]))[0],[(member,mt),(twin,tt)]))
        check(results==[303,303] and db.execute('SELECT COUNT(*) FROM hc_portal_file_study WHERE file_id=?',(files[2],)).fetchone()[0]==1,'Duas sessões não duplicam a marcação')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()==baseline,'Marcação não altera catálogo compartilhado')
        # Renomear/mover preserva estudo; substituir conteúdo reinicia para todas as contas.
        stale=values('file',files[0])
        revision=stale['content_revision']
        edits=dict(csrf=at,id=files[0],revision=revision,title='Arquivo renomeado',subject_id=subject,folder_id='',kind='material')
        check(admin.request('/materiais/atualizar',edits)[0]==303,'Renomear arquivo estudado')
        mark('file',files[0],expected=409,content_revision=revision)
        check(db.execute('SELECT COUNT(*) FROM hc_portal_file_study WHERE file_id=?',(files[0],)).fetchone()[0]==2,'Renomear preserva marcações das duas contas')
        second=int(admin.request('/materias/criar',dict(csrf=at,name='Estudo destino',color='blue'))[1]['Location'].rsplit('/',1)[1])
        check(admin.request('/materiais/atualizar',dict(edits,revision=revision+1,subject_id=second))[0]==303,'Mover arquivo estudado')
        check(progress(member,subject)['file']==(2,2) and progress(member,second)['file']==(1,1),'Movimentação reflete totais sem perder estudo')
        check(admin.multipart('/materiais/atualizar',dict(edits,revision=revision+2,subject_id=second),[('novo.txt','text/plain',b'Novo conteudo')])[0]==303,'Substituir arquivo estudado')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_file_study WHERE file_id=?',(files[0],)).fetchone()[0]==0,'Substituição reinicia marcações de todas as contas')
        check(progress(member,second)['file']==(0,1),'Total reflete substituição')
        check(admin.request('/materiais/excluir',dict(csrf=at,id=files[1],revision=1,confirm=1))[0]==303,'Excluir arquivo estudado')
        check(progress(member,subject)['file']==(1,1),'Arquivo excluído sai de denominador e numerador')
        mark('file',files[1],expected=404)
        check(admin.request('/videos/atualizar',dict(csrf=at,id=video,revision=1,title='Vídeo renomeado',url='https://youtu.be/dQw4w9WgXcQ'))[0]==303,'Renomear vídeo estudado')
        check(progress(member,subject)['video']==(1,1),'Renomear vídeo preserva marcação')
        check(admin.request('/videos/atualizar',dict(csrf=at,id=video,revision=2,title='Outro vídeo',url='https://youtu.be/aqz-KE-bpKQ'))[0]==303,'Substituir vídeo')
        check(progress(member,subject)['video']==(0,1),'Trocar conteúdo do vídeo reinicia marcação')
        mark('video',video)
        check(admin.request('/videos/excluir',dict(csrf=at,id=video,revision=3,confirm=1))[0]==303,'Excluir vídeo estudado')
        check(progress(member,subject)['video']==(0,0),'Excluir vídeo atualiza totais')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_video_study WHERE video_id=?',(video,)).fetchone()[0]==0,'FK limpa marcações de vídeo removido')
        mark('video',video,expected=404)
        check(admin.request('/materias/excluir',dict(csrf=at,id=second,revision=1,confirm=1))[0]==303,'Excluir matéria mantém arquivo disponível sem associação')
        check(member.request('/materiais/'+str(files[0]))[0]==200,'Arquivo sem matéria continua estudável')
        mark('file',files[0])
        check(b'class="study-badge"' in member.request('/materiais/sem-materia')[2],'Estudo de arquivo sem matéria identificado')
    paths=['portal/src/study.php','portal/src/documents.php','portal/src/videos.php','portal/src/views.php','portal/src/migrations.php','portal/schema.sql']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/study-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Estudo:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
