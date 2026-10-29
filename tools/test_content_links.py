"""Vínculos privados: tipos, recorrência, exclusão, concorrência e revisões."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets

import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    args = parser.parse_args()
    checks = []
    def check(value, label):
        assert value, label
        checks.append(label)
    with test_server(Path(args.php)) as (base, db, _, storage, _, _, _):
        member, admin, twin = [portal.Client(base) for _ in range(3)]
        member.login('aluno', portal.MEMBER_PASSWORD)
        twin.login('aluno', portal.MEMBER_PASSWORD)
        admin.login()
        mt, at, tt = member.csrf(), admin.csrf(), twin.csrf()
        baseline = db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        subjects = [r[0] for r in db.execute('SELECT id FROM hc_portal_subjects LIMIT 2')]
        file = db.execute('SELECT id FROM hc_portal_files WHERE subject_id = ? LIMIT 1', (subjects[1],)).fetchone()[0]
        db.execute('INSERT INTO hc_portal_videos (subject_id,title,youtube_id) VALUES (?, ?, ?)', (subjects[1], 'Vídeo de estudo', 'dQw4w9WgXcQ'))
        video = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('INSERT INTO hc_portal_folders (subject_id,name) VALUES (?, ?)', (subjects[1], 'Pasta de estudo'))
        folder = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.commit()
        defaults = dict(csrf=mt, title='Compromisso com conteúdo', description='', event_date='2032-01-31', all_day='1', priority='media', category='curso', subject_id=subjects[0], event_id='')
        def create(kind='event', **options):
            response = member.request('/agenda/' + ('eventos' if kind == 'event' else 'tarefas') + '/criar', dict(defaults, **options))
            check(response[0] == 303, 'Criar compromisso ' + kind)
            return int(response[1]['Location'].rsplit('/', 1)[1])
        def item(kind, id):
            c = db.execute('SELECT * FROM hc_portal_' + kind + 's WHERE id = ?', (id,))
            return dict(zip([r[0] for r in c.description], c.fetchone()))
        def values(kind, id, type='file', content=file, action='add', **options):
            record = item(kind, id)
            data = dict(csrf=mt, kind=kind, id=id, type=type, content_id=content, action=action, revision=record['revision'])
            if record['recurrence_id']:
                data['recurrence_revision'] = db.execute('SELECT revision FROM hc_portal_recurrences WHERE id=?', (record['recurrence_id'],)).fetchone()[0]
            return dict(data, **options)
        def change(kind, id, expected=303, client=member, **options):
            response = client.request('/agenda/conteudos/alterar', values(kind, id, **options))
            check(response[0] == expected, 'Vínculo ' + kind + ' HTTP ' + str(expected) + ' ' + str({k:v for k,v in options.items() if k != 'csrf'}))
        def count(kind, type, id):
            return db.execute(f'SELECT COUNT(*) FROM hc_portal_{kind}_{type}s WHERE {kind}_id=?', (id,)).fetchone()[0]
        event = create()
        task = create('task', event_id=event)
        for type, content in [('file', file), ('video', video), ('folder', folder)]:
            change('event', event, type=type, content=content)
            check(count('event', type, event) == 1, type + ' de outra matéria vinculado')
        page = member.request('/agenda/tarefas/' + str(task))[2]
        check('Conteúdos do evento'.encode() in page and 'Vídeo de estudo'.encode() in page and 'Pasta de estudo'.encode() in page, 'Tarefa mostra os três tipos de conteúdo do evento')
        change('task', task)
        check(count('task', 'file', task) == 1, 'Tarefa conserva vínculo próprio')
        change('event', event)
        check(count('event', 'file', event) == 1, 'Repetição da operação não duplica vínculo')
        stale = values('event', event)
        change('event', event, type='video', content=video, action='remove')
        check(member.request('/agenda/conteudos/alterar', stale)[0] == 409, 'Formulário antigo não sobrescreve vínculos')
        change('event', event, type='video', content=video)
        for kind, id in [('event',event), ('task',task)]:
            check(admin.request(f'/agenda/conteudos?kind={kind}&item_id={id}')[0] == 404, 'Administrador não lê vínculos alheios ' + kind)
            change(kind, id, expected=404, client=admin, csrf=at)
        check(member.request('/agenda/conteudos/alterar')[0] == 405, 'Alteração exige POST')
        change('event', event, expected=403, csrf='invalido')
        change('event', event, expected=400, type='users')
        change('event', event, expected=404, content=999999)
        check(member.request('/agenda/conteudos?kind[]=event&item_id='+str(event))[0] == 400, 'Tipo de compromisso estruturado é recusado')
        check(member.request('/agenda/conteudos?kind=event&item_id='+str(event)+'&type=users')[0] == 400, 'Busca rejeita tipo inválido')
        check(member.request('/agenda/conteudos?kind=event&item_id='+str(event)+'&q[]=x')[0] == 400, 'Busca rejeita consulta estruturada')
        check(member.request('/agenda/conteudos?kind=event&item_id='+str(event)+'&q=sem-resultados')[0] == 200, 'Busca vazia de resultados é utilizável')
        check(b'Pr\xc3\xb3xima' in member.request('/agenda/conteudos?kind=event&item_id='+str(event))[2], 'Catálogo possui paginação')
        # Transformar evento já vinculado em série copia seus vínculos e os próprios das tarefas.
        response = member.request('/agenda/eventos/atualizar', dict(defaults, id=event, revision=item('event', event)['revision'], recurrence='monthly', recurrence_interval=1, recurrence_count=3, recurrence_key=secrets.token_hex(16)))
        check(response[0] == 303, 'Converter evento com conteúdo em recorrente')
        series = item('event', event)['recurrence_id']
        events = [r[0] for r in db.execute('SELECT id FROM hc_portal_events WHERE recurrence_id=? ORDER BY occurrence_date', (series,))]
        tasks = [r[0] for r in db.execute('SELECT id FROM hc_portal_tasks WHERE recurrence_id=? ORDER BY occurrence_date', (series,))]
        for id in events:
            check(all(count('event', type, id) == 1 for type in ['file','video','folder']), 'Ocorrência copia os três vínculos sem copiar arquivos')
        check(all(count('task','file',id) == 1 for id in tasks), 'Recorrência copia vínculos próprios das tarefas')
        change('event', events[1], action='remove')
        change('event', events[0], action='remove', recurrence_scope='all')
        check([count('event','file',id) for id in events] == [0,0,0], 'Remoção em série respeita exceção removida')
        change('event', events[0], recurrence_scope='all')
        check([count('event','file',id) for id in events] == [1,0,1], 'Adição em série preserva exceção individual')
        change('event', events[2], action='remove', recurrence_scope='following')
        check([count('event','file',id) for id in events] == [1,0,0], 'Esta e próximas preserva anteriores')
        change('event', event, expected=409, recurrence_scope='all', recurrence_revision=1)
        change('task', tasks[1], action='remove')
        check(member.request('/agenda/tarefas/estado', dict(csrf=mt,id=tasks[2],revision=item('task',tasks[2])['revision'],complete=1))[0] == 303, 'Concluir tarefa com vínculo')
        change('task', tasks[0], action='remove', recurrence_scope='all')
        check(count('task','file',tasks[2]) == 1, 'Remoção em série preserva tarefa concluída')
        db.execute('UPDATE hc_portal_events SET event_date=? WHERE id=?', ('2000-01-01',events[2])); db.commit()
        change('event', event, type='video',content=video,action='remove', recurrence_scope='all')
        check(count('event','video',events[2]) == 1, 'Alteração em série preserva ocorrência passada')
        # Duas sessões tentam adicionar o mesmo conteúdo; uma recebe revisão antiga.
        fresh = create()
        data = values('event', fresh)
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda pair: pair[0].request('/agenda/conteudos/alterar',dict(data,csrf=pair[1]))[0], [(member,mt),(twin,tt)]))
        check(sorted(statuses) == [303,409] and count('event','file',fresh) == 1, 'Duas sessões não duplicam vínculo')
        # Exclusão lógica deixa compromisso navegável e impede novo vínculo.
        check(admin.request('/materiais/excluir',dict(csrf=at,id=file,revision=1,confirm=1))[0] == 303, 'Excluir material vinculado')
        check(member.request('/agenda/eventos/'+str(event))[0] == 200, 'Arquivo removido não quebra o evento')
        check(member.request('/agenda/tarefas/'+str(task))[0] == 200, 'Arquivo removido não quebra a tarefa')
        change('event', fresh, expected=404)
        change('event', fresh, action='remove')
        check(count('event','file',fresh) == 0, 'Vínculo de arquivo removido pode ser limpo')
        check(admin.request('/videos/excluir',dict(csrf=at,id=video,revision=1,confirm=1))[0] == 303, 'Vídeo vinculado pode ser excluído')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_event_videos').fetchone()[0] == 0, 'Exclusão de vídeo remove somente seus vínculos')
        check(admin.request('/pastas/excluir',dict(csrf=at,id=folder,revision=1,confirm=1))[0] == 303, 'Pasta vinculada pode ser excluída')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_event_folders').fetchone()[0] == 0, 'Exclusão de pasta remove seus vínculos')
        check(member.request('/agenda/eventos/'+str(event))[0] == 200, 'Conteúdos excluídos preservam compromisso')
        check(len(db.execute('SELECT * FROM hc_portal_files').fetchall()) == len(baseline), 'Vincular não copia arquivos do catálogo')
    paths = ['portal/src/content-links.php','portal/src/recurrence.php','portal/src/controller.php','portal/src/bootstrap.php','portal/src/migrations.php','portal/schema.sql','portal/migrations/009-commitment-content.sql']
    report = dict(status='verified',checks=len(checks),results=checks,tested_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/content-links-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('Conteúdos:',len(checks),'verificações aprovadas')


if __name__ == '__main__': main()
