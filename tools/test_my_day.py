"""Painel Meu dia: privacidade, datas, paginação e estado das tarefas via HTTP."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import test_portal as portal
from test_runtime_fixes import test_server


def seed(db, owner, today):
    def task(title, day, done=False, timed=False):
        return db.execute('INSERT INTO hc_portal_tasks (user_id, title, description, task_date, priority, category, starts_at, ends_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (owner, title, '', str(day), 'urgente', 'curso', '00:00' if timed else None, '00:01' if timed else None, '2026-01-01 10:00:00' if done else None)).lastrowid
    def event(title, day):
        return db.execute('INSERT INTO hc_portal_events (user_id, title, description, event_date, priority, category) VALUES (?, ?, ?, ?, ?, ?)', (owner, title, '', str(day), 'media', 'faculdade')).lastrowid
    for i in range(13):
        task('Hoje ' + str(i).zfill(2), today, timed=i == 0)
        event('Evento hoje ' + str(i).zfill(2), today)
    for i in range(12):
        task('Atrasada ' + str(i).zfill(2), today - timedelta(days=1), timed=i == 0)
        task('Concluída hoje ' + str(i).zfill(2), today, done=True)
    task('Passado concluído', today - timedelta(days=3), done=True)
    event('Evento passado', today - timedelta(days=3))
    for i in range(11):
        task('Futura ' + str(i).zfill(2), today + timedelta(days=1))
    event('Limite sete dias', today + timedelta(days=7))
    task('Limite tarefa sete dias', today + timedelta(days=7))
    task('Futura concluída', today + timedelta(days=2), done=True)
    event('Fora oito dias', today + timedelta(days=8))
    task('Fora tarefa oito dias', today + timedelta(days=8))
    task('<script>alert(1)</script>', today)
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    args = parser.parse_args()
    checks = []
    def check(value, label):
        assert value, label
        checks.append(label)
    def counts(body):
        return {key.decode(): int(value) for key, value in re.findall(rb'data-my-day-count="([^"]+)">([0-9]+)', body)}
    with test_server(Path(args.php)) as (base, db, config, _, _, scratch, env):
        guest, member, admin = [portal.Client(base) for _ in range(3)]
        check(guest.request('/meu-dia?tarefas=2')[1]['Location'] == '/entrar', 'Painel exige login')
        check(guest.login('aluno', portal.MEMBER_PASSWORD)[1]['Location'] == '/meu-dia?tarefas=2', 'Login retoma painel e paginação solicitados')
        check(member.login('aluno', portal.MEMBER_PASSWORD)[1]['Location'] == '/biblioteca', 'Login sem destino continua na biblioteca')
        admin.login()
        mt, at = member.csrf(), admin.csrf()
        owner = db.execute("SELECT id FROM hc_portal_users WHERE login = 'aluno'").fetchone()[0]
        other = db.execute("SELECT id FROM hc_portal_users WHERE login = 'admin'").fetchone()[0]
        baseline = db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall()
        status, _, body = member.request('/meu-dia')
        check(status == 200 and counts(body) == dict(eventos=0, tarefas=0, atrasadas=0, proximos=0), 'Estados vazios e contagens zeradas')
        check(body.count(b'class="agenda-empty"') == 4, 'Quatro listas vazias explicadas')
        check(member.request('/meu-dia', dict(csrf=mt))[0] == 405, 'Painel aceita somente GET')
        check(member.request('route=my-day', follow_canonical=False)[1]['Location'] == '/meu-dia', 'Rota antiga do painel redireciona para URL amigável')
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        db.execute("INSERT INTO hc_portal_users (login, name, password_hash, role, must_change_password) SELECT 'segundo.aluno', 'Segundo aluno', password_hash, 'member', 0 FROM hc_portal_users WHERE id = ?", (owner,))
        second_owner = db.execute("SELECT id FROM hc_portal_users WHERE login = 'segundo.aluno'").fetchone()[0]
        db.execute("INSERT INTO hc_portal_tasks (user_id, title, description, task_date, priority, category) VALUES (?, 'Privado segundo aluno', '', ?, 'baixa', 'curso')", (second_owner, str(today)))
        db.execute("INSERT INTO hc_portal_events (user_id, title, description, event_date, priority, category) VALUES (?, 'Privado segundo aluno evento', '', ?, 'baixa', 'curso')", (second_owner, str(today)))
        db.commit()
        second_member = portal.Client(base)
        second_member.login('segundo.aluno', portal.MEMBER_PASSWORD)
        seed(db, owner, today)
        seed(db, other, today)
        db.execute("UPDATE hc_portal_tasks SET title = 'Privado administrador ' || id WHERE user_id = ?", (other,))
        db.execute("UPDATE hc_portal_events SET title = 'Privado administrador evento ' || id WHERE user_id = ?", (other,))
        db.commit()
        status, _, body = member.request('/meu-dia?user_id=' + str(other))
        check(status == 200 and counts(body) == dict(eventos=13, tarefas=14, atrasadas=12, proximos=13), 'Contagens do dono, sem incluir outra conta ou tarefas concluídas')
        check(b'Privado administrador' not in body, 'Estudante não vê títulos da outra conta')
        check(b'Privado segundo aluno' not in body, 'Estudante não vê compromissos de outro estudante')
        check(counts(second_member.request('/meu-dia')[2]) == dict(eventos=1, tarefas=1, atrasadas=0, proximos=0), 'Segundo estudante vê apenas suas contagens')
        check(b'Privado segundo aluno' not in admin.request('/meu-dia')[2], 'Administrador não vê compromissos do segundo estudante')
        check('Hoje 00'.encode() not in admin.request('/meu-dia')[2], 'Administrador não vê tarefas de estudante')
        check(counts(admin.request('/meu-dia')[2]) == dict(eventos=13, tarefas=14, atrasadas=12, proximos=13), 'Administrador também recebe somente suas contagens')
        for key, attribute in [('eventos', b'data-commitment-id'), ('tarefas', b'data-task-row'), ('atrasadas', b'data-task-row'), ('proximos', b'data-commitment-id')]:
            section = body.split(('id="' + key + '"').encode(), 1)[1].split(b'</section>', 1)[0]
            if key == 'tarefas': section = section.split(b'<details', 1)[0]
            check(section.count(attribute) == 10, 'Lista limitada a dez itens: ' + key)
            second = member.request('/meu-dia?' + key + '=2')[2].split(('id="' + key + '"').encode(), 1)[1].split(b'</section>', 1)[0]
            if key == 'tarefas': second = second.split(b'<details', 1)[0]
            check(second.count(attribute) == (4 if key == 'tarefas' else 2 if key == 'atrasadas' else 3), 'Segunda página acessível: ' + key)
        second = member.request('/meu-dia?tarefas=2&proximos=2&concluidas=2')[2]
        check(b'&lt;script&gt;alert(1)&lt;/script&gt;' in body and b'<script>alert(1)</script>' not in body, 'Título escapado contra HTML')
        check(b'Limite sete dias' in second and b'Limite tarefa sete dias' in second, 'Inclui sétimo dia para eventos e tarefas')
        for title in ['Fora oito dias', 'Fora tarefa oito dias', 'Futura concluída', 'Evento passado', 'Passado concluído']:
            check(title.encode() not in body + second, 'Exclui item fora da regra: ' + title)
        for invalid in ['0', '-1', 'abc', '999999999999', '1%20OR%201=1']:
            check(member.request('/meu-dia?tarefas=' + invalid)[0] == 200, 'Paginação inválida limitada com segurança: ' + invalid)
        check(member.request('/meu-dia?tarefas[]=2')[0] == 200, 'Paginação em array não quebra o painel')
        task = db.execute("SELECT id FROM hc_portal_tasks WHERE user_id = ? AND title = 'Hoje 00'", (owner,)).fetchone()[0]
        state = dict(csrf=mt, id=task, revision=1, complete=1, return_to='/meu-dia?tarefas=2&proximos=2')
        check(member.request('/agenda/tarefas/estado', dict(state, csrf='bad'))[0] == 403, 'Conclusão no painel exige CSRF')
        check(admin.request('/agenda/tarefas/estado', dict(state, csrf=at))[0] == 404, 'Administrador não conclui tarefa alheia')
        response = member.request('/agenda/tarefas/estado', state)
        check(response[0] == 303 and response[1]['Location'] == state['return_to'], 'Concluir retorna ao painel conservando páginas')
        check(counts(member.request('/meu-dia')[2])['tarefas'] == 13, 'Conclusão atualiza contagem de pendências')
        check(member.request('/agenda/tarefas/estado', state)[0] == 409, 'Conclusão rejeita formulário antigo')
        check(member.request('/agenda/tarefas/estado', dict(state, revision=2, complete=0))[0] == 303, 'Reabertura reutiliza operação existente')
        check(counts(member.request('/meu-dia')[2])['tarefas'] == 14, 'Reabertura restaura contagem de pendências')
        check(db.execute('SELECT task_date, starts_at, ends_at FROM hc_portal_tasks WHERE id = ?', (task,)).fetchone() == (str(today), '00:00', '00:01'), 'Conclusão e reabertura preservam data e horários')
        # Boundary checks use an explicit instant in the data function; no test clock in production.
        db.execute('DELETE FROM hc_portal_tasks')
        db.execute('DELETE FROM hc_portal_events')
        db.execute("INSERT INTO hc_portal_tasks (user_id, title, description, task_date, priority, category, starts_at, ends_at) VALUES (?, 'Virada com horário', '', '2026-12-30', 'baixa', 'curso', '00:00', '00:01')", (owner,))
        db.execute("INSERT INTO hc_portal_tasks (user_id, title, description, task_date, priority, category) VALUES (?, 'Virada dia inteiro', '', '2026-12-30', 'baixa', 'curso')", (owner,))
        db.execute("INSERT INTO hc_portal_events (user_id, title, description, event_date, priority, category) VALUES (?, 'Novo ano limite', '', '2027-01-07', 'baixa', 'curso')", (owner,))
        db.commit()
        script = scratch / 'clock.php'
        script.write_text('<?php require ' + portal.php_literal(portal.ROOT/'portal/src/bootstrap.php') + '; require ' + portal.php_literal(portal.ROOT/'portal/src/my-day.php') + '; echo json_encode(my_day_data(' + str(owner) + ', new DateTimeImmutable($argv[1])));', encoding='utf-8')
        def clock(instant):
            result = subprocess.run([args.php, '-n', '-d', 'extension_dir=' + str(Path(args.php).parent/'ext'), '-d', 'extension=pdo_sqlite', str(script), instant], env=env, capture_output=True, check=True)
            return json.loads(result.stdout)
        before, after = clock('2026-12-31T02:59:59Z'), clock('2026-12-31T03:00:00Z')
        check(before['today'] == '2026-12-30' and before['groups']['tarefas']['total'] == 2 and before['groups']['atrasadas']['total'] == 0, 'Horário de fim passado não atrasa tarefas antes da meia-noite de Brasília')
        check(after['today'] == '2026-12-31' and after['groups']['tarefas']['total'] == 0 and after['groups']['atrasadas']['total'] == 2, 'Meia-noite de Brasília atrasa tarefas com horário e de dia inteiro')
        check(before['groups']['proximos']['total'] == 0 and after['last'] == '2027-01-07' and after['groups']['proximos']['total'] == 1, 'Sete dias atravessam mês e ano sem incluir o oitavo dia')
        check(db.execute('SELECT * FROM hc_portal_files ORDER BY id').fetchall() == baseline, 'Painel preserva materiais existentes')
    paths = ['portal/src/my-day.php','portal/src/bootstrap.php','portal/src/controller.php','portal/src/views.php','portal/assets/app.css','index.php']
    report = dict(status='verified', checks=len(checks), results=checks, verified_at=datetime.now(timezone.utc).isoformat(), sha256={p:hashlib.sha256((portal.ROOT/p).read_bytes()).hexdigest() for p in paths})
    (portal.ROOT/'artifacts/my-day-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Meu dia:', len(checks), 'verificações aprovadas')


if __name__ == '__main__': main()
