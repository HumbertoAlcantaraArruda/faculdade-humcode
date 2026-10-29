"""Recorrência finita: calendário, escopos, exceções, cópias e isolamento HTTP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

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
    with test_server(Path(args.php)) as (base, db, _, _, _, _, _):
        member, admin, twin = [portal.Client(base) for _ in range(3)]
        member.login('aluno', portal.MEMBER_PASSWORD)
        twin.login('aluno', portal.MEMBER_PASSWORD)
        admin.login()
        mt, at, tt = member.csrf(), admin.csrf(), twin.csrf()
        baseline = db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        owner = db.execute("SELECT id FROM hc_portal_users WHERE login = 'aluno'").fetchone()[0]
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        start = str(today + timedelta(days=10))
        defaults = dict(csrf=mt, title='Série teste', description='Descrição', event_date=start, all_day='0', starts_at='10:00', ends_at='11:00', priority='media', category='curso', subject_id='', event_id='')
        def record(kind, identifier):
            cursor = db.execute('SELECT * FROM hc_portal_' + ('events' if kind == 'event' else 'tasks') + ' WHERE id = ?', (identifier,))
            row = cursor.fetchone()
            return dict(zip([c[0] for c in cursor.description], row)) if row else None
        def members(kind, series):
            column = 'event_date' if kind == 'event' else 'task_date'
            return db.execute('SELECT id, ' + column + ', recurrence_exception FROM hc_portal_' + ('events' if kind == 'event' else 'tasks') + ' WHERE recurrence_id = ? ORDER BY occurrence_date, id', (series,)).fetchall()
        def create(kind='event', expected=303, client=member, **options):
            values = dict(defaults, **options)
            if values.get('recurrence') in ['weekly', 'monthly']:
                values.setdefault('recurrence_key', secrets.token_hex(16))
                values.setdefault('recurrence_interval', 1)
                values.setdefault('recurrence_count', 3)
            response = client.request('/agenda/' + ('eventos' if kind == 'event' else 'tarefas') + '/criar', values)
            check(response[0] == expected, 'Criar ' + kind + ' HTTP ' + str(expected) + ': ' + str({k:v for k,v in options.items() if k not in ['csrf','recurrence_key']}))
            return int(response[1]['Location'].rsplit('/', 1)[1]) if expected == 303 else None
        def update(kind, identifier, expected=303, client=member, **options):
            item = record(kind, identifier)
            values = {k:item[k] if item[k] is not None else '' for k in ['title','description','priority','category','subject_id','starts_at','ends_at','revision']}
            values.update(csrf=mt, id=identifier, event_date=item['event_date' if kind == 'event' else 'task_date'], all_day='1' if item['starts_at'] is None else '0')
            if kind == 'task': values['event_id'] = item['event_id'] or ''
            if item['recurrence_id'] is not None:
                values['recurrence_revision'] = db.execute('SELECT revision FROM hc_portal_recurrences WHERE id = ?', (item['recurrence_id'],)).fetchone()[0]
            values.update(options)
            response = client.request('/agenda/' + ('eventos' if kind == 'event' else 'tarefas') + '/atualizar', values)
            check(response[0] == expected, 'Editar ' + kind + ' HTTP ' + str(expected) + ': ' + str({k:v for k,v in options.items() if k != 'csrf'}))
        def delete(kind, identifier, expected=303, client=member, **options):
            item = record(kind, identifier)
            values = dict(csrf=mt, id=identifier, revision=item['revision'], confirm=1)
            if item['recurrence_id'] is not None: values['recurrence_revision'] = db.execute('SELECT revision FROM hc_portal_recurrences WHERE id = ?', (item['recurrence_id'],)).fetchone()[0]
            response = client.request('/agenda/' + ('eventos' if kind == 'event' else 'tarefas') + '/excluir', dict(values, **options))
            check(response[0] == expected, 'Excluir ' + kind + ' HTTP ' + str(expected) + ': ' + str({k:v for k,v in options.items() if k != 'csrf'}))
        # Validation and bounded generation.
        for options in [dict(recurrence='daily'), dict(recurrence='monthly',recurrence_count=1),dict(recurrence='monthly',recurrence_count=121),dict(recurrence='monthly',recurrence_interval=0),dict(recurrence='monthly',recurrence_interval=13),dict(recurrence='monthly',recurrence_count='abc'),dict(recurrence='monthly',recurrence_key='bad'),dict(recurrence='weekly'),dict(recurrence='weekly',**{'recurrence_days[0]':'7'}),dict(recurrence='weekly',**{'recurrence_days[0]':'1','recurrence_days[1]':'1'}),dict(recurrence='monthly',event_date='9999-12-31')]:
            create(expected=400, **options)
        check(db.execute('SELECT COUNT(*) FROM hc_portal_recurrences').fetchone()[0] == 0, 'Dados inválidos não criam séries parciais')
        rollback_parent = create(event_date='2032-01-31')
        rollback_task = create('task', event_id=rollback_parent, event_date='9999-12-31')
        update('event',rollback_parent, expected=400, recurrence='monthly',recurrence_interval=1,recurrence_count=3,recurrence_key=secrets.token_hex(16))
        check(record('event',rollback_parent)['recurrence_id'] is None and record('task',rollback_task)['recurrence_id'] is None, 'Erro no deslocamento de uma tarefa desfaz toda a criação da série')
        create(expected=403, recurrence='monthly', csrf='bad')
        avulso = create(title='Evento avulso')
        check(record('event', avulso)['recurrence_id'] is None, 'Compromissos avulsos continuam avulsos')
        leap = create(event_date='2032-01-31', recurrence='monthly')
        leap_series = record('event', leap)['recurrence_id']
        check([r[1] for r in members('event', leap_series)] == ['2032-01-31','2032-02-29','2032-03-31'], 'Mensal usa último dia em fevereiro bissexto e retoma dia 31 em março')
        non_leap = create(event_date='2031-01-31', recurrence='monthly', recurrence_interval=1)
        check([r[1] for r in members('event',record('event',non_leap)['recurrence_id'])] == ['2031-01-31','2031-02-28','2031-03-31'], 'Mensal em ano comum não deriva para dia 28 nos meses seguintes')
        interval = create(event_date='2030-12-30', recurrence='weekly', recurrence_interval=2, recurrence_count=4, **{'recurrence_days[0]':'1','recurrence_days[1]':'3'})
        check([r[1] for r in members('event',record('event',interval)['recurrence_id'])] == ['2030-12-30','2031-01-01','2031-01-13','2031-01-15'], 'Semanal com dois dias e intervalo de duas semanas atravessa o ano')
        monthly_interval = create(event_date='2031-12-31', recurrence='monthly', recurrence_interval=2)
        check([r[1] for r in members('event',record('event',monthly_interval)['recurrence_id'])] == ['2031-12-31','2032-02-29','2032-04-30'], 'Intervalo mensal usa a data original e atravessa o ano')
        large = create('task', event_date=start, recurrence='monthly', recurrence_count=120)
        check(len(members('task',record('task',large)['recurrence_id'])) == 120, 'Limite finito gera exatamente 120 ocorrências')
        check(len({r[1] for r in members('task',record('task',large)['recurrence_id'])}) == 120, 'Ocorrências geradas têm datas únicas')
        # Replay and independent concurrent forms for the same operation.
        key = secrets.token_hex(16)
        values = dict(defaults, recurrence='monthly', recurrence_interval=1, recurrence_count=4, recurrence_key=key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.request, '/agenda/eventos/criar', dict(values, csrf=token)) for client, token in [(member,mt),(twin,tt)]]
            responses = [future.result() for future in futures]
        check(all(r[0] == 303 for r in responses) and responses[0][1]['Location'] == responses[1][1]['Location'], 'Envio concorrente com mesma chave retorna a mesma ocorrência')
        same = int(responses[0][1]['Location'].rsplit('/',1)[1])
        same_series = record('event',same)['recurrence_id']
        check(len(members('event',same_series)) == 4, 'Envio concorrente não duplica a série')
        for _ in range(3): member.request('/agenda?mes=' + start[:7]); member.request('/meu-dia'); member.request('/notificacoes')
        check(len(members('event',same_series)) == 4, 'Acessos repetidos não geram novas ocorrências')
        try:
            db.execute('UPDATE hc_portal_events SET occurrence_date = ? WHERE id = ?', (members('event',same_series)[0][1], members('event',same_series)[1][0]))
            check(False, 'Índice de unicidade deveria rejeitar cópia duplicada')
        except sqlite3.IntegrityError:
            db.rollback(); check(True, 'Unicidade da ocorrência também é garantida pelo banco')
        # Exceptions and scope isolation.
        ids = [row[0] for row in members('event',same_series)]
        update('event',ids[1], title='Exceção individual', recurrence_scope='this')
        check(record('event',ids[1])['recurrence_exception'] == 1 and record('event',ids[0])['title'] == 'Série teste', 'Alterar uma ocorrência preserva as demais e marca exceção')
        update('event',ids[0], title='Toda série', recurrence_scope='all')
        check([record('event',i)['title'] for i in ids] == ['Toda série','Exceção individual','Toda série','Toda série'], 'Edição da série preserva exceção individual')
        update('event',ids[2], title='Esta e próximas', recurrence_scope='following')
        check(record('event',ids[0])['title'] == 'Toda série' and record('event',ids[2])['title'] == record('event',ids[3])['title'] == 'Esta e próximas', 'Edição desta e próximas não altera anteriores')
        update('event',ids[2], expected=409, recurrence_scope='all', recurrence_revision=1)
        update('event',ids[2], expected=409, revision=1)
        update('event',ids[2], expected=404, client=admin, csrf=at, recurrence_scope='all')
        update('event',ids[2], expected=400, recurrence_scope='invalid')
        delete('event',ids[3], expected=404, client=admin, csrf=at, recurrence_scope='all')
        delete('event',ids[3], expected=403, csrf='bad', recurrence_scope='all')
        delete('event',ids[3], expected=400, confirm=0, recurrence_scope='all')
        check(b'Exce' in member.request('/agenda/eventos/' + str(ids[1]))[2] and b'Recorrente' in member.request('/agenda?mes=' + start[:7])[2], 'Detalhe e agenda identificam recorrência e exceção')
        check(b'Exce' not in admin.request('/agenda?mes=' + start[:7])[2], 'Administrador não vê série de outra conta')
        # Original tasks are retained; subsequent copies start pending and keep offsets.
        parent = create(title='Evento com tarefas')
        child = create('task', title='Preparação', event_id=parent, event_date=str(today + timedelta(days=8)), starts_at='08:00', ends_at='09:00')
        done = dict(csrf=mt, id=child, revision=1, complete=1)
        check(member.request('/agenda/tarefas/estado',done)[0] == 303, 'Tarefa de origem pode estar concluída antes de repetir evento')
        update('event',parent, recurrence='monthly', recurrence_interval=1, recurrence_count=3, recurrence_key=secrets.token_hex(16))
        parent_series = record('event',parent)['recurrence_id']
        copied = [record('task',row[0]) for row in members('task',parent_series)]
        events = [record('event',row[0]) for row in members('event',parent_series)]
        check(len(copied) == 3 and copied[0]['completed_at'] is not None and all(t['completed_at'] is None for t in copied[1:]), 'Repetição preserva conclusão original e novas tarefas ficam pendentes')
        check(all((datetime.fromisoformat(t['task_date'])-datetime.fromisoformat(e['event_date'])).days == -2 for t,e in zip(copied,events)), 'Tarefas conservam deslocamento de dois dias antes do evento')
        check(all(t['starts_at'] == '08:00' and t['ends_at'] == '09:00' and t['event_id'] == e['id'] for t,e in zip(copied,events)), 'Cópias conservam horários e vinculam ao próprio evento')
        added = create('task', title='Tarefa acrescentada', event_id=events[1]['id'], event_date=str(datetime.fromisoformat(events[1]['event_date']).date()+timedelta(days=1)))
        check(len(members('task',parent_series)) == 6, 'Nova tarefa de evento recorrente acompanha todas as ocorrências ainda não passadas')
        added_slot = record('task',added)['recurrence_slot']
        added_ids = db.execute('SELECT id FROM hc_portal_tasks WHERE recurrence_id = ? AND recurrence_slot = ? ORDER BY occurrence_date', (parent_series,added_slot)).fetchall()
        update('task',added, title='Tarefa na série', recurrence_scope='all')
        check(all(record('task',r[0])['title'] == 'Tarefa na série' for r in added_ids) and record('task',child)['title'] == 'Preparação', 'Editar tarefa na série altera somente seu próprio modelo')
        update('task',added, expected=400, recurrence_scope='all', event_id='')
        copied_pending = copied[1]
        check(member.request('/agenda/tarefas/estado', dict(csrf=mt,id=copied_pending['id'],revision=copied_pending['revision'],complete=1))[0] == 303, 'Uma cópia pode ser concluída isoladamente')
        update('task',copied[2]['id'], title='Somente pendentes', recurrence_scope='all')
        check(record('task',child)['title'] == record('task',copied_pending['id'])['title'] == 'Preparação' and record('task',copied[2]['id'])['title'] == 'Somente pendentes', 'Edição de várias tarefas preserva concluídas')
        # Past preservation and deletion scopes, including exceptions.
        historic = create(event_date=str(today-timedelta(days=35)), recurrence='monthly', recurrence_count=4)
        historical = members('event',record('event',historic)['recurrence_id'])
        future_ids = [row[0] for row in historical if row[1] >= str(today)]
        update('event',future_ids[0], title='Futuro atualizado', recurrence_scope='all')
        check(all(record('event',r[0])['title'] == 'Série teste' for r in historical if r[1] < str(today)), 'Edição da série preserva ocorrências passadas')
        delete('event',future_ids[0], recurrence_scope='all')
        check(all(record('event',r[0]) is not None for r in historical if r[1] < str(today)) and all(record('event',i) is None for i in future_ids), 'Excluir série preserva passado e remove futuras')
        delete('event',ids[2], recurrence_scope='following')
        check(record('event',ids[0]) is not None and record('event',ids[1]) is not None and record('event',ids[2]) is None and record('event',ids[3]) is None, 'Excluir esta e próximas preserva anteriores e exceções')
        delete('event',ids[1], recurrence_scope='this')
        check(record('event',ids[1]) is None and record('event',ids[0]) is not None, 'Excluir exceção individual não altera outra ocorrência')
        delete('event',events[1]['id'], recurrence_scope='all')
        check(all(record('event',e['id']) is None for e in events), 'Exclusão de eventos em série remove cada evento selecionado')
        check(all(record('task',t['id'])['event_id'] is None for t in copied), 'Exclusão de eventos preserva tarefas como avulsas')
        delete('task',copied[2]['id'], recurrence_scope='all')
        check(record('task',copied[2]['id']) is None and record('task',child) is not None and record('task',copied_pending['id']) is not None, 'Excluir tarefas em série preserva concluídas')
        # Independent notices, delayed access, and completed future occurrences.
        notice_task = create('task', event_date=str(today), all_day='1', recurrence='weekly', recurrence_count=3, **{'recurrence_days[0]':str((today.weekday()+1)%7)})
        notice_series = record('task',notice_task)['recurrence_id']
        notice_ids = [row[0] for row in members('task',notice_series)]
        member.request('/meu-dia'); member.request('/notificacoes')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_task_notifications WHERE task_id = ?', (notice_task,)).fetchone()[0] == 1, 'Ocorrência de hoje tem um único aviso')
        future_task = record('task',notice_ids[1])
        check(member.request('/agenda/tarefas/estado',dict(csrf=mt,id=future_task['id'],revision=1,complete=1))[0] == 303, 'Ocorrência futura pode ser concluída antes da data')
        member.request('/notificacoes')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_task_notifications WHERE task_id = ?', (future_task['id'],)).fetchone()[0] == 0, 'Ocorrência futura concluída não gera aviso')
        check(record('task',notice_ids[2])['completed_at'] is None, 'Concluir uma ocorrência não conclui a próxima')
        db.execute('UPDATE hc_portal_tasks SET notify_on = ? WHERE id IN (?, ?)', (str(today-timedelta(days=1)),notice_ids[1],notice_ids[2])); db.commit()
        member.request('/notificacoes'); member.request('/notificacoes')
        check(db.execute('SELECT COUNT(*) FROM hc_portal_task_notifications WHERE task_id = ?', (notice_ids[2],)).fetchone()[0] == 1, 'Acesso tardio gera apenas um aviso por ocorrência pendente')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall() == baseline, 'Recorrência não altera materiais compartilhados')
        check(member.request('/agenda?mes=2040-01')[0] == 200, 'Navegação distante não requer cron nem geração adicional')
    paths = ['portal/src/recurrence.php','portal/src/events.php','portal/src/tasks.php','portal/src/migrations.php','portal/schema.sql','portal/migrations/008-agenda-recurrence.sql']
    report = dict(status='verified', checks=len(checks), results=checks, tested_at=datetime.now(timezone.utc).isoformat(), sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/recurrence-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Recorrência:',len(checks),'verificações aprovadas')


if __name__ == '__main__': main()
