"""Testa as vídeo aulas do YouTube por matéria com banco temporário."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

import test_portal as portal
from test_runtime_fixes import test_server

VIDEO_A = 'dQw4w9WgXcQ'
VIDEO_B = 'aqz-KE-bpKQ'
VIDEO_C = 'jNQXAC9IVRw'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    php = Path(args.php)
    checks = []

    def check(condition, label):
        assert condition, label
        checks.append(label)

    with test_server(php) as (base, connection, config, _, _, folder, environment):
        script = folder / 'youtube.php'
        script.write_text('<?php require ' + portal.php_literal(portal.ROOT / 'portal/src/bootstrap.php') + '; require ' + portal.php_literal(portal.ROOT / 'portal/src/videos.php') + '; echo json_encode(array_map("youtube_video_id", json_decode(stream_get_contents(STDIN), true)));', encoding='utf-8')
        links = {
            'https://www.youtube.com/watch?v=' + VIDEO_A: VIDEO_A,
            'https://youtube.com/watch?v=' + VIDEO_A + '&list=PL1&t=30s': VIDEO_A,
            'www.youtube.com/watch?v=' + VIDEO_A: VIDEO_A,
            'http://m.youtube.com/watch?v=' + VIDEO_A: VIDEO_A,
            'https://youtu.be/' + VIDEO_B + '?si=abc': VIDEO_B,
            'https://www.youtube.com/shorts/' + VIDEO_C: VIDEO_C,
            'https://www.youtube.com/embed/' + VIDEO_C: VIDEO_C,
            'https://www.youtube.com/live/' + VIDEO_C + '?feature=share': VIDEO_C,
            'https://www.youtube-nocookie.com/embed/' + VIDEO_A: VIDEO_A,
            '  https://youtu.be/' + VIDEO_B + '  ': VIDEO_B,
            'https://www.youtube.com/playlist?list=PL123': None,
            'https://www.youtube.com/watch?v=curto': None,
            'https://www.youtube.com/watch?v[]=' + VIDEO_A: None,
            'https://evil.example/watch?v=' + VIDEO_A: None,
            'https://youtube.com.evil.example/watch?v=' + VIDEO_A: None,
            'https://user@www.youtube.com/watch?v=' + VIDEO_A: None,
            'javascript:alert(1)//youtube.com/watch?v=' + VIDEO_A: None,
            'ftp://www.youtube.com/watch?v=' + VIDEO_A: None,
            'https://www.youtube.com/watch?v=' + VIDEO_A + '"onload="x': None,
            VIDEO_A: None,
            '': None,
        }
        result = subprocess.run([str(php), '-n', str(script)], input=json.dumps(list(links)).encode(), env=environment, capture_output=True, check=True)
        parsed = json.loads(result.stdout)
        for link, got, expected in zip(links, parsed, links.values()):
            check(got == expected, 'Link interpretado: ' + repr(link))

        admin = portal.Client(base)
        member = portal.Client(base)
        guest = portal.Client(base)
        check(admin.login()[0] == 303, 'Administrador autentica')
        check(member.login('aluno', portal.MEMBER_PASSWORD)[0] == 303, 'Estudante autentica')
        token = admin.csrf('/biblioteca')
        member_token = member.csrf('/biblioteca')
        status, headers, _ = admin.request('/materias/criar', {'csrf': token, 'name': 'Matéria de vídeos', 'color': 'teal'})
        subject = int(headers['Location'].rsplit('/', 1)[1])
        status, headers, _ = admin.request('/materias/criar', {'csrf': token, 'name': 'Matéria sem vídeos', 'color': 'blue'})
        empty_subject = int(headers['Location'].rsplit('/', 1)[1])
        page_url = '/materias/' + str(subject)

        def videos(subject_id=subject):
            return connection.execute('SELECT id, title, youtube_id FROM hc_portal_videos WHERE subject_id = ? ORDER BY sort_order, id', (subject_id,)).fetchall()

        def add(title, link, client=admin, csrf=token, subject_id=subject):
            return client.request('/videos/criar', {'csrf': csrf, 'subject_id': subject_id, 'title': title, 'url': link})

        # Matéria sem vídeos.
        body = admin.request('/materias/' + str(empty_subject))[2]
        check(b'id="videos"' in body and b'Nenhuma v' in body and b'data-open="video-add-dialog"' in body, 'Administrador vê a seção vazia com o botão de adicionar')
        body = member.request('/materias/' + str(empty_subject))[2]
        check(b'id="videos"' not in body and b'video-dialog' not in body, 'Estudante não vê a seção quando a matéria não tem vídeos')

        # Permissões e validações.
        check(guest.request('/videos/criar', {'csrf': 'x', 'subject_id': subject, 'title': 'A', 'url': VIDEO_A})[1]['Location'] == '/entrar', 'Visitante é enviado ao login')
        check(add('Indevido', 'https://youtu.be/' + VIDEO_A, member, member_token)[0] == 403, 'Estudante não adiciona vídeos')
        check(admin.request('/videos/criar', {'csrf': 'invalido', 'subject_id': subject, 'title': 'A', 'url': VIDEO_A})[0] == 403, 'Adição valida CSRF')
        check(admin.request('/videos/criar')[0] == 405, 'GET não adiciona vídeos')
        check(add('Sem link válido', 'https://example.com/x')[0] == 400, 'Link que não é do YouTube é recusado')
        check(add('', 'https://youtu.be/' + VIDEO_A)[0] == 400, 'Título obrigatório')
        check(add('Matéria inexistente', 'https://youtu.be/' + VIDEO_A, subject_id=999999)[0] == 400, 'Matéria inexistente é recusada')
        check(videos() == [], 'Entradas inválidas não criam vídeos')

        # Adição e ordem.
        status, headers, _ = add('Aula 1 <script>alert(1)</script>', 'https://www.youtube.com/watch?v=' + VIDEO_A)
        check(status == 303 and headers['Location'] == page_url + '#videos', 'Adição redireciona para a seção de vídeos')
        check(add('Aula 2', 'https://youtu.be/' + VIDEO_B)[0] == 303, 'Segundo vídeo adicionado')
        check(add('Aula 3', 'https://www.youtube.com/shorts/' + VIDEO_C)[0] == 303, 'Terceiro vídeo adicionado')
        check([row[2] for row in videos()] == [VIDEO_A, VIDEO_B, VIDEO_C], 'Vídeos ficam na ordem de adição')
        ids = [row[0] for row in videos()]

        for client, label in ((admin, 'Administrador'), (member, 'Estudante')):
            status, headers, body = client.request(page_url)
            check(status == 200 and body.count(b'data-video-open') == 3, label + ' vê os três vídeos')
            check(b'<script>alert(1)</script>' not in body and b'&lt;script&gt;alert(1)&lt;/script&gt;' in body, label + ': título é escapado')
            check(body.index(VIDEO_A.encode()) < body.index(VIDEO_B.encode()) < body.index(VIDEO_C.encode()), label + ' vê a ordem definida')
            check(('https://www.youtube.com/watch?v=' + VIDEO_B).encode() in body, label + ' tem link para abrir no YouTube')
            csp = headers['Content-Security-Policy']
            check('frame-src \'self\' https://www.youtube-nocookie.com' in csp and 'https://i.ytimg.com' in csp, label + ': política permite somente o player e as miniaturas')
        body = admin.request(page_url)[2]
        check(body.count(b'/videos/mover') == 6 and ('/videos/' + str(ids[0]) + '/editar').encode() in body, 'Administrador vê reordenar e editar')
        body = member.request(page_url)[2]
        check(b'/videos/mover' not in body and b'/editar' not in body.split(b'id="videos"')[1].split(b'</section>')[0] and b'data-open="video-add-dialog"' not in body, 'Estudante não vê controles de gestão')
        check(b'id="videos"' not in member.request('/materiais/sem-materia')[2] and b'id="videos"' not in member.request('/biblioteca')[2], 'Vídeos só aparecem na página da matéria')

        # Reordenação.
        def move(video_id, direction, client=admin, csrf=token):
            return client.request('/videos/mover', {'csrf': csrf, 'id': video_id, 'direction': direction})

        check(move(ids[0], 'down', member, member_token)[0] == 403, 'Estudante não reordena')
        check(admin.request('/videos/mover', {'csrf': 'x', 'id': ids[0], 'direction': 'down'})[0] == 403, 'Reordenação valida CSRF')
        check(move(ids[0], 'sideways')[0] == 400, 'Direção inválida é recusada')
        check(move(999999, 'up')[0] == 404, 'Vídeo inexistente retorna 404')
        status, headers, _ = move(ids[0], 'down')
        check(status == 303 and headers['Location'] == page_url + '#videos' and [row[0] for row in videos()] == [ids[1], ids[0], ids[2]], 'Mover para baixo troca com o seguinte')
        check(move(ids[2], 'up')[0] == 303 and [row[0] for row in videos()] == [ids[1], ids[2], ids[0]], 'Mover para cima troca com o anterior')
        check(move(ids[1], 'up')[0] == 303 and [row[0] for row in videos()] == [ids[1], ids[2], ids[0]], 'Primeiro vídeo não sobe além do início')
        check(move(ids[0], 'down')[0] == 303 and [row[0] for row in videos()] == [ids[1], ids[2], ids[0]], 'Último vídeo não desce além do fim')
        body = member.request(page_url)[2]
        check(body.index(VIDEO_B.encode()) < body.index(VIDEO_C.encode()) < body.index(VIDEO_A.encode()), 'Estudante vê a nova ordem')
        check(sorted(row[0] for row in connection.execute('SELECT sort_order FROM hc_portal_videos WHERE subject_id = ?', (subject,)).fetchall()) == [1, 2, 3], 'Ordem permanece sequencial')
        check(add('Aula 4', 'https://youtu.be/' + VIDEO_A)[0] == 303 and videos()[-1][1] == 'Aula 4', 'Novo vídeo entra no fim da lista reordenada')
        ids = [row[0] for row in videos()]

        # Edição.
        target = ids[0]
        check(member.request('/videos/' + str(target) + '/editar')[0] == 403, 'Estudante não abre a edição')
        check(admin.request('/videos/999999/editar')[0] == 404, 'Edição de vídeo inexistente retorna 404')
        status, _, body = admin.request('/videos/' + str(target) + '/editar')
        revision = re.search(rb'name="revision" value="(\d+)"', body).group(1).decode()
        check(status == 200 and ('https://www.youtube.com/watch?v=' + VIDEO_B).encode() in body, 'Edição mostra o link atual')
        values = {'csrf': token, 'id': target, 'revision': revision, 'title': 'Título revisado', 'url': 'https://youtu.be/' + VIDEO_C}
        check(member.request('/videos/atualizar', dict(values, csrf=member_token))[0] == 403, 'Estudante não atualiza vídeos')
        check(admin.request('/videos/atualizar', dict(values, url='https://example.com'))[0] == 400, 'Atualização recusa link inválido')
        status, headers, _ = admin.request('/videos/atualizar', values)
        check(status == 303 and headers['Location'] == page_url + '#videos', 'Atualização conclui')
        row = connection.execute('SELECT title, youtube_id, revision, sort_order FROM hc_portal_videos WHERE id = ?', (target,)).fetchone()
        check(row[:3] == ('Título revisado', VIDEO_C, int(revision) + 1) and [r[0] for r in videos()][0] == target, 'Atualização muda título e link e mantém a posição')
        check(admin.request('/videos/atualizar', values)[0] == 409, 'Formulário antigo é recusado')
        check(admin.request('/videos/atualizar', dict(values, revision='abc'))[0] == 409, 'Revisão inválida é recusada')

        # Remoção.
        revision = str(row[2])
        remove = {'csrf': token, 'id': target, 'revision': revision, 'confirm': 1}
        check(member.request('/videos/excluir', dict(remove, csrf=member_token))[0] == 403, 'Estudante não remove vídeos')
        check(admin.request('/videos/excluir', {k: v for k, v in remove.items() if k != 'confirm'})[0] == 400, 'Remoção exige confirmação')
        check(admin.request('/videos/excluir', dict(remove, revision='99'))[0] == 409, 'Remoção com revisão antiga é recusada')
        check(admin.request('/videos/excluir')[0] == 405, 'GET não remove vídeos')
        status, headers, _ = admin.request('/videos/excluir', remove)
        check(status == 303 and target not in [r[0] for r in videos()] and len(videos()) == 3, 'Remoção apaga somente o vídeo escolhido')
        check(admin.request('/videos/' + str(target) + '/editar')[0] == 404, 'Vídeo removido deixa de existir')

        # Exclusão da matéria remove seus vídeos e preserva materiais.
        check(admin.upload(token, subject, [('preservado.txt', 'text/plain', b'Bytes preservados')])[0] == 303, 'Material enviado na matéria com vídeos')
        material = connection.execute("SELECT id FROM hc_portal_files WHERE original_name = 'preservado.txt'").fetchone()[0]
        body = admin.request('/materias/' + str(subject) + '/editar')[2]
        revision = re.search(rb'name="revision" value="(\d+)"', body).group(1).decode()
        check(admin.request('/materias/excluir', {'csrf': token, 'id': subject, 'revision': revision, 'confirm': 1})[0] == 303, 'Matéria com vídeos pode ser excluída')
        check(videos() == [] and connection.execute('SELECT COUNT(*) FROM hc_portal_videos').fetchone()[0] == 0, 'Exclusão da matéria remove seus vídeos')
        check(member.request('/materiais/' + str(material) + '/download')[2] == b'Bytes preservados', 'Material da matéria excluída é preservado')

        # Segurança do banco e do navegador.
        check(connection.execute('PRAGMA foreign_key_check').fetchall() == [], 'Banco sem violações de chave estrangeira')

    if args.output:
        report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'total': len(checks), 'checks': checks}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'checks': len(checks)}))


if __name__ == '__main__':
    main()
