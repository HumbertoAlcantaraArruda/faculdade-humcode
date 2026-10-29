"""Tarefas privadas: vínculos, horários sobrepostos, conclusão e notificações."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
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
    with test_server(Path(args.php)) as (base, db, config, storage, manifest, scratch, env):
        member, admin, guest = [portal.Client(base) for _ in range(3)]
        member.login('aluno', portal.MEMBER_PASSWORD)
        admin.login()
        mt, at = member.csrf(), admin.csrf()
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        future, past = str(today + timedelta(days=20)), str(today - timedelta(days=1))
        baseline = db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        subject = db.execute('SELECT id FROM hc_portal_subjects ORDER BY id LIMIT 1').fetchone()[0]
        defaults = dict(csrf=mt, title='Tarefa privada estudante', description='Descrição\n<script>alert(1)</script>', event_date=str(today), category='curso', priority='urgente', all_day='0', starts_at='10:00', ends_at='11:00', subject_id=subject, event_id='')
        event_values = dict(defaults, title='Evento principal', category='faculdade', priority='baixa')
        event = int(member.request('/agenda/eventos/criar', event_values)[1]['Location'].rsplit('/', 1)[1])
        admin_event = int(admin.request('/agenda/eventos/criar', dict(event_values, csrf=at, title='Evento privado admin'))[1]['Location'].rsplit('/', 1)[1])
        def record(task):
            cursor = db.execute('SELECT * FROM hc_portal_tasks WHERE id = ?', (task,))
            item = cursor.fetchone()
            return dict(zip([c[0] for c in cursor.description], item)) if item else None
        def create(expected=303, client=member, **values):
            response = client.request('/agenda/tarefas/criar', dict(defaults, **values))
            check(response[0] == expected, 'Criar tarefa HTTP ' + str(expected) + ': ' + str(values))
            return int(response[1]['Location'].rsplit('/', 1)[1]) if expected == 303 else None
        def update(task, expected=303, client=member, **values):
            item = record(task)
            data = {k:item[k] if item[k] is not None else '' for k in ['title','description','category','priority','starts_at','ends_at','subject_id','event_id','revision']}
            data.update(id=task, csrf=mt, event_date=item['task_date'], all_day='1' if item['starts_at'] is None else '0')
            data.update(values)
            check(client.request('/agenda/tarefas/atualizar', data)[0] == expected, 'Editar tarefa HTTP ' + str(expected) + ': ' + str(values))
        def state(task, complete='1', expected=303, client=member, **values):
            data = dict(id=task, csrf=mt, revision=record(task)['revision'], complete=complete)
            data.update(values)
            response = client.request('/agenda/tarefas/estado', data)
            check(response[0] == expected, 'Estado tarefa HTTP ' + str(expected) + ': ' + str(values))
            return response
        def notice_count(task, unread=False):
            return db.execute('SELECT COUNT(*) FROM hc_portal_task_notifications WHERE task_id = ?' + (' AND read_at IS NULL' if unread else ''), (task,)).fetchone()[0]
        check(guest.request('/agenda/tarefas/nova')[0] == 303, 'Tarefas exigem login')
        check(guest.login('aluno', portal.MEMBER_PASSWORD)[1]['Location'] == '/agenda/tarefas/nova', 'Login retoma cadastro da tarefa')
        for path in ['/agenda/tarefas/criar', '/agenda/tarefas/atualizar', '/agenda/tarefas/excluir', '/agenda/tarefas/estado', '/notificacoes/tarefas/ler']:
            check(member.request(path)[0] == 405, 'POST obrigatório: ' + path)
        check(member.request('/agenda/tarefas/nova', dict(csrf=mt))[0] == 405, 'Formulário de tarefa exige GET')
        create(csrf='invalid', expected=403)
        for values in [dict(title=' '),dict(title='x'*181),dict(description='x'*5001),dict(category=''),dict(category='pessoal'),dict(priority='alta'),dict(event_date='2026-02-30'),dict(starts_at='24:00'),dict(ends_at='10:00'),dict(ends_at='09:00'),dict(all_day='2'),dict(subject_id='abc'),dict(subject_id=999999)]:
            create(expected=400, **values)
        for invalid in [admin_event, 'xyz', 999999, ['1']]:
            create(expected=404, event_id=invalid)
        task = create(event_id=event)
        duplicate_time = create(title='Mesmo horário permitido')
        whole = create(title='Dia inteiro', all_day='1', starts_at='13:00', ends_at='14:00')
        old = create(title='Registro antigo', event_date=past)
        later = create(title='Lembrete futuro', event_date=future)
        foreign = create(client=admin, csrf=at, title='Tarefa privada admin', event_id=admin_event)
        check(record(task)['starts_at'] == '10:00' and record(duplicate_time)['starts_at'] == '10:00', 'Evento e duas tarefas aceitam o mesmo horário')
        check(record(whole)['starts_at'] is None and record(whole)['ends_at'] is None, 'Dia inteiro elimina horários')
        check(record(old)['notify_on'] is None, 'Cadastro passado não gera retroativo')
        form = member.request('/agenda/tarefas/nova?event_id=' + str(event))[2].decode()
        for snippet in ['value="faculdade" selected', 'value="baixa" selected', 'name="starts_at" value="10:00"', 'value="' + str(event) + '" selected']:
            check(snippet in form, 'Formulário herda evento: ' + snippet)
        check('Evento privado admin' not in form, 'Seletor de eventos contém apenas eventos do dono')
        check(admin.request('/agenda/tarefas/nova?event_id=' + str(event))[0] == 404, 'Administrador não cria a partir do evento de outra pessoa')
        page = member.request('/agenda/tarefas/' + str(task))[2]
        check(b'&lt;script&gt;' in page and b'<script>alert' not in page, 'Descrição escapada')
        check(notice_count(task, True) == 1, 'Tarefa de hoje gera aviso pendente')
        check(notice_count(old) == notice_count(later) == 0, 'Passado cadastrado e futuro não avisam')
        for client, item, token in [(admin,task,at),(member,foreign,mt)]:
            for suffix in ['', '/editar']:
                check(client.request('/agenda/tarefas/' + str(item) + suffix)[0] == 404, 'Outra conta não acessa tarefa' + suffix)
            update(item, expected=404, client=client, csrf=token)
            state(item, expected=404, client=client, csrf=token)
            check(client.request('/agenda/tarefas/excluir', dict(id=item,csrf=token,revision=1,confirm=1))[0] == 404, 'Outra conta não exclui tarefa')
        check(b'Tarefa privada estudante' not in admin.request('/agenda')[2], 'Calendário do administrador não expõe tarefa do estudante')
        check(b'Tarefa privada admin' not in member.request('/notificacoes')[2], 'Avisos isolam donos')
        notice = db.execute('SELECT id FROM hc_portal_task_notifications WHERE task_id = ?', (task,)).fetchone()[0]
        check(admin.request('/notificacoes/tarefas/ler', dict(csrf=at,id=notice))[0] == 404, 'Outra conta não lê aviso da tarefa')
        check(member.request('/notificacoes/tarefas/ler', dict(csrf='bad',id=notice))[0] == 403, 'Aviso exige CSRF')
        state(task, csrf='bad', expected=403)
        state(task, complete='2', expected=400)
        state(task, revision=0, expected=409)
        state(task)
        check(record(task)['completed_at'] is not None and notice_count(task, True) == 0, 'Concluir registra data e encerra aviso pendente')
        for _ in range(2): member.request('/agenda')
        check(notice_count(task) == 1 and notice_count(task,True) == 0, 'Acesso não recria aviso de tarefa concluída')
        check('1 de 1 concluídas' in member.request('/agenda/eventos/' + str(event))[2].decode(), 'Evento apresenta progresso')
        state(task, complete='0', return_to='https://example.com')
        check(record(task)['completed_at'] is None and notice_count(task,True) == 0, 'Reabrir preserva aviso já lido')
        check(state(task, complete='1', return_to='/agenda')[1]['Location'] == '/agenda', 'Conclusão retorna à agenda')
        state(task, complete='0')
        update(task, title='Tarefa renomeada', event_date=future, priority='media')
        check(notice_count(task) == 0 and record(task)['task_date'] == future, 'Reagendar cancela aviso antigo')
        update(task, revision=1, expected=409)
        update(task, event_id=admin_event, expected=404)
        member.request('/agenda/eventos/atualizar', dict(event_values,id=event,revision=1,event_date=past))
        check(record(task)['task_date'] == future, 'Reagendar evento preserva data da tarefa')
        update(task,event_date=str(today))
        member.request('/agenda')
        check(notice_count(task,True) == 1, 'Reagendar tarefa para hoje gera novo aviso')
        check(member.request('/notificacoes/tarefas/ler',dict(csrf=mt,id=db.execute('SELECT id FROM hc_portal_task_notifications WHERE task_id = ?', (task,)).fetchone()[0]))[0] == 303, 'Dono marca aviso de tarefa como lido')
        check(notice_count(task,True) == 0, 'Leitura persiste')
        state(later)
        db.execute('UPDATE hc_portal_tasks SET task_date = ?, notify_on = ? WHERE id = ?', (past,past,later))
        db.commit()
        member.request('/agenda')
        check(notice_count(later) == 0, 'Tarefa concluída antecipadamente não avisa quando data chega')
        state(later,complete='0')
        member.request('/biblioteca')
        check(notice_count(later,True) == 1, 'Tarefa elegível reaberta recebe aviso tardio no acesso')
        revision = record(task)['revision']
        check(member.request('/agenda/eventos/excluir',dict(csrf=mt,id=event,revision=2,confirm=1))[0] == 303, 'Excluir evento com tarefas')
        check(record(task)['event_id'] is None and record(task)['revision'] == revision+1 and record(task)['task_date'] == str(today), 'Excluir evento preserva tarefa avulsa e invalida formulário antigo')
        update(task,revision=revision,expected=409)
        check(b'Tarefa avulsa' in member.request('/agenda/tarefas/' + str(task))[2], 'Tarefa preservada acessível')
        response = admin.request('/materias/criar',dict(csrf=at,name='Tarefas matéria temporária',color='teal'))
        temporary = int(response[1]['Location'].rsplit('/',1)[1])
        update(task,subject_id=temporary)
        admin.request('/materias/excluir',dict(csrf=at,id=temporary,revision=1,confirm=1))
        check(record(task)['subject_id'] is None, 'Excluir matéria preserva tarefa sem associação')
        check(member.request('/agenda/tarefas/excluir',dict(csrf=mt,id=task,revision=record(task)['revision']))[0] == 400, 'Exclusão exige confirmação')
        check(member.request('/agenda/tarefas/excluir',dict(csrf=mt,id=task,revision=1,confirm=1))[0] == 409, 'Exclusão exige revisão atual')
        check(member.request('/agenda/tarefas/excluir',dict(csrf=mt,id=task,revision=record(task)['revision'],confirm=1))[0] == 303, 'Dono exclui tarefa')
        check(record(task) is None and notice_count(task) == 0, 'Exclusão elimina tarefa e aviso por FK')
        check(member.request('/agenda/tarefas/' + str(task))[0] == 404, 'Tarefa removida retorna 404')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall() == baseline, 'Materiais existentes preservados')
    paths = ['portal/src/tasks.php','portal/src/task-views.php','portal/src/events.php','portal/src/agenda-views.php','portal/src/migrations.php','portal/schema.sql']
    report = dict(status='verified',checks=len(checks),results=checks,verified_at=datetime.now(timezone.utc).isoformat(),sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/tasks-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Tarefas:',len(checks),'verificações aprovadas')

if __name__ == '__main__': main()
