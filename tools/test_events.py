"""Agenda: HTTP real, isolamento por dono e ciclo de vida dos avisos."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import re
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    args = parser.parse_args()
    checks = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with test_server(Path(args.php)) as (base, db, config, storage, manifest, scratch, env):
        admin, member, guest = [portal.Client(base) for _ in range(3)]
        admin.login()
        member.login('aluno', portal.MEMBER_PASSWORD)
        at, mt = admin.csrf(), member.csrf()
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        future, past = str(today + timedelta(days=35)), str(today - timedelta(days=1))
        baseline = db.execute('SELECT id, sha256, subject_id, folder_id, kind FROM hc_portal_files ORDER BY id').fetchall()
        subject = db.execute('SELECT id FROM hc_portal_subjects ORDER BY id LIMIT 1').fetchone()[0]
        defaults = dict(csrf=mt, title='Evento exclusivo do estudante', description='Linha um\n<script>alert(1)</script>', event_date=str(today), all_day='1', priority='urgente', subject_id=subject, category='faculdade')

        def create(expected=303, client=member, **values):
            response = client.request('/agenda/eventos/criar', dict(defaults, **values))
            check(response[0] == expected, 'Criar evento HTTP ' + str(expected) + ': ' + str(values))
            return int(response[1]['Location'].rsplit('/', 1)[1]) if expected == 303 else None

        def row(event):
            cursor = db.execute('SELECT * FROM hc_portal_events WHERE id = ?', (event,))
            result = cursor.fetchone()
            return dict(zip([column[0] for column in cursor.description], result)) if result else None

        def change(event, expected=303, client=member, **values):
            original = row(event)
            data = {key: original[key] if original[key] is not None else '' for key in ['title', 'description', 'event_date', 'priority', 'subject_id', 'starts_at', 'ends_at', 'category']}
            data.update(csrf=mt, id=event, revision=original['revision'], all_day='1' if original['starts_at'] is None else '0')
            data.update(values)
            response = client.request('/agenda/eventos/atualizar', data)
            check(response[0] == expected, 'Alterar evento HTTP ' + str(expected) + ': ' + str(values))

        def count(event, unread=False):
            return db.execute('SELECT COUNT(*) FROM hc_portal_event_notifications WHERE event_id = ?' + (' AND read_at IS NULL' if unread else ''), (event,)).fetchone()[0]

        check(guest.request('/agenda')[0] == 303, 'Agenda exige autenticação')
        check(guest.login('aluno', portal.MEMBER_PASSWORD)[1]['Location'] == '/agenda', 'Login retoma agenda')
        for route in ['/agenda/eventos/criar', '/agenda/eventos/atualizar', '/agenda/eventos/excluir', '/notificacoes/ler']:
            check(member.request(route)[0] == 405, route + ' exige POST')
        check(member.request('/agenda', {'csrf': mt})[0] == 405, 'Calendário exige GET')
        create(csrf='invalid', expected=403)
        for category in ['', 'pessoal', 'trabalho', 'Faculdade', ['faculdade']]:
            create(expected=400, category=category)
        missing = dict(defaults)
        del missing['category']
        check(member.request('/agenda/eventos/criar', missing)[0] == 400, 'Categoria ausente é recusada pelo servidor')
        for values in [dict(title=' '), dict(title='x'*181), dict(description='x'*5001), dict(event_date='2026-02-30'), dict(event_date='0999-01-01'), dict(event_date='2026-1-01'), dict(event_date=['2026-01-01']), dict(priority='alta'), dict(priority='x'), dict(subject_id='xyz'), dict(subject_id=999999), dict(all_day='2'), dict(all_day='0'), dict(all_day='0', starts_at='24:00', ends_at='25:00'), dict(all_day='0', starts_at='13:00', ends_at='13:00'), dict(all_day='0', starts_at='13:00', ends_at='12:00')]:
            create(expected=400, **values)
        event = create()
        check(row(event)['category'] == 'faculdade', 'Categoria persiste no cadastro')
        categories = {'faculdade': 'Faculdade', 'curso': 'Curso', 'certificacao': 'Certificação', 'concurso': 'Concurso', 'estudo_independente': 'Estudo independente', 'pesquisa': 'Pesquisa', 'evento_academico': 'Evento acadêmico'}
        for category, label in categories.items():
            change(event, category=category)
            check(row(event)['category'] == category and ('Categoria: ' + label).encode() in member.request('/agenda/eventos/' + str(event))[2], 'Categoria válida persiste e aparece: ' + label)
        for category in ['', 'pessoal', ['curso']]:
            change(event, category=category, expected=400)
        # Categoria nula representa um cadastro anterior à migração 006.
        db.execute('UPDATE hc_portal_events SET category = NULL WHERE id = ?', (event,))
        db.commit()
        check(b'Sem categoria' in member.request('/agenda/eventos/' + str(event))[2], 'Evento antigo permanece acessível sem categoria inventada')
        change(event, expected=400)
        change(event, category='faculdade')
        check(count(event) == 1, 'Classificar evento anterior conserva a mesma notificação')
        timed = create(title='Evento com horário', all_day='0', starts_at='08:30', ends_at='10:00', priority='baixa', subject_id='')
        old = create(title='Evento histórico', event_date=past, priority='media')
        later = create(title='Evento futuro', event_date=future)
        own_admin = create(client=admin, csrf=at, title='Evento exclusivo do administrador')
        check(row(event)['starts_at'] is None and row(event)['ends_at'] is None, 'Dia inteiro persiste sem horários')
        check(row(timed)['starts_at'] == '08:30' and row(timed)['ends_at'] == '10:00', 'Horário inicial e final persistem')
        check(row(old)['notify_on'] is None, 'Cadastro passado não agenda aviso retroativo')
        check(row(later)['notify_on'] == future, 'Evento futuro agenda aviso para sua data')
        # detalhe e formulários em modal: só o fragmento, com o mesmo controle de acesso
        shown = member.request('/agenda/eventos/' + str(event) + '?modal=1')
        check(shown[0] == 200 and b'data-detail-fragment data-detail-forms' in shown[2] and b'<html' not in shown[2], 'Detalhe do evento em modal devolve só o fragmento')
        formed = member.request('/agenda/novo?modal=1')
        check(formed[0] == 200 and b'data-detail-fragment' in formed[2] and b'data-event-form' in formed[2] and b'<html' not in formed[2] and b'data-close' in formed[2], 'Novo evento em modal devolve o formulário sem layout')
        edited = member.request('/agenda/eventos/' + str(event) + '/editar?modal=1')
        check(edited[0] == 200 and b'data-event-form' in edited[2] and b'<html' not in edited[2], 'Edição do evento em modal devolve o formulário sem layout')
        check(admin.request('/agenda/eventos/' + str(event) + '?modal=1')[0] == 404 and admin.request('/agenda/eventos/' + str(event) + '/editar?modal=1')[0] == 404, 'Fragmentos do evento não vazam para outro usuário')
        check(portal.Client(base).request('/agenda/eventos/' + str(event) + '?modal=1')[0] == 303, 'Fragmento do evento exige autenticação')
        check(b'<html' in member.request('/agenda/eventos/' + str(event))[2] and b'data-detail-fragment' not in member.request('/agenda/eventos/' + str(event))[2], 'Página completa do evento continua disponível')
        page = member.request('/agenda/eventos/' + str(event))[2].decode()
        check('&lt;script&gt;' in page and '<script>alert' not in page, 'Descrição é escapada contra XSS')
        check('Linha um<br' in page, 'Quebras da descrição preservadas')
        check(count(event) == count(timed) == 1 and count(old) == count(later) == 0, 'Hoje avisa; passado cadastrado e futuro não avisam')
        for client, foreign, token in [(admin, event, at), (member, own_admin, mt)]:
            for suffix in ['', '/editar']:
                check(client.request('/agenda/eventos/' + str(foreign) + suffix)[0] == 404, 'Outro dono não acessa evento' + suffix)
            change(foreign, expected=404, client=client, csrf=token)
            check(client.request('/agenda/eventos/excluir', dict(csrf=token, id=foreign, revision=1, confirm=1))[0] == 404, 'Outro dono não exclui evento')
        admin_page, member_page = admin.request('/agenda')[2], member.request('/agenda')[2]
        check(defaults['title'].encode() not in admin_page and b'Evento exclusivo do administrador' not in member_page, 'Calendário e sino isolam as contas')
        notice = db.execute('SELECT id FROM hc_portal_event_notifications WHERE event_id = ?', (event,)).fetchone()[0]
        check(admin.request('/notificacoes/ler', dict(csrf=at, id=notice))[0] == 404, 'Outro dono não marca aviso')
        check(member.request('/notificacoes/ler', dict(csrf='bad', id=notice))[0] == 403, 'Leitura exige CSRF')
        check(member.request('/notificacoes/ler', dict(csrf=mt, id=notice))[0] == 303, 'Dono marca aviso como lido')
        for _ in range(3):
            member.request('/agenda')
        check(count(event) == 1 and count(event, True) == 0, 'Acessos posteriores não duplicam nem reabrem aviso lido')
        change(event, title='Título atualizado', priority='baixa')
        change(event, category='pesquisa')
        notices = member.request('/notificacoes')[2]
        check(b'Pesquisa' in notices and count(event, True) == 0, 'Alterar categoria atualiza aviso sem reabrir leitura')
        check('Título atualizado'.encode() in notices and count(event, True) == 0, 'Título atualizado conserva aviso lido')
        change(event, revision=1, expected=409)
        change(event, event_date=future)
        member.request('/agenda')
        check(count(event) == 0, 'Reagendamento para futuro cancela aviso anterior')
        change(event, event_date=str(today))
        member.request('/agenda')
        check(count(event, True) == 1, 'Reagendamento para hoje gera novo aviso')
        change(event, event_date=past)
        member.request('/agenda')
        check(count(event) == 0 and row(event)['notify_on'] is None, 'Reagendamento para passado cancela e não retroage')
        change(old, title='Histórico editado')
        member.request('/agenda')
        check(count(old) == 0, 'Editar histórico sem mudar data não gera aviso')
        # Simula uma data que chegou durante ausência, sem mudar a regra do relógio da aplicação.
        db.execute('UPDATE hc_portal_events SET event_date = ?, notify_on = ? WHERE id = ?', (past, past, later))
        db.commit()
        member.request('/biblioteca')
        check(count(later, True) == 1, 'Acesso tardio recebe aviso pendente na biblioteca')
        notice_page = member.request('/notificacoes')[2].decode()
        check(datetime.strptime(past, '%Y-%m-%d').strftime('%d/%m/%Y') in notice_page, 'Aviso tardio conserva a data original')
        check(count(later) == 1, 'Aviso tardio não duplica')
        change(timed, all_day='1', starts_at='09:00', ends_at='10:00')
        check(row(timed)['starts_at'] is None and row(timed)['ends_at'] is None, 'Converter em dia inteiro elimina horários antigos')
        for date in ['1000-01-01', '9999-12-31', '2028-02-29']:
            check(member.request('/agenda?mes=' + date[:7] + '&dia=' + date)[0] == 200, 'Calendário suporta limite/data bissexta ' + date)
        for query in ['mes=2026-13', 'mes[]=x', 'mes=2026-02&dia=2026-03-01', 'dia=2026-02-30']:
            check(member.request('/agenda?' + query)[0] == 400, 'Calendário rejeita ' + query)
        # Associação removida preserva evento e invalida formulário aberto.
        response = admin.request('/materias/criar', dict(csrf=at, name='Matéria temporária agenda', color='teal'))
        temporary_subject = int(response[1]['Location'].rsplit('/', 1)[1])
        linked = create(subject_id=temporary_subject)
        check(admin.request('/materias/excluir', dict(csrf=at, id=temporary_subject, revision=1, confirm=1))[0] == 303, 'Excluir matéria com evento privado')
        check(row(linked)['subject_id'] is None and row(linked)['revision'] == 2, 'Evento preservado sem matéria e revisão incrementada')
        change(linked, revision=1, expected=409)
        member.request('/agenda')
        check(member.request('/agenda/eventos/excluir', dict(csrf=mt, id=linked, revision=1, confirm=1))[0] == 409, 'Excluir exige revisão atual')
        check(member.request('/agenda/eventos/excluir', dict(csrf=mt, id=linked, revision=2))[0] == 400, 'Excluir exige confirmação')
        check(member.request('/agenda/eventos/excluir', dict(csrf=mt, id=linked, revision=2, confirm=1))[0] == 303, 'Dono exclui evento')
        check(row(linked) is None and count(linked) == 0, 'Exclusão remove evento e notificação por FK')
        check(member.request('/agenda/eventos/' + str(linked))[0] == 404, 'Evento excluído indisponível')
        # Paginação testa a separação entre o resumo do sino e o histórico completo.
        for i in range(23):
            create(title='Aviso paginado ' + str(i), subject_id='')
        body = member.request('/notificacoes')[2]
        check('Página 1 de 2'.encode() in body, 'Histórico paginado')
        check(len(re.findall(rb'data-notification-id=', body)) == 25, 'Histórico mostra 20 e sino mostra 5')
        check(member.request('/notificacoes?pagina=999999')[0] == 200, 'Página excessiva limitada ao histórico existente')
        check(db.execute('SELECT id, sha256, subject_id, folder_id, kind FROM hc_portal_files ORDER BY id').fetchall() == baseline, 'Agenda preserva todos os materiais e classificações')
    paths = ['index.php', 'portal/src/events.php', 'portal/src/agenda-views.php', 'portal/src/migrations.php', 'portal/src/controller.php', 'portal/src/subjects.php', 'portal/src/views.php', 'portal/schema.sql']
    report = dict(status='verified', checks=len(checks), results=checks, tested_at=datetime.now(timezone.utc).isoformat(), sha256={path: hashlib.sha256((portal.ROOT / path).read_bytes()).hexdigest() for path in paths})
    (portal.ROOT / 'artifacts/events-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Agenda:', len(checks), 'verificações aprovadas')


if __name__ == '__main__':
    main()
