"""Anexos de anotações: limite de 3, formatos, 10 MB, dono, substituição e exclusão do arquivo físico."""
import argparse
from datetime import datetime, timezone
import hashlib,io,json,struct,zipfile,zlib
from pathlib import Path
import test_portal as portal
from test_runtime_fixes import test_server

PDF=b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'
JPG=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9'
HTML=b'<!doctype html><html><body>Arquivo da nota</body></html>'
def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
PNG=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00'))+chunk(b'IEND',b'')
def docx():
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        archive.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    return buffer.getvalue()
DOCX=docx()
PDF_TYPE,PNG_TYPE,JPG_TYPE,HTML_TYPE,DOCX_TYPE='application/pdf','image/png','image/jpeg','text/html','application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--php',required=True); args=parser.parse_args(); checks=[]
    def check(value,label):
        assert value,label
        checks.append(label)
    with test_server(Path(args.php)) as (base,db,_,storage,_,_,_):
        member,admin=portal.Client(base),portal.Client(base); member.login('aluno',portal.MEMBER_PASSWORD); admin.login(); mt,at=member.csrf(),admin.csrf()
        owner=db.execute("SELECT id FROM hc_portal_users WHERE login='aluno'").fetchone()[0]
        def stored(): return sorted(p.name for p in Path(storage).glob('*.bin'))
        def post(route,client=member,token=None,files=(),field='attachments[]',**fields):
            return client.multipart(route,dict(dict(csrf=token or (mt if client is member else at),title='Nota com arquivos',body='Texto',subject_id=''),**fields),files,field)
        def rows(note): return db.execute('SELECT id,original_name,stored_path,extension,size,sha256 FROM hc_portal_note_files WHERE note_id=? ORDER BY id',(note,)).fetchall()
        before=stored()
        # criação com os três primeiros formatos
        response=post('/anotacoes/criar',files=[('aula.pdf',PDF_TYPE,PDF),('foto.png',PNG_TYPE,PNG),('texto.docx',DOCX_TYPE,DOCX)])
        check(response[0]==303,'Criar nota com 3 arquivos'); note=int(response[1]['Location'].rsplit('/',1)[1]); files=rows(note)
        check(len(files)==3 and [f[3] for f in files]==['pdf','png','docx'],'Três anexos registrados com extensão')
        check(all(f[5]==hashlib.sha256(c).hexdigest() and f[4]==len(c) for f,c in zip(files,[PDF,PNG,DOCX])),'Tamanho e hash dos anexos conferem')
        check(len(stored())==len(before)+3 and all(f[2] in stored() and f[2].endswith('.bin') and len(f[2])==52 for f in files),'Arquivos gravados com nome aleatório')
        page=member.request('/anotacoes/'+str(note))[2]
        check(b'aula.pdf' in page and b'foto.png' in page and b'texto.docx' in page and b'id="note-files-heading">Arquivos</h2>' in page,'Página da nota lista os anexos')
        edit=member.request('/anotacoes/'+str(note)+'/editar')[2]
        check(edit.count(b'action="/anotacoes/arquivos/atualizar"')==3 and edit.count(b'action="/anotacoes/arquivos/excluir"')==3 and b'action="/anotacoes/arquivos/adicionar"' in edit and b'name="return" value="edit"' in edit and b'name="remove_files[]"' not in edit,'Edição usa lápis e lixo por arquivo e adicionar')
        back=member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=note,**{'return':'edit'}),[],'attachments[]')
        check(back[0]==400,'Adicionar sem arquivo pela edição é recusado')
        # leitura pelo dono
        pdf,png,docx_row=files
        opened=member.request('/anotacoes/arquivo/'+str(pdf[0]))
        check(opened[0]==200 and opened[2]==PDF and opened[1]['Content-Type']=='application/pdf' and opened[1]['Content-Disposition'].startswith('inline'),'Dono abre PDF em linha')
        check(opened[1].get('X-Content-Type-Options')=='nosniff','Entrega com nosniff')
        got=member.request('/anotacoes/arquivo/'+str(docx_row[0])+'/download')
        check(got[0]==200 and got[2]==DOCX and got[1]['Content-Disposition'].startswith('attachment') and got[1]['Content-Type']=='application/octet-stream','Dono baixa DOCX')
        check(member.request('/anotacoes/arquivo/'+str(docx_row[0]))[0]==415,'DOCX não abre em linha')
        # privacidade
        for route in ['/anotacoes/arquivo/'+str(pdf[0]),'/anotacoes/arquivo/'+str(pdf[0])+'/download']:
            check(admin.request(route)[0]==404,'Outro usuário não acessa '+route)
        check(portal.Client(base).request('/anotacoes/arquivo/'+str(pdf[0]))[0]==303,'Anexo exige autenticação')
        check(member.request('/anotacoes/arquivo/999999')[0]==404,'Anexo inexistente retorna 404')
        check(member.request('/anotacoes/arquivo/'+str(pdf[0]),dict(csrf=mt))[0]==405,'Anexo só aceita GET')
        # limite de três
        revision=db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(note,)).fetchone()[0]
        update=dict(id=note,revision=revision,title='Nota com arquivos',body='Texto',subject_id='')
        snapshot=stored()
        check(post('/anotacoes/atualizar',files=[('quarto.pdf',PDF_TYPE,PDF)],**update)[0]==400,'Quarto arquivo é recusado')
        check(len(rows(note))==3 and stored()==snapshot,'Recusa não grava arquivo nem registro')
        check(db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(note,)).fetchone()[0]==revision,'Recusa não altera a nota')
        check(post('/anotacoes/criar',files=[(n+'.pdf',PDF_TYPE,PDF) for n in 'abcd'])[0]==400,'Criar com 4 arquivos é recusado')
        check(db.execute("SELECT COUNT(*) FROM hc_portal_notes WHERE user_id=? AND title='Nota com arquivos'",(owner,)).fetchone()[0]==1 and stored()==snapshot,'Criação recusada não deixa nota nem arquivo')
        # formatos e conteúdo
        before_count=db.execute('SELECT COUNT(*) FROM hc_portal_notes').fetchone()[0]
        for name,mime,content,label in [('malware.exe','application/octet-stream',b'MZ\x90\x00','EXE'),('texto.txt','text/plain',b'texto','TXT'),('pacote.zip','application/zip',DOCX,'ZIP'),('pagina.htm','text/html',HTML,'HTM'),('planilha.xlsx',DOCX_TYPE,DOCX,'XLSX'),('falso.pdf',PDF_TYPE,PNG,'PDF com conteúdo de PNG'),('falso.png',PNG_TYPE,HTML,'PNG com conteúdo HTML'),('vazio.pdf',PDF_TYPE,b'','arquivo vazio')]:
            check(post('/anotacoes/criar',files=[(name,mime,content)])[0]==400,'Recusa '+label)
        check(db.execute('SELECT COUNT(*) FROM hc_portal_notes').fetchone()[0]==before_count and stored()==snapshot,'Arquivos inválidos não criam nota nem gravam')
        limit=10*1024*1024
        check(post('/anotacoes/criar',files=[('grande.pdf',PDF_TYPE,PDF+b'0'*(limit-len(PDF)+1))])[0]==400,'Arquivo acima de 10 MB é recusado')
        exact=post('/anotacoes/criar',files=[('limite.pdf',PDF_TYPE,PDF+b'0'*(limit-len(PDF)))])
        check(exact[0]==303,'Arquivo de exatamente 10 MB é aceito'); exact_note=int(exact[1]['Location'].rsplit('/',1)[1])
        check(rows(exact_note)[0][4]==limit,'Tamanho de 10 MB registrado')
        for ext,mime,content in [('jpg',JPG_TYPE,JPG),('jpeg',JPG_TYPE,JPG),('html',HTML_TYPE,HTML)]:
            made=post('/anotacoes/criar',files=[('arquivo.'+ext,mime,content)]); check(made[0]==303,'Aceita '+ext.upper())
        html_row=rows(int(made[1]['Location'].rsplit('/',1)[1]))[0]
        served=member.request('/anotacoes/arquivo/'+str(html_row[0]))
        check(served[0]==200 and 'sandbox' in served[1]['Content-Security-Policy'] and 'allow-same-origin' not in served[1]['Content-Security-Policy'],'HTML abre isolado, sem a origem do portal')
        check(member.request('/anotacoes/arquivo/'+str(html_row[0])+'/download')[1]['Content-Disposition'].startswith('attachment'),'HTML também baixa')
        # substituição e remoção na mesma gravação
        revision=db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(note,)).fetchone()[0]
        old_paths={f[0]:f[2] for f in files}
        change=post('/anotacoes/atualizar',files=[('novo.pdf',PDF_TYPE,PDF+b'novo')],field='replace['+str(pdf[0])+']',**dict(update,revision=revision))
        check(change[0]==303,'Substituir arquivo')
        row=db.execute('SELECT original_name,stored_path,size FROM hc_portal_note_files WHERE id=?',(pdf[0],)).fetchone()
        check(row[0]=='novo.pdf' and row[2]==len(PDF)+4 and row[1]!=old_paths[pdf[0]],'Registro do arquivo substituído')
        check(old_paths[pdf[0]] not in stored() and row[1] in stored(),'Arquivo antigo apagado e novo gravado')
        check(member.request('/anotacoes/arquivo/'+str(pdf[0]))[2]==PDF+b'novo','Download entrega o conteúdo novo')
        check(db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(note,)).fetchone()[0]==revision+1,'Substituição incrementa revisão da nota')
        revision+=1
        check(post('/anotacoes/atualizar',files=[('cheio.pdf',PDF_TYPE,PDF)],**dict(update,revision=revision))[0]==400,'Com 3 arquivos, adicionar outro continua recusado')
        removal=member.request('/anotacoes/atualizar',dict(update,csrf=mt,revision=revision,**{'remove_files[]':str(png[0])}))
        check(removal[0]==303,'Remover arquivo'); revision+=1
        check([f[0] for f in rows(note)]==[pdf[0],docx_row[0]] and png[2] not in stored(),'Registro e arquivo físico removidos')
        check(member.request('/anotacoes/arquivo/'+str(png[0]))[0]==404,'Arquivo removido não abre mais')
        swap=post('/anotacoes/atualizar',files=[('troca.png',PNG_TYPE,PNG),('outro.jpg',JPG_TYPE,JPG)],**dict(update,revision=revision))
        check(swap[0]==400,'Adicionar 2 com 2 existentes excede 3');
        swap=post('/anotacoes/atualizar',files=[('troca.png',PNG_TYPE,PNG)],**dict(update,revision=revision))
        check(swap[0]==303 and len(rows(note))==3,'Adicionar 1 com 2 existentes'); revision+=1
        # remover e adicionar na mesma gravação respeita o limite
        ids=[f[0] for f in rows(note)]
        both=post('/anotacoes/atualizar',files=[('um.pdf',PDF_TYPE,PDF),('dois.pdf',PDF_TYPE,PDF)],**dict(update,revision=revision,**{'remove_files[]':str(ids[0])}))
        check(both[0]==400,'Remover 1 e adicionar 2 com 3 existentes excede o limite')
        both=post('/anotacoes/atualizar',files=[('um.pdf',PDF_TYPE,PDF)],**dict(update,revision=revision,**{'remove_files[]':str(ids[0])}))
        check(both[0]==303 and len(rows(note))==3 and ids[0] not in [f[0] for f in rows(note)],'Remover 1 e adicionar 1 mantém 3'); revision+=1
        # substituir e remover o mesmo arquivo, arquivo alheio e dados estruturados
        ids=[f[0] for f in rows(note)]
        check(post('/anotacoes/atualizar',files=[('x.pdf',PDF_TYPE,PDF)],field='replace['+str(ids[0])+']',**dict(update,revision=revision,**{'remove_files[]':str(ids[0])}))[0]==400,'Substituir e remover o mesmo arquivo é recusado')
        foreign=rows(exact_note)[0][0]
        check(member.request('/anotacoes/atualizar',dict(update,csrf=mt,revision=revision,**{'remove_files[]':str(foreign)}))[0]==400 and rows(exact_note),'Não remove arquivo de outra nota')
        check(post('/anotacoes/atualizar',files=[('x.pdf',PDF_TYPE,PDF)],field='replace['+str(foreign)+']',**dict(update,revision=revision))[0]==400,'Não substitui arquivo de outra nota')
        check(member.request('/anotacoes/atualizar',dict(update,csrf=mt,revision=revision,remove_files='abc'))[0]==400,'Remoção estruturada é recusada')
        check(post('/anotacoes/atualizar',files=[('x.pdf',PDF_TYPE,PDF)],csrf='invalido',**dict(update,revision=revision))[0]==403,'Envio exige CSRF')
        check(post('/anotacoes/atualizar',files=[('x.pdf',PDF_TYPE,PDF)],**dict(update,revision=revision-1))[0]==409,'Formulário antigo não altera anexos')
        # outro usuário não mexe nos anexos da nota
        check(post('/anotacoes/atualizar',client=admin,token=at,files=[('x.pdf',PDF_TYPE,PDF)],**dict(update,revision=revision))[0]==404,'Administrador não anexa em nota alheia')
        check(admin.request('/anotacoes/atualizar',dict(update,csrf=at,revision=revision,**{'remove_files[]':str(ids[0])}))[0]==404 and len(rows(note))==3,'Administrador não remove anexo alheio')
        # excluir a nota apaga arquivos
        paths=[f[2] for f in rows(note)]
        check(all(p in stored() for p in paths),'Arquivos existem antes da exclusão')
        check(member.request('/anotacoes/excluir',dict(csrf=mt,id=note,revision=revision,confirm=1))[0]==303,'Excluir nota com anexos')
        check(not rows(note) and not any(p in stored() for p in paths),'Exclusão apaga registros e arquivos físicos')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_files WHERE stored_path IN (SELECT stored_path FROM hc_portal_note_files)').fetchone()[0]==0,'Anexos de notas não entram na biblioteca')
        # substituir e excluir um único arquivo pela página da anotação
        single=post('/anotacoes/criar',files=[('um.pdf',PDF_TYPE,PDF),('dois.png',PNG_TYPE,PNG)],title='Nota arquivos unitários'); one=int(single[1]['Location'].rsplit('/',1)[1]); first,second=rows(one)
        page=member.request('/anotacoes/'+str(one))[2]
        check(page.count(b'action="/anotacoes/arquivos/atualizar"')==2 and page.count(b'action="/anotacoes/arquivos/excluir"')==2,'Cada arquivo tem botões de substituir e excluir')
        rev=db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(one,)).fetchone()[0]
        replaced=member.multipart('/anotacoes/arquivos/atualizar',dict(csrf=mt,id=first[0]),[('novo.html',HTML_TYPE,b'<p>novo</p>')],'file')
        now=rows(one)
        check(replaced[0]==303 and len(now)==2 and now[0][0]==first[0] and now[0][1]=='novo.html' and now[0][3]=='html' and now[1]==second,'Substituir troca só o arquivo escolhido')
        check(first[2] not in stored() and now[0][2] in stored(),'Substituição apaga o arquivo físico antigo')
        check(db.execute('SELECT revision FROM hc_portal_notes WHERE id=?',(one,)).fetchone()[0]==rev+1,'Substituição atualiza a revisão da nota')
        check(member.multipart('/anotacoes/arquivos/atualizar',dict(csrf=mt,id=first[0]),[('x.exe','application/octet-stream',b'MZ')],'file')[0]==400 and rows(one)==now,'Substituição recusa extensão inválida')
        check(member.multipart('/anotacoes/arquivos/atualizar',dict(csrf=mt,id=first[0]),[],'file')[0]==400,'Substituição exige arquivo')
        check(admin.multipart('/anotacoes/arquivos/atualizar',dict(csrf=at,id=first[0]),[('x.html',HTML_TYPE,b'x')],'file')[0]==404 and rows(one)==now,'Outro usuário não substitui arquivo alheio')
        check(member.request('/anotacoes/arquivos/excluir',dict(csrf=mt,id=second[0]))[0]==400 and len(rows(one))==2,'Excluir arquivo exige confirmação')
        check(admin.request('/anotacoes/arquivos/excluir',dict(csrf=at,id=second[0],confirm=1))[0]==404 and len(rows(one))==2,'Outro usuário não exclui arquivo alheio')
        check(member.request('/anotacoes/arquivos/excluir',dict(csrf=mt,id=second[0],confirm=1))[0]==303 and [r[0] for r in rows(one)]==[first[0]],'Excluir remove só o arquivo escolhido')
        check(second[2] not in stored(),'Exclusão apaga o arquivo físico')
        check(member.request('/anotacoes/arquivos/excluir',dict(csrf=mt,id=first[0],confirm=1))[0]==303 and not rows(one),'Excluir o último arquivo deixa a nota sem anexos')
        check(member.request('/anotacoes/arquivos/excluir',dict(id=first[0],confirm=1))[0] in (400,403),'Excluir arquivo exige token CSRF')
        # adicionar arquivos pela página da anotação
        empty=post('/anotacoes/criar',title='Nota para adicionar'); added=int(empty[1]['Location'].rsplit('/',1)[1]); before_add=stored()
        check(b'action="/anotacoes/arquivos/adicionar"' in member.request('/anotacoes/'+str(added))[2] and b'Nenhum arquivo.' in member.request('/anotacoes/'+str(added))[2],'Nota sem arquivos oferece adicionar')
        got=member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[('um.pdf',PDF_TYPE,PDF),('dois.png',PNG_TYPE,PNG)],'attachments[]')
        check(got[0]==303 and [r[1] for r in rows(added)]==['um.pdf','dois.png'] and len(stored())==len(before_add)+2,'Adicionar grava dois arquivos')
        snap=stored()
        check(member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[('a.pdf',PDF_TYPE,PDF),('b.pdf',PDF_TYPE,PDF)],'attachments[]')[0]==400 and len(rows(added))==2 and stored()==snap,'Adicionar acima do limite de três é recusado sem gravar')
        check(member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[('x.exe','application/octet-stream',b'MZ')],'attachments[]')[0]==400 and len(rows(added))==2,'Adicionar recusa extensão inválida')
        check(member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[],'attachments[]')[0]==400,'Adicionar exige ao menos um arquivo')
        check(admin.multipart('/anotacoes/arquivos/adicionar',dict(csrf=at,note_id=added),[('a.pdf',PDF_TYPE,PDF)],'attachments[]')[0]==404 and len(rows(added))==2,'Outro usuário não adiciona em nota alheia')
        check(member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[('tres.html',HTML_TYPE,b'<p>3</p>')],'attachments[]')[0]==303 and len(rows(added))==3,'Adicionar completa o limite de três')
        check(member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=added),[('quatro.html',HTML_TYPE,b'<p>4</p>')],'attachments[]')[0]==400 and len(rows(added))==3,'Quarto arquivo pela página é recusado')
        # ações vindas da página de edição voltam para a edição
        back_note=int(post('/anotacoes/criar',files=[('a.pdf',PDF_TYPE,PDF)],title='Nota volta edição')[1]['Location'].rsplit('/',1)[1]); only=rows(back_note)[0]
        goes=member.multipart('/anotacoes/arquivos/adicionar',dict(csrf=mt,note_id=back_note,**{'return':'edit'}),[('b.html',HTML_TYPE,b'<p>b</p>')],'attachments[]')
        check(goes[0]==303 and goes[1]['Location'].endswith('/anotacoes/'+str(back_note)+'/editar'),'Adicionar pela edição volta para a edição')
        goes=member.multipart('/anotacoes/arquivos/atualizar',dict(csrf=mt,id=only[0],**{'return':'edit'}),[('c.html',HTML_TYPE,b'<p>c</p>')],'file')
        check(goes[0]==303 and goes[1]['Location'].endswith('/editar'),'Substituir pela edição volta para a edição')
        goes=member.request('/anotacoes/arquivos/excluir',dict(csrf=mt,id=only[0],confirm=1,**{'return':'edit'}))
        check(goes[0]==303 and goes[1]['Location'].endswith('/editar'),'Excluir pela edição volta para a edição')
        goes=member.request('/anotacoes/arquivos/excluir',dict(csrf=mt,id=rows(back_note)[0][0],confirm=1,**{'return':'outro'}))
        check(goes[0]==303 and goes[1]['Location'].endswith('/anotacoes/'+str(back_note)),'Destino de retorno desconhecido cai na página da anotação')

        # detalhe em modal: só o fragmento, e retorno seguro para a lista
        mnote = int(post('/anotacoes/criar', files=[('m.pdf', PDF_TYPE, PDF)], title='Nota modal')[1]['Location'].rsplit('/', 1)[1])
        frag = member.request('/anotacoes/' + str(mnote) + '?modal=1')
        check(frag[0] == 200 and b'data-detail-fragment' in frag[2] and b'<html' not in frag[2] and b'back-link' not in frag[2] and b'name="return" value="modal"' in frag[2], 'Detalhe da nota em modal devolve só o fragmento')
        full = member.request('/anotacoes/' + str(mnote))[2]
        check(b'<html' in full and b'back-link' in full and b'data-detail-fragment' not in full, 'Página completa da nota continua disponível')
        check(admin.request('/anotacoes/' + str(mnote) + '?modal=1')[0] == 404, 'Fragmento da nota não vaza para outro usuário')
        check(portal.Client(base).request('/anotacoes/' + str(mnote) + '?modal=1')[0] == 303, 'Fragmento da nota exige autenticação')
        goes = member.multipart('/anotacoes/arquivos/adicionar', dict(csrf=mt, note_id=mnote, **{'return': '/anotacoes?subject_id=0'}), [('n.html', HTML_TYPE, b'<p>n</p>')], 'attachments[]')
        check(goes[0] == 303 and goes[1]['Location'] == '/anotacoes?subject_id=0#abrir-nota-' + str(mnote), 'Ação no modal volta para a lista e reabre a anotação')
        crlf = chr(13) + chr(10)
        for bad in ['//evil.example/x', 'https://evil.example/x', '/' + chr(92) + 'evil.example', '/a#b', 'javascript:alert(1)', '/ok' + crlf + 'X-Evil: 1']:
            goes = member.multipart('/anotacoes/arquivos/atualizar', dict(csrf=mt, id=rows(mnote)[0][0], **{'return': bad}), [('r.html', HTML_TYPE, b'<p>r</p>')], 'file')
            check(goes[0] == 303 and 'evil' not in goes[1]['Location'] and goes[1]['Location'].endswith('/anotacoes/' + str(mnote)), 'Retorno inseguro é ignorado: ' + bad.replace(crlf, ' '))
    paths=['portal/src/note-files.php','portal/src/notes.php','portal/src/migrations.php','portal/schema.sql','portal/migrations/013-note-files.sql']
    report=dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/note-files-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Anexos de anotações:',len(checks),'verificações aprovadas')


if __name__=='__main__': main()
