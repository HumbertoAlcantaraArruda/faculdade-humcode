"""Atualiza um portal existente por FTPS, com backup, migração e verificação."""
import argparse
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import ftplib
import getpass
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.parse

import deploy
import test_portal

ROOT = deploy.ROOT
FILES = ['portal/src/migrations.php', 'portal/src/subjects.php', 'portal/src/videos.php', 'portal/src/profile.php', 'portal/src/documents.php', 'portal/src/views.php', 'portal/src/install.php', 'portal/src/bootstrap.php', 'portal/src/controller.php', 'portal/assets/app.js', 'portal/assets/app.css', 'portal/assets/theme.js', 'portal/assets/legacy-bridge.js', 'portal/assets/favicon.svg', 'portal/assets/.htaccess', 'portal/schema.sql', 'portal/migrations/001-material-management.sql', 'portal/migrations/002-subject-management.sql', 'portal/migrations/003-subject-videos.sql','portal/bin/migrate.php', 'index.php']
FILES += ['portal/assets/vendor/jquery-3.7.1.min.js', 'portal/assets/vendor/select2-4.1.0.min.js', 'portal/assets/vendor/select2-4.1.0.min.css', 'portal/assets/vendor/select2-pt-BR.js', 'portal/assets/vendor/sweetalert2-11.14.5.min.js', 'portal/assets/vendor/sweetalert2-11.14.5.min.css']
FILES += ['portal/src/folders.php', 'portal/migrations/004-mini-ged.sql']
FILES += ['portal/src/events.php', 'portal/src/agenda-views.php', 'portal/migrations/005-user-agenda.sql']
FILES += ['portal/migrations/006-event-category.sql']
FILES += ['portal/src/tasks.php', 'portal/src/task-views.php', 'portal/migrations/007-agenda-tasks.sql']
FILES += ['portal/src/my-day.php']
FILES += ['portal/src/recurrence.php', 'portal/migrations/008-agenda-recurrence.sql']
FILES += ['portal/src/content-links.php', 'portal/migrations/009-commitment-content.sql']
FILES += ['portal/src/study.php', 'portal/migrations/010-study-progress.sql']
FILES += ['portal/src/notes.php', 'portal/migrations/011-private-notes.sql']
FILES += ['portal/src/invitations.php', 'portal/migrations/012-event-invitations.sql']
FILES += ['portal/src/note-files.php', 'portal/migrations/013-note-files.sql']
FILES += ['portal/migrations/014-note-important.sql', 'portal/assets/vendor/tabulator-6.3.1.min.js', 'portal/assets/vendor/tabulator-6.3.1.min.css']
FILES += ['portal/src/mailer.php', 'portal/src/two-factor.php', 'portal/migrations/015-two-factor.sql']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def optional_bytes(ftp, path):
    try:
        return deploy.remote_bytes(ftp, path)
    except ftplib.error_perm as error:
        if str(error).startswith('550'):
            return None
        raise


def helper_source(token, migration_path, bootstrap_path='portal/src/bootstrap.php'):
    source = '''<?php
declare(strict_types=1);
ini_set('display_errors', '0');
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !is_string($_POST['token'] ?? null) || !hash_equals(TOKEN_LITERAL, $_POST['token'])) { http_response_code(404); exit; }
$humcodeMigrationFile = __DIR__ . MIGRATION_LITERAL;
if (!is_file($humcodeMigrationFile)) { $humcodeMigrationFile = __DIR__ . '/portal/src/migrations.php'; }
$bootstrap = __DIR__ . BOOTSTRAP_LITERAL;
require is_file($bootstrap) ? $bootstrap : __DIR__ . '/portal/src/bootstrap.php';
require_once __DIR__ . '/portal/src/documents.php';
header('Content-Type: application/json; charset=utf-8');
function snapshot(): array {
    $snapshot = [];
    $columns = portal_schema_columns();
    foreach (['hc_portal_users', 'hc_portal_subjects', 'hc_portal_files', 'hc_portal_videos', 'hc_portal_folders', 'hc_portal_events', 'hc_portal_event_notifications', 'hc_portal_tasks', 'hc_portal_task_notifications', 'hc_portal_recurrences', 'hc_portal_event_files', 'hc_portal_event_videos', 'hc_portal_event_folders', 'hc_portal_task_files', 'hc_portal_task_videos', 'hc_portal_task_folders', 'hc_portal_file_study', 'hc_portal_video_study', 'hc_portal_notes', 'hc_portal_note_files', 'hc_portal_invitations'] as $table) {
        $rows = $table !== 'hc_portal_users' && empty($columns[$table]) ? [] : query('SELECT * FROM ' . $table . ' ORDER BY id')->fetchAll();
        foreach ($rows as &$row) {
            unset($row['revision'], $row['legacy_path']);
            if ($table === 'hc_portal_users') { $row['email'] = $row['email'] ?? null; $row['two_factor_enabled'] = (int) ($row['two_factor_enabled'] ?? 0); }
            if ($table === 'hc_portal_files') { $row['deleted_at'] = $row['deleted_at'] ?? null; $row['folder_id'] = $row['folder_id'] ?? null; $row['kind'] = $row['kind'] ?? 'material'; }
            if ($table === 'hc_portal_events') { $row['category'] = $row['category'] ?? null; }
            if (in_array($table, ['hc_portal_events', 'hc_portal_tasks'], true)) { $row['recurrence_id'] = $row['recurrence_id'] ?? null; $row['occurrence_date'] = $row['occurrence_date'] ?? null; $row['recurrence_exception'] = (int) ($row['recurrence_exception'] ?? 0); }
            if ($table === 'hc_portal_tasks') { $row['recurrence_slot'] = (int) ($row['recurrence_slot'] ?? 0); }
            ksort($row);
        }
        unset($row);
        $snapshot[$table] = ['count' => count($rows), 'sha256' => hash('sha256', json_encode($rows, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES))];
    }
    return $snapshot;
}
function classification(): array {
    $columns = portal_schema_columns();
    $kind = isset($columns['hc_portal_files']['kind']) ? 'kind' : "'material'";
    $folder = isset($columns['hc_portal_files']['folder_id']) ? 'folder_id' : 'NULL';
    return query('SELECT subject_id, ' . $kind . ' AS kind, COUNT(*) AS total, SUM(CASE WHEN ' . $folder . ' IS NULL THEN 0 ELSE 1 END) AS in_folders FROM hc_portal_files GROUP BY subject_id, ' . $kind . ' ORDER BY subject_id, kind')->fetchAll();
}
$prefix = 'verify.' . substr(hash('sha256', TOKEN_LITERAL), 0, 16);
$action = $_POST['action'] ?? '';
try {
    if ($action === 'probe') { echo json_encode(['snapshot' => snapshot(), 'classification' => classification(), 'schema_ready' => portal_schema_ready(), 'php' => PHP_VERSION, 'post_max_size' => ini_get('post_max_size'), 'max_file_uploads' => (int) ini_get('max_file_uploads')]); }
    elseif ($action === 'migrate') { echo json_encode(['applied' => migrate_portal(), 'schema_ready' => portal_schema_ready(), 'snapshot' => snapshot(), 'classification' => classification()]); }
    elseif ($action === 'fixtures') {
        $password = $_POST['password'] ?? '';
        if (!is_string($password) || strlen($password) < 12 || strlen($password) > 72) { throw new RuntimeException('Senha de teste inválida.'); }
        db()->beginTransaction();
        foreach (['admin', 'member'] as $role) { query('INSERT INTO hc_portal_users (login, name, password_hash, role, must_change_password) VALUES (?, ?, ?, ?, 0)', [$prefix . '.' . $role, 'Verificação temporária', password_hash($password, PASSWORD_DEFAULT), $role]); }
        // Administrador com 2FA e navegador lembrado: as verificações não enviam e-mails reais.
        $adminId = (int) query('SELECT id FROM hc_portal_users WHERE login = ?', [$prefix . '.admin'])->fetchColumn();
        $email = $prefix . '@example.invalid'; $trusted = bin2hex(random_bytes(32));
        query('UPDATE hc_portal_users SET email = ?, two_factor_enabled = 1 WHERE id = ?', [$email, $adminId]);
        query('INSERT INTO hc_portal_trusted_devices (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)', [$adminId, hash('sha256', $trusted), time() + 3600, time()]);
        db()->commit();
        echo json_encode(['admin_login' => $prefix . '.admin', 'member_login' => $prefix . '.member', 'admin_email' => $email, 'admin_trusted' => ['humcode_2fa_' . $adminId, $trusted]]);
    }
    elseif ($action === 'recurrences') {
        $users = query('SELECT id FROM hc_portal_users WHERE login IN (?, ?)', [$prefix . '.admin', $prefix . '.member'])->fetchAll();
        $result = ['events' => [], 'tasks' => [], 'series' => [], 'invitations' => []];
        foreach ($users as $user) {
            foreach (['events', 'tasks'] as $kind) { $result[$kind] = array_merge($result[$kind], query('SELECT * FROM hc_portal_' . $kind . ' WHERE user_id = ? ORDER BY id', [$user['id']])->fetchAll()); }
            $result['series'] = array_merge($result['series'], query('SELECT * FROM hc_portal_recurrences WHERE user_id = ? ORDER BY id', [$user['id']])->fetchAll());
            $result['invitations'] = array_merge($result['invitations'], query('SELECT * FROM hc_portal_invitations WHERE sender_id = ? ORDER BY id', [$user['id']])->fetchAll());
        }
        echo json_encode($result);
    }
    elseif ($action === 'mail') { require_once __DIR__ . '/portal/src/mailer.php'; echo json_encode(['configured' => mail_available(), 'smtp_login' => mail_probe()]); }
    elseif ($action === 'two-factor') {
        query('UPDATE hc_portal_users SET two_factor_enabled = ? WHERE login = ?', [($_POST['enabled'] ?? '') === '1' ? 1 : 0, $prefix . '.admin']);
        echo json_encode(['ok' => true]);
    }
    elseif ($action === 'cleanup') {
        $users = query('SELECT id FROM hc_portal_users WHERE login IN (?, ?)', [$prefix . '.admin', $prefix . '.member'])->fetchAll();
        foreach ($users as $user) {
            $files = query('SELECT * FROM hc_portal_files WHERE uploaded_by = ?', [$user['id']])->fetchAll();
            foreach ($files as $file) { remove_uploaded_binary($file); }
            $photo = path_inside((string) config('storage_path'), 'avatar-' . (int) $user['id'] . '.image');
            if ($photo && !unlink($photo)) { throw new RuntimeException('Não foi possível limpar a foto temporária.'); }
            db()->beginTransaction();
            query('DELETE FROM hc_portal_files WHERE uploaded_by = ?', [$user['id']]);
            query('DELETE FROM hc_portal_tasks WHERE user_id = ?', [$user['id']]);
            query('DELETE FROM hc_portal_events WHERE user_id = ?', [$user['id']]);
            query('UPDATE hc_portal_folders SET parent_id = NULL WHERE subject_id IN (SELECT id FROM hc_portal_subjects WHERE created_by = ?)', [$user['id']]);
            query('DELETE FROM hc_portal_folders WHERE subject_id IN (SELECT id FROM hc_portal_subjects WHERE created_by = ?)', [$user['id']]);
            query('DELETE FROM hc_portal_videos WHERE created_by = ? OR subject_id IN (SELECT id FROM hc_portal_subjects WHERE created_by = ?)', [$user['id'], $user['id']]);
            query('DELETE FROM hc_portal_subjects WHERE created_by = ?', [$user['id']]);
            query('DELETE FROM hc_portal_recurrences WHERE user_id = ?', [$user['id']]);
            if (!empty(portal_schema_columns()['hc_portal_trusted_devices'])) { query('DELETE FROM hc_portal_trusted_devices WHERE user_id = ?', [$user['id']]); query('DELETE FROM hc_portal_two_factor_codes WHERE user_id = ?', [$user['id']]); }
            query('DELETE FROM hc_portal_users WHERE id = ?', [$user['id']]);
            db()->commit();
        }
        echo json_encode(['snapshot' => snapshot()]);
    }
    else { http_response_code(400); echo json_encode(['error' => 'Operação inválida.']); }
} catch (Throwable $error) {
    if (db()->inTransaction()) { db()->rollBack(); }
    error_log('Humcode update: ' . $error->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Não foi possível concluir a verificação. Consulte o log PHP.']);
}
'''
    return source.replace('TOKEN_LITERAL', deploy.php_string(token)).replace('MIGRATION_LITERAL', deploy.php_string('/' + migration_path)).replace('BOOTSTRAP_LITERAL', deploy.php_string('/' + bootstrap_path)).encode('utf-8')


def verify_features(helper, prefix):
    password = secrets.token_urlsafe(24)
    fixture = helper('fixtures', password=password)
    admin = test_portal.Client(deploy.SITE)
    member = test_portal.Client(deploy.SITE)
    checks = []

    def check(condition, label):
        if not condition:
            raise RuntimeError('Verificação de produção falhou: ' + label)
        checks.append(label)

    mail = helper('mail')
    check(mail['configured'] and mail['smtp_login'], 'SMTP configurado e autenticado em produção (códigos do 2FA)')
    admin.trust(*fixture['admin_trusted'])
    check(admin.login(fixture['admin_login'], password)[0] == 303, 'Administrador temporário autentica')
    check(member.login(fixture['member_login'], password)[0] == 303, 'Estudante temporário autentica')
    # Validação em 2 etapas: navegador lembrado entra sem código; admin sem 2FA fica restrito à Minha conta.
    check(admin.request('/biblioteca')[0] == 200, 'Administrador com 2FA e navegador lembrado acessa o portal')
    check(member.request('/biblioteca')[0] == 200, 'Estudante sem 2FA continua entrando somente com a senha')
    helper('two-factor', enabled='0')
    blocked = admin.request('/biblioteca')
    check(blocked[0] == 303 and blocked[1]['Location'].endswith('/minha-conta'), 'Administrador sem 2FA é levado à Minha conta')
    check(b'data-two-factor-required' in admin.request('/minha-conta')[2], 'Minha conta exige ativar a validação em 2 etapas')
    helper('two-factor', enabled='1')
    check(admin.request('/biblioteca')[0] == 200, 'Administrador volta a acessar após ativar 2FA')
    stray = test_portal.Client(deploy.SITE)
    stray_check = stray.request('/entrar/verificacao')
    check(stray_check[0] == 303 and stray_check[1]['Location'].endswith('/entrar'), 'Verificação sem login pendente volta ao login')
    token = admin.csrf()
    member_token = member.csrf()
    status, headers, _ = admin.request('route=create-subject', {'csrf': token, 'name': prefix, 'color': 'teal'})
    check(status == 303, 'Criação de matéria em MariaDB')
    subject = int(re.search(r'/materias/([0-9]+)$', headers['Location']).group(1))
    body = admin.request('route=edit-subject&id=' + str(subject))[2]
    revision = re.search(rb'name="revision" value="(\d+)"', body).group(1).decode()
    check(admin.request('route=update-subject', {'csrf': token, 'id': subject, 'revision': revision, 'name': prefix + ' revisada', 'color': 'blue'})[0] == 303, 'Edição de matéria em MariaDB')
    check(member.request('route=edit-subject&id=' + str(subject))[0] == 403, 'Estudante não gerencia matérias')
    page = admin.request('route=subject&id=' + str(subject))[2]
    check(b'data-max-total-bytes=' in page and b'data-upload-count' in page, 'Interface anuncia limites e envia contagem do lote')
    check(b'data-open="video-add-dialog"' in page, 'Administrador pode adicionar vídeos à matéria')
    folder_values = {'csrf': token, 'subject_id': subject, 'name': prefix + ' pasta'}
    check(member.request('/pastas/criar', dict(folder_values, csrf=member_token))[0] == 403, 'Estudante não cria pastas')
    check(admin.request('/pastas/criar', dict(folder_values, csrf='invalid'))[0] == 403, 'Pastas exigem CSRF válido')
    check(admin.request('/pastas/criar', folder_values)[0] == 303, 'Criação de pasta em MariaDB')
    folder_page = admin.request('/materias/' + str(subject))[2]
    folder_id = int(re.search(rb'data-folder-row="(\d+)"', folder_page).group(1))
    check(admin.request('/pastas/criar', folder_values)[0] == 400, 'Nome de pasta duplicado recusado em MariaDB')
    folder_edit = admin.request('/pastas/' + str(folder_id) + '/editar')[2]
    folder_revision = re.search(rb'name="revision" value="(\d+)"', folder_edit).group(1).decode()
    folder_remove = {'csrf': token, 'id': folder_id, 'revision': folder_revision, 'confirm': 1}
    check(admin.request('/pastas/atualizar', {'csrf': token, 'id': folder_id, 'revision': folder_revision, 'name': prefix + ' pasta', 'parent_id': folder_id})[0] == 400, 'Ciclo na árvore recusado em MariaDB')
    video_values = {'csrf': token, 'subject_id': subject, 'title': prefix + ' aula', 'url': 'https://youtu.be/aqz-KE-bpKQ'}
    check(member.request('/videos/criar', dict(video_values, csrf=member_token))[0] == 403, 'Estudante não adiciona vídeos')
    check(admin.request('/videos/criar', dict(video_values, csrf='invalid'))[0] == 403, 'Vídeos exigem CSRF válido')
    check(admin.request('/videos/criar', dict(video_values, url='https://example.com/video'))[0] == 400, 'Vídeos recusam links fora do YouTube')
    check(admin.request('/videos/criar', video_values)[0] == 303, 'Adição de vídeo em MariaDB')
    status, headers, video_page = member.request('/materias/' + str(subject))
    check(status == 200 and b'data-video-id="aqz-KE-bpKQ"' in video_page, 'Estudante vê o vídeo da matéria')
    check(b'video-add-dialog' not in video_page and b'/videos/mover' not in video_page, 'Estudante vê vídeos sem controles de gestão')
    check('https://www.youtube-nocookie.com' in headers.get('Content-Security-Policy', ''), 'CSP permite o player do YouTube')
    video_page = admin.request('/materias/' + str(subject))[2]
    video_id = int(re.search(rb'/videos/(\d+)/editar', video_page).group(1))
    video_edit = admin.request('/videos/' + str(video_id) + '/editar')[2]
    video_revision = re.search(rb'name="revision" value="(\d+)"', video_edit).group(1).decode()
    video_changes = {'csrf': token, 'id': video_id, 'revision': video_revision, 'title': prefix + ' revisada', 'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw'}
    check(admin.request('/videos/atualizar', video_changes)[0] == 303, 'Edição de vídeo em MariaDB')
    check(admin.request('/videos/atualizar', video_changes)[0] == 409, 'Vídeos recusam formulário desatualizado')
    check(b'data-video-id="jNQXAC9IVRw"' in member.request('/materias/' + str(subject))[2], 'Link atualizado aparece para estudantes')
    check(admin.request('/videos/criar', video_values)[0] == 303, 'Segundo vídeo adicionado para reordenação')
    check(admin.request('/videos/mover', {'csrf': token, 'id': video_id, 'direction': 'down'})[0] == 303, 'Reordenação de vídeos em MariaDB')
    video_page = member.request('/materias/' + str(subject))[2]
    check(video_page.index(b'data-video-id="aqz-KE-bpKQ"') < video_page.index(b'data-video-id="jNQXAC9IVRw"'), 'Estudante vê os vídeos na nova ordem')
    video_remove = {'csrf': token, 'id': video_id, 'revision': int(video_revision) + 1, 'confirm': 1}
    check(admin.request('/videos/excluir', video_remove)[0] == 303, 'Remoção de vídeo em MariaDB')
    check(admin.request('/videos/' + str(video_id) + '/editar')[0] == 404, 'Vídeo removido deixa de estar disponível')
    files = [('verificacao-a.txt', 'text/plain', b'Verificacao A'), ('verificacao-b.txt', 'text/plain', b'Verificacao B')]
    check(admin.upload(token, subject, files)[0] == 303, 'Upload múltiplo completo')
    check(admin.multipart('route=upload', {'csrf': token, 'subject_id': subject, 'expected_files': 3}, [('faltante.txt', 'text/plain', b'Teste')], 'documents[]')[0] == 400, 'Upload incompleto recusado em produção')
    page = admin.request('route=subject&id=' + str(subject))[2]
    ids = list(dict.fromkeys(int(value) for value in re.findall(rb'data-material-row="(\d+)"', page)))
    check(len(ids) == 2, 'Lote inválido não adicionou materiais')
    material = ids[0]
    edit = admin.request('route=edit-material&id=' + str(material))[2]
    revision = re.search(rb'name="revision" value="(\d+)"', edit).group(1).decode()
    check(member.request('route=update-material', {'csrf': member_token, 'id': material, 'revision': revision, 'title': 'Não alterar', 'subject_id': subject})[0] == 403, 'Estudante não altera material')
    new_bytes = b'Verificacao da substituicao'
    values = {'csrf': token, 'id': material, 'revision': revision, 'title': 'Verificacao atualizada', 'subject_id': subject, 'folder_id': folder_id, 'kind': 'prova'}
    check(admin.multipart('route=update-material', values, [('substituido.txt', 'text/plain', new_bytes)])[0] == 303, 'Substituição de material')
    check(admin.request('/pastas/excluir', folder_remove)[0] == 400, 'Pasta com arquivo ativo não pode ser excluída em MariaDB')
    folder_page = member.request('/pastas/' + str(folder_id))[2]
    check(b'data-material-row="' + str(material).encode() + b'"' in folder_page, 'Estudante navega até arquivo movido para pasta')
    check(b'kind-badge' in folder_page, 'Categoria Prova aparece no arquivo movido')
    category_page = member.request('/materias/' + str(subject) + '?categoria=provas')[2]
    check(b'data-material-row="' + str(material).encode() + b'"' in category_page and b'folder-column' in category_page, 'Categoria consulta toda a matéria em MariaDB')
    check(b'id="videos"' not in category_page and b'id="videos"' not in folder_page, 'Vídeos ficam somente na raiz sem filtro')
    check(member.request('route=file&id=' + str(material) + '&download=1')[2] == new_bytes, 'Download conserva os bytes da substituição')
    check(admin.request('route=update-material', values)[0] == 409, 'Formulário antigo é recusado')
    edit = admin.request('route=edit-material&id=' + str(material))[2]
    revision = re.search(rb'name="revision" value="(\d+)"', edit).group(1).decode()
    check(admin.request('route=delete-material', {'csrf': token, 'id': material, 'revision': revision, 'confirm': 1})[0] == 303, 'Exclusão de material temporário')
    check(member.request('route=file&id=' + str(material))[0] == 404, 'Material excluído fica indisponível')
    check(admin.request('/pastas/excluir', folder_remove)[0] == 303, 'Arquivo excluído logicamente não bloqueia exclusão da pasta em MariaDB')
    check(member.request('/pastas/' + str(folder_id))[0] == 404, 'Pasta removida deixa de estar disponível')
    edit = admin.request('route=edit-subject&id=' + str(subject))[2]
    revision = re.search(rb'name="revision" value="(\d+)"', edit).group(1).decode()
    event_values = {'csrf': member_token, 'title': prefix + ' evento privado', 'description': 'Agenda verificada', 'event_date': datetime.now(timezone(timedelta(hours=-3))).date().isoformat(), 'all_day': '1', 'priority': 'urgente', 'subject_id': subject, 'category': 'faculdade'}
    check(member.request('/agenda/eventos/criar', dict(event_values, category=''))[0] == 400, 'Categoria obrigatória ao cadastrar evento')
    check(member.request('/agenda/eventos/criar', dict(event_values, category='pessoal'))[0] == 400, 'Agenda recusa categoria fora das sete opções educacionais')
    check(member.request('/agenda/eventos/criar', dict(event_values, csrf='invalid'))[0] == 403, 'Agenda exige CSRF válido')
    event_response = member.request('/agenda/eventos/criar', event_values)
    check(event_response[0] == 303, 'Estudante cria evento privado em MariaDB')
    event_id = int(event_response[1]['Location'].rsplit('/', 1)[1])
    event_path = '/agenda/eventos/' + str(event_id)
    check(admin.request(event_path)[0] == 404 and admin.request(event_path + '/editar')[0] == 404, 'Administrador não acessa evento de outra conta')
    event_changes = dict(event_values, id=event_id, revision=1, title=prefix + ' evento atualizado', category='certificacao')
    check(member.request('/agenda/eventos/atualizar', dict(event_changes, category=''))[0] == 400, 'Categoria obrigatória ao editar evento')
    check(admin.request('/agenda/eventos/atualizar', dict(event_changes, csrf=token))[0] == 404, 'Administrador não altera evento de outra conta')
    check(member.request('/agenda/eventos/atualizar', dict(event_changes, all_day='0', starts_at='15:00', ends_at='14:00'))[0] == 400, 'Agenda recusa intervalo de horário inválido')
    check(member.request('/agenda/eventos/atualizar', event_changes)[0] == 303, 'Estudante altera seu evento')
    check('Categoria: Certificação'.encode() in member.request(event_path)[2], 'Categoria atualizada persiste em MariaDB')
    check(member.request('/agenda/eventos/atualizar', event_changes)[0] == 409, 'Agenda recusa formulário desatualizado')
    notices = member.request('/notificacoes')[2]
    notification_ids = re.findall(rb'data-notification-id="(\d+)"', notices)
    check(len(set(notification_ids)) == 1, 'Evento de hoje gera uma única notificação')
    notice_id = int(notification_ids[0])
    check(re.findall(rb'data-notification-id="(\d+)"', member.request('/notificacoes')[2]) == notification_ids, 'Acessos repetidos não duplicam notificação')
    check(admin.request('/notificacoes/ler', {'csrf': token, 'id': notice_id})[0] == 404, 'Notificação de outra conta não pode ser lida')
    check(member.request('/notificacoes/ler', {'csrf': member_token, 'id': notice_id})[0] == 303, 'Dono marca notificação como lida')
    check(b'notification-count' not in member.request('/agenda')[2], 'Leitura remove contador de avisos pendentes')
    check(admin.request('route=delete-subject', {'csrf': token, 'id': subject, 'revision': revision, 'confirm': 1})[0] == 303, 'Exclusão de matéria preserva seus materiais')
    event_page = member.request(event_path)[2]
    check(b'Sem mat' in event_page and str(event_changes['title']).encode() in event_page, 'Excluir matéria preserva evento privado sem associação')
    check(member.request('/agenda/eventos/excluir', {'csrf': member_token, 'id': event_id, 'revision': 3, 'confirm': 1})[0] == 303, 'Dono exclui evento em MariaDB')
    check(member.request(event_path)[0] == 404 and b'data-notification-id=' not in member.request('/notificacoes')[2], 'Excluir evento remove seu aviso')
    linked_event_values = dict(event_values, subject_id='', all_day='0', starts_at='10:00', ends_at='11:00', title=prefix + ' evento das tarefas')
    linked_event_response = member.request('/agenda/eventos/criar', linked_event_values)
    check(linked_event_response[0] == 303, 'Evento de preparação para tarefas criado em MariaDB')
    linked_event = int(linked_event_response[1]['Location'].rsplit('/', 1)[1])
    task_values = dict(linked_event_values, event_id=linked_event, title=prefix + ' tarefa privada')
    check(member.request('/agenda/tarefas/criar', dict(task_values, csrf='bad'))[0] == 403, 'Tarefas exigem CSRF')
    check(admin.request('/agenda/tarefas/criar', dict(task_values, csrf=token))[0] == 404, 'Administrador não vincula tarefa ao evento alheio')
    task_response = member.request('/agenda/tarefas/criar', task_values)
    check(task_response[0] == 303, 'Tarefa aceita o mesmo horário do evento em MariaDB')
    task_id = int(task_response[1]['Location'].rsplit('/', 1)[1])
    task_path = '/agenda/tarefas/' + str(task_id)
    check(admin.request(task_path)[0] == 404 and admin.request(task_path + '/editar')[0] == 404, 'Tarefa privada não é acessível por outra conta')
    check(member.request(task_path)[0] == 200, 'Dono acessa sua tarefa')
    check(admin.request('/agenda/tarefas/estado', {'csrf': token, 'id': task_id, 'revision': 1, 'complete': 1})[0] == 404, 'Outra conta não conclui tarefa')
    check(member.request('/agenda/tarefas/estado', {'csrf': member_token, 'id': task_id, 'revision': 1, 'complete': 1})[0] == 303, 'Dono conclui tarefa em MariaDB')
    task_notices = member.request('/notificacoes')[2]
    check(not re.search(rb'<article class="notification-item unread"[^>]*data-notification-kind="task"', task_notices), 'Concluir tarefa encerra aviso pendente')
    check('1 de 1 concluídas'.encode() in member.request('/agenda/eventos/' + str(linked_event))[2], 'Evento mostra progresso das tarefas')
    check(member.request('/agenda/tarefas/estado', {'csrf': member_token, 'id': task_id, 'revision': 2, 'complete': 0})[0] == 303, 'Tarefa concluída pode ser reaberta')
    task_changes = dict(task_values, id=task_id, revision=3, title=prefix + ' tarefa revisada')
    check(member.request('/agenda/tarefas/atualizar', task_changes)[0] == 303, 'Dono edita tarefa em MariaDB')
    check(member.request('/agenda/tarefas/atualizar', task_changes)[0] == 409, 'Tarefa recusa formulário antigo')
    check(member.request('/agenda/eventos/excluir', {'csrf': member_token, 'id': linked_event, 'revision': 1, 'confirm': 1})[0] == 303, 'Evento com tarefa pode ser excluído')
    check(b'Tarefa avulsa' in member.request(task_path)[2], 'Excluir evento preserva tarefa como avulsa em MariaDB')
    check(member.request('/agenda/tarefas/excluir', {'csrf': member_token, 'id': task_id, 'revision': 5, 'confirm': 1})[0] == 303, 'Dono exclui tarefa em MariaDB')
    check(member.request(task_path)[0] == 404, 'Tarefa excluída deixa de estar acessível')
    standalone = member.request('/agenda/tarefas/criar', dict(task_values, event_id=''))
    check(standalone[0] == 303, 'Tarefa avulsa pode ser criada diretamente')
    standalone_id = int(standalone[1]['Location'].rsplit('/', 1)[1])
    check(member.request('/agenda/tarefas/excluir', {'csrf': member_token, 'id': standalone_id, 'revision': 1, 'confirm': 1})[0] == 303, 'Limpeza da tarefa avulsa pela aplicação')
    survivor = next(value for value in ids if value != material)
    check(member.request('route=view&id=' + str(survivor))[0] == 200, 'Material sem matéria conserva seu link')
    check(member.request('route=file&id=' + str(survivor) + '&download=1')[2] in [item[2] for item in files], 'Material preservado conserva seu conteúdo')
    guest = test_portal.Client(deploy.SITE)
    guest.request('route=view&id=' + str(survivor))
    check(guest.login(fixture['member_login'], password)[1]['Location'].endswith('/materiais/' + str(survivor)), 'Login retoma o material em produção')
    check(member.multipart('route=update-photo', {'csrf': member_token, 'action': 'upload'}, [('foto.png', 'image/png', test_portal.photo_png())], 'photo')[0] == 303, 'Foto temporária pode ser enviada')
    check(member.request('route=photo')[2] == test_portal.photo_png(), 'Foto temporária é servida corretamente')
    check(member.request('route=update-photo', {'csrf': member_token, 'action': 'remove'})[0] == 303, 'Foto temporária removida')
    manifest = json.loads((ROOT / 'portal/import-manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files'][:1]:
        check(member.request('/' + urllib.parse.quote(item['stored_path']))[0] == 200, 'Material legado continua acessível após autenticação')
    verify_my_day(admin, member, token, member_token, prefix, check)
    verify_recurrence(helper, admin, member, token, member_token, prefix, check, fixture['member_login'], password)
    verify_content_links(helper, admin, member, token, member_token, prefix, check)
    verify_study(admin, member, token, member_token, prefix, check)
    verify_notes(admin, member, token, member_token, prefix, check)
    verify_invitations(helper, admin, member, token, member_token, prefix, check, fixture, password)
    return checks


def verify_invitations(helper, admin, member, admin_token, member_token, prefix, check, fixture, password):
    values=dict(csrf=member_token,title=prefix+' convite',description='Evento compartilhado por convite',event_date='2032-01-31',all_day='1',category='curso',priority='media',subject_id='')
    response=member.request('/agenda/eventos/criar',values)
    check(response[0]==303,'Evento temporário para convites criado')
    event=int(response[1]['Location'].rsplit('/',1)[1])
    body=member.request('/agenda/convidar?event_id='+str(event)+'&q='+urllib.parse.quote(fixture['admin_login']))[2]
    options=re.search(rb'<select name="recipient_ids\[\]"[^>]*>(.*?)</select>',body,re.S).group(1)
    recipient=int(re.search(rb'<option value="(\d+)"',options).group(1))
    check(admin.request('/agenda/convidar?event_id='+str(event))[0]==404,'Seleção de convidados protege evento em produção')
    send=dict(csrf=member_token,event_id=event,revision=1,**{'recipient_ids[]':[str(recipient)]})
    def send_request(options):
        return member.request('/convites/enviar',urllib.parse.urlencode(options,doseq=True).encode())
    check(send_request(dict(send,csrf='invalid'))[0]==403,'Convites exigem CSRF em produção')
    check(send_request(send)[0]==303,'Convite enviado em MariaDB')
    check(send_request(send)[0]==303,'Envio repetido é idempotente em MariaDB')
    rows=[r for r in helper('recurrences')['invitations'] if r['source_event_id'] is not None and int(r['source_event_id'])==event]
    check(len(rows)==1,'Índice impede convite duplicado por versão em produção')
    invite=rows[0]; identifier=int(invite['id'])
    check(b'data-notification-kind="invitation"' in admin.request('/notificacoes')[2],'Destinatário recebe convite no sino e histórico')
    check(admin.request('/agenda/eventos/'+str(event))[0]==404,'Convite não libera agenda do remetente')
    check(admin.request('/notificacoes/convites/ler',dict(csrf=admin_token,id=identifier))[0]==303,'Aviso de convite pode ser lido')
    row=next(r for r in helper('recurrences')['invitations'] if int(r['id'])==identifier)
    check(row['state']=='pending','Ler aviso não aceita convite em produção')
    twin=test_portal.Client(deploy.SITE); twin.trust(*fixture['admin_trusted'])
    check(twin.login(fixture['admin_login'],password)[0]==303,'Segunda sessão do destinatário autentica para concorrência')
    twin_token=twin.csrf()
    data=dict(csrf=admin_token,id=identifier,revision=1,choice='accepted')
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda pair: pair[0].request('/convites/responder',dict(data,csrf=pair[1]))[0],[(admin,admin_token),(twin,twin_token)]))
    check(statuses==[303,303],'Aceitação concorrente idempotente em MariaDB')
    records=helper('recurrences'); invite=next(r for r in records['invitations'] if int(r['id'])==identifier)
    copy=int(invite['accepted_event_id'])
    accepted=next(r for r in records['events'] if int(r['id'])==copy)
    check(int(accepted['user_id'])==recipient and accepted['recurrence_id'] is None,'Aceite cria ocorrência avulsa do destinatário')
    check(len([r for r in records['events'] if int(r['user_id'])==recipient and r['title']==values['title']])==1,'Aceites simultâneos criam somente uma cópia')
    check(member.request('/convites/responder',dict(data,csrf=member_token))[0]==404,'Remetente não responde em nome do destinatário')
    check(admin.request('/minha-conta/email',dict(csrf=admin_token,email=fixture['admin_email']))[0]==303,'Contato atual mantido sem envio de e-mail em MariaDB')
    check(fixture['admin_email'].encode() not in member.request('/agenda/convidar?event_id='+str(event))[2],'Seleção não divulga contato do destinatário')
    check(admin.request('/minha-conta/email',dict(csrf=admin_token,email='invalid'))[0]==400,'Contato inválido recusado em produção')
    # Uma versão nova produz convite próprio; alteração posterior cancela somente pendentes.
    check(member.request('/agenda/eventos/atualizar',dict(values,id=event,revision=1,title=prefix+' convite atualizado'))[0]==303,'Evento original editado depois de aceite')
    check(admin.request('/agenda/eventos/'+str(copy))[2].find(values['title'].encode())>=0,'Cópia aceita permanece independente em produção')
    check(send_request(dict(send,revision=2))[0]==303,'Nova versão pode ser convidada em MariaDB')
    pending=next(r for r in helper('recurrences')['invitations'] if r['source_event_id'] is not None and int(r['source_event_id'])==event and r['state']=='pending')
    check(member.request('/agenda/eventos/excluir',dict(csrf=member_token,id=event,revision=2,confirm=1))[0]==303,'Excluir origem cancela convite pendente')
    row=next(r for r in helper('recurrences')['invitations'] if int(r['id'])==int(pending['id']))
    check(row['state']=='canceled' and row['source_event_id'] is None,'Histórico de convite preservado ao excluir origem em MariaDB')
    check(admin.request('/convites/responder',dict(csrf=admin_token,id=pending['id'],revision=1,choice='accepted'))[0]==409,'Convite cancelado não pode ser aceito em produção')


def verify_notes(admin, member, admin_token, member_token, prefix, check):
    response=admin.request('/materias/criar',dict(csrf=admin_token,name=prefix+' notas',color='teal'))
    check(response[0]==303,'Matéria temporária para notas criada')
    subject=int(response[1]['Location'].rsplit('/',1)[1])
    values=dict(csrf=member_token,title=prefix+' anotação',body='Resumo privado\n<script>alert(1)</script>',subject_id=subject)
    response=member.request('/anotacoes/criar',values)
    check(response[0]==303,'Nota criada em MariaDB')
    note=int(response[1]['Location'].rsplit('/',1)[1])
    body=member.request('/anotacoes/'+str(note))[2]
    check(b'&lt;script&gt;alert(1)&lt;/script&gt;' in body and b'<script>alert(1)</script>' not in body,'HTML de nota escapado em produção')
    check(admin.request('/anotacoes/'+str(note))[0]==404,'Administrador não lê notas alheias em produção')
    updates=dict(values,id=note,revision=1,title=prefix+' nota editada')
    check(admin.request('/anotacoes/atualizar',dict(updates,csrf=admin_token))[0]==404,'Administrador não edita notas alheias em produção')
    check(b'data-note-count="0"' in admin.request('/materias/'+str(subject))[2],'Contagem de notas privada em produção')
    check(b'data-note-count="1"' in member.request('/materias/'+str(subject))[2],'Nota exibida dentro da matéria em produção')
    check(member.request('/anotacoes/atualizar',updates)[0]==303,'Nota editada em MariaDB')
    check(member.request('/anotacoes/importante',dict(csrf=member_token,id=note,important='1'))[0]==303,'Anotação marcada como importante em MariaDB')
    listed=json.loads(member.request('/anotacoes/dados?page=1&size=12')[2])
    check(listed['data'] and listed['data'][0]['id']==note and listed['data'][0]['important'] is True and listed['last_page']>=1,'Dados JSON listam a importante primeiro em MariaDB')
    check(note not in [row['id'] for row in json.loads(admin.request('/anotacoes/dados?page=1&size=12')[2])['data']],'Dados JSON de anotações não vazam para outro usuário em produção')
    check(member.request('/anotacoes/importante',dict(csrf=member_token,id=note,important='0'))[0]==303,'Importância removida em MariaDB')
    check(member.request('/anotacoes/atualizar',updates)[0]==409,'Nota recusa formulário antigo em produção')
    check(member.request('/anotacoes/criar',dict(values,title=prefix+' Unicode',body='\U0001f4da'*20000))[0]==303,'MariaDB aceita 20 mil caracteres Unicode em nota')
    check(member.request('/anotacoes/criar',dict(values,body='x'*20001))[0]==400,'Nota aplica limite de conteúdo em produção')
    check(admin.request('/materias/excluir',dict(csrf=admin_token,id=subject,revision=1,confirm=1))[0]==303,'Excluir matéria preserva notas pessoais em MariaDB')
    check(b'Sem mat\xc3\xa9ria' in member.request('/anotacoes/'+str(note))[2],'Nota preservada continua acessível em produção')
    check(member.request('/anotacoes/atualizar',dict(updates,revision=2,subject_id=''))[0]==409,'Nota preservada rejeita revisão anterior à exclusão da matéria')
    check(member.request('/anotacoes/atualizar',dict(updates,revision=3,subject_id='',body='Preservada'))[0]==303,'Nota sem matéria pode ser editada em produção')
    check(member.request('/anotacoes/excluir',dict(csrf=member_token,id=note,revision=4,confirm=1))[0]==303,'Dono exclui nota em MariaDB')
    check(member.request('/anotacoes/'+str(note))[0]==404,'Nota excluída indisponível em produção')


def verify_study(admin, member, admin_token, member_token, prefix, check):
    response=admin.request('/materias/criar',dict(csrf=admin_token,name=prefix+' estudo',color='blue'))
    check(response[0]==303,'Matéria temporária para estudo criada')
    subject=int(response[1]['Location'].rsplit('/',1)[1])
    def progress(client):
        body=client.request('/materias/'+str(subject))[2]
        return {kind.decode():(int(done),int(total)) for kind,done,total in re.findall(rb'data-study-progress="([^"]+)" data-study-done="(\d+)" data-study-total="(\d+)"',body)}
    check(progress(member)['all']==(0,0),'Matéria vazia sem progresso inventado em produção')
    check(admin.upload(admin_token,subject,[('estudo.txt','text/plain',b'Estudo temporario')])[0]==303,'Arquivo de estudo criado em MariaDB')
    file=int(re.search(rb'data-material-row="(\d+)"',member.request('/materias/'+str(subject))[2]).group(1))
    check(admin.request('/videos/criar',dict(csrf=admin_token,subject_id=subject,title=prefix+' estudo em vídeo',url='https://youtu.be/aqz-KE-bpKQ'))[0]==303,'Vídeo de estudo criado em MariaDB')
    video=int(re.search(rb'/videos/(\d+)/editar',admin.request('/materias/'+str(subject))[2]).group(1))
    data=dict(csrf=member_token,type='file',id=file,studied='1',content_revision=1)
    check(member.request('/estudo/marcar',dict(data,csrf='invalid'))[0]==403,'Estudo exige CSRF em produção')
    check(member.request('/estudo/marcar',data)[0]==303,'Material marcado em MariaDB')
    check(member.request('/estudo/marcar',data)[0]==303,'Repetição da marcação é idempotente em MariaDB')
    check(progress(member)['all']==(1,2),'Total combinado de estudo atualizado')
    check(progress(admin)['all']==(0,2),'Administrador vê somente seu progresso')
    check(admin.request('/estudo/marcar',dict(data,csrf=admin_token))[0]==303,'Outra conta marca o mesmo arquivo independentemente')
    check(member.request('/estudo/marcar',dict(data,type='video',id=video))[0]==303,'Vídeo marcado como assistido em MariaDB')
    check(progress(member)==dict(file=(1,1),video=(1,1),all=(2,2)),'Totais separados e combinados conferidos em produção')
    check(member.request('/estudo/marcar',dict(data,studied='0'))[0]==303,'Desmarcar material em produção')
    check(progress(admin)['file']==(1,1) and progress(member)['file']==(0,1),'Desmarcação preserva progresso de outra conta')
    check(member.request('/estudo/marcar',data)[0]==303,'Marca restaurada para substituição')
    edits=dict(csrf=admin_token,id=file,revision=1,title='Estudo substituído',subject_id=subject,folder_id='',kind='prova')
    check(admin.multipart('/materiais/atualizar',edits,[('substituido.txt','text/plain',b'Estudo substituido')])[0]==303,'Substituir conteúdo estudado em produção')
    check(progress(member)['file']==progress(admin)['file']==(0,1),'Substituição reinicia todas as marcações em MariaDB')
    check(member.request('/estudo/marcar',data)[0]==409,'Formulário anterior à substituição é recusado')
    check(member.request('/estudo/marcar',dict(data,content_revision=2))[0]==303,'Novo conteúdo pode ser estudado')
    check(admin.request('/materiais/excluir',dict(csrf=admin_token,id=file,revision=2,confirm=1))[0]==303,'Excluir arquivo estudado em produção')
    check(progress(member)['file']==(0,0),'Conteúdo excluído sai dos totais de estudo')
    check(admin.request('/videos/excluir',dict(csrf=admin_token,id=video,revision=1,confirm=1))[0]==303,'Excluir vídeo estudado em produção')
    check(progress(member)['all']==(0,0),'Exclusão de vídeo limpa marcação e totais em MariaDB')


def verify_content_links(helper, admin, member, admin_token, member_token, prefix, check):
    response = admin.request('/materias/criar', dict(csrf=admin_token,name=prefix+' vínculos',color='teal'))
    check(response[0] == 303, 'Matéria temporária para vínculos criada')
    subject = int(response[1]['Location'].rsplit('/',1)[1])
    check(admin.upload(admin_token, subject, [('vinculo.txt','text/plain',b'Conteudo vinculado temporario')])[0] == 303, 'Arquivo temporário para vínculo enviado')
    body = member.request('/materias/'+str(subject))[2]
    file = int(re.search(rb'data-material-row="(\d+)"',body).group(1))
    check(admin.request('/videos/criar',dict(csrf=admin_token,subject_id=subject,title=prefix+' vídeo vinculado',url='https://youtu.be/aqz-KE-bpKQ'))[0] == 303, 'Vídeo temporário para vínculo criado')
    video = int(re.search(rb'/videos/(\d+)/editar',admin.request('/materias/'+str(subject))[2]).group(1))
    check(admin.request('/pastas/criar',dict(csrf=admin_token,subject_id=subject,name=prefix+' pasta vinculada'))[0] == 303, 'Pasta temporária para vínculo criada')
    folder = int(re.search(rb'data-folder-row="(\d+)"',member.request('/materias/'+str(subject))[2]).group(1))
    values = dict(csrf=member_token,title=prefix+' compromisso vinculado',description='',event_date='2032-01-31',all_day='1',priority='media',category='curso',subject_id='')
    response = member.request('/agenda/eventos/criar',values)
    check(response[0] == 303, 'Evento temporário para vínculos criado')
    event = int(response[1]['Location'].rsplit('/',1)[1])
    response = member.request('/agenda/tarefas/criar',dict(values,event_id=event))
    check(response[0] == 303, 'Tarefa temporária para vínculos criada')
    task = int(response[1]['Location'].rsplit('/',1)[1])
    def link_values(kind,id,type,content,action='add',**options):
        page = member.request('/agenda/conteudos?kind='+kind+'&item_id='+str(id))[2]
        revision = re.search(rb'name="revision" value="(\d+)"',page).group(1).decode()
        data = dict(csrf=member_token,kind=kind,id=id,type=type,content_id=content,action=action,revision=revision)
        series = re.search(rb'name="recurrence_revision" value="(\d+)"',page)
        if series: data['recurrence_revision'] = series.group(1).decode()
        return dict(data,**options)
    for type, content in [('file',file),('video',video),('folder',folder)]:
        check(member.request('/agenda/conteudos/alterar',link_values('event',event,type,content))[0] == 303, type+' vinculado em MariaDB')
    check(member.request('/agenda/conteudos/alterar',link_values('task',task,'file',file))[0] == 303, 'Vínculo próprio de tarefa em MariaDB')
    body = member.request('/agenda/tarefas/'+str(task))[2]
    check(body.count(b'class="content-link-row"') == 4 and 'Conteúdos do evento'.encode() in body, 'Tarefa mostra vínculos próprios e herdados em produção')
    check(admin.request('/agenda/conteudos?kind=event&item_id='+str(event))[0] == 404, 'Administrador não lê vínculos alheios em produção')
    data = link_values('event',event,'file',file)
    check(admin.request('/agenda/conteudos/alterar',dict(data,csrf=admin_token))[0] == 404, 'Administrador não altera vínculos alheios em produção')
    check(member.request('/agenda/conteudos/alterar',dict(data,csrf='invalid'))[0] == 403, 'Vínculos exigem CSRF em produção')
    check(member.request('/agenda/conteudos/alterar',data)[0] == 303, 'Adição repetida aceita sem duplicação em produção')
    check(member.request('/agenda/eventos/'+str(event))[2].count(b'class="content-link-row"') == 3, 'Índices de vínculos impedem duplicação em MariaDB')
    data = link_values('event',event,'file',file,'remove')
    check(member.request('/agenda/conteudos/alterar',data)[0] == 303, 'Remoção de vínculo em produção')
    check(member.request('/agenda/conteudos/alterar',data)[0] == 409, 'Vínculos recusam revisão antiga em produção')
    check(member.request('/materiais/'+str(file)+'/download')[2] == b'Conteudo vinculado temporario', 'Remover vínculo conserva bytes do arquivo')
    check(member.request('/agenda/conteudos/alterar',link_values('event',event,'file',file))[0] == 303, 'Vínculo restaurado para testar cópia recorrente')
    revision = link_values('event',event,'file',file)['revision']
    check(member.request('/agenda/eventos/atualizar',dict(values,id=event,revision=revision,recurrence='monthly',recurrence_interval=1,recurrence_count=3,recurrence_key=secrets.token_hex(16)))[0] == 303, 'Evento com conteúdo e tarefas vira recorrente em MariaDB')
    records = helper('recurrences')
    series = next(r['recurrence_id'] for r in records['events'] if int(r['id']) == event)
    events = [r for r in records['events'] if r['recurrence_id'] == series]
    tasks = [r for r in records['tasks'] if r['recurrence_id'] == series]
    check(len(events) == len(tasks) == 3, 'Série vinculada possui três eventos e tarefas em MariaDB')
    for record in events:
        check(member.request('/agenda/eventos/'+str(record['id']))[2].count(b'class="content-link-row"') == 3, 'Ocorrência copia todos os vínculos em produção')
    for record in tasks:
        check(member.request('/agenda/tarefas/'+str(record['id']))[2].count(b'class="content-link-row"') == 4, 'Tarefa recorrente copia vínculos próprios e mostra herdados')
    check(member.request('/agenda/conteudos/alterar',link_values('event',event,'file',file,'remove',recurrence_scope='all'))[0] == 303, 'Alcance da série aplica vínculos em MariaDB')
    check(all(member.request('/agenda/eventos/'+str(r['id']))[2].count(b'class="content-link-row"') == 2 for r in events), 'Remoção de série alcançou as três ocorrências')
    check(admin.request('/videos/excluir',dict(csrf=admin_token,id=video,revision=1,confirm=1))[0] == 303, 'Excluir vídeo limpa suas referências em MariaDB')
    check(admin.request('/pastas/excluir',dict(csrf=admin_token,id=folder,revision=1,confirm=1))[0] == 303, 'Excluir pasta limpa suas referências em MariaDB')
    check(member.request('/agenda/eventos/'+str(event))[0] == 200, 'Exclusão de conteúdo preserva evento em produção')


def verify_my_day(admin, member, admin_token, member_token, prefix, check):
    """Use only publication fixtures; cleanup() removes all their records."""
    def counts(body):
        return {key.decode(): int(value) for key, value in re.findall(rb'data-my-day-count="([^"]+)">([0-9]+)', body)}
    today = datetime.now(timezone(timedelta(hours=-3))).date()
    status, _, body = member.request('/meu-dia')
    check(status == 200 and counts(body) == dict(eventos=0, tarefas=0, atrasadas=0, proximos=0), 'Meu dia vazio disponível em MariaDB')
    check(member.request('/meu-dia', dict(csrf=member_token))[0] == 405, 'Meu dia exige GET em produção')
    values = dict(csrf=member_token, title=prefix + ' painel', description='', event_date=str(today), all_day='1', priority='media', category='curso', subject_id='', event_id='')
    today_tasks = []
    for i in range(12):
        response = member.request('/agenda/tarefas/criar', dict(values, title=prefix + ' painel hoje ' + str(i).zfill(2)))
        if response[0] != 303: raise RuntimeError('Falha ao preparar tarefa de teste do painel')
        today_tasks.append(int(response[1]['Location'].rsplit('/', 1)[1]))
    check(len(today_tasks) == 12, 'Tarefas de teste do painel criadas em MariaDB')
    past_values = dict(values, title=prefix + ' painel atrasada', event_date=str(today - timedelta(days=1)), all_day='0', starts_at='10:00', ends_at='11:00')
    check(member.request('/agenda/tarefas/criar', past_values)[0] == 303, 'Tarefa atrasada do painel criada em MariaDB')
    check(member.request('/agenda/eventos/criar', dict(values, title=prefix + ' painel evento hoje'))[0] == 303, 'Evento de hoje do painel criado em MariaDB')
    check(member.request('/agenda/eventos/criar', dict(values, title=prefix + ' painel limite sete', event_date=str(today + timedelta(days=7))))[0] == 303, 'Evento no sétimo dia criado em MariaDB')
    check(member.request('/agenda/tarefas/criar', dict(values, title=prefix + ' painel tarefa sete', event_date=str(today + timedelta(days=7))))[0] == 303, 'Tarefa no sétimo dia criada em MariaDB')
    check(member.request('/agenda/eventos/criar', dict(values, title=prefix + ' painel fora oito', event_date=str(today + timedelta(days=8))))[0] == 303, 'Evento fora da janela criado para conferir limite')
    body = member.request('/meu-dia')[2]
    check(counts(body) == dict(eventos=1, tarefas=12, atrasadas=1, proximos=2), 'Meu dia calcula contagens privadas em MariaDB')
    today_section = body.split(b'id="tarefas"', 1)[1].split(b'</section>', 1)[0]
    check(today_section.count(b'data-task-row=') == 10, 'Meu dia limita primeira página em MariaDB')
    second = member.request('/meu-dia?tarefas=2')[2].split(b'id="tarefas"', 1)[1].split(b'</section>', 1)[0]
    check(second.count(b'data-task-row=') == 2, 'Meu dia pagina os demais registros em MariaDB')
    check((prefix + ' painel limite sete').encode() in body and (prefix + ' painel tarefa sete').encode() in body and (prefix + ' painel fora oito').encode() not in body, 'Meu dia inclui sétimo dia e exclui oitavo em produção')
    private_admin = admin.request('/meu-dia')[2]
    check(counts(private_admin) == dict(eventos=0, tarefas=0, atrasadas=0, proximos=0) and (prefix + ' painel').encode() not in private_admin, 'Meu dia não expõe listas ou contagens ao administrador')
    task = today_tasks[-1]
    state = dict(csrf=member_token, id=task, revision=1, complete=1, return_to='/meu-dia?tarefas=2')
    check(member.request('/agenda/tarefas/estado', dict(state, csrf='bad'))[0] == 403, 'Conclusão pelo painel exige CSRF em produção')
    check(admin.request('/agenda/tarefas/estado', dict(state, csrf=admin_token))[0] == 404, 'Administrador não conclui tarefa do painel alheio')
    response = member.request('/agenda/tarefas/estado', state)
    check(response[0] == 303 and response[1]['Location'] == state['return_to'], 'Conclusão retorna à página do painel em produção')
    body = member.request('/meu-dia')[2]
    check(counts(body)['tarefas'] == 11 and b'id="concluidas"' in body, 'Painel retira concluída das pendências e permite reabrir')
    check(member.request('/agenda/tarefas/estado', state)[0] == 409, 'Painel recusa conclusão com revisão antiga em produção')
    check(member.request('/agenda/tarefas/estado', dict(state, revision=2, complete=0))[0] == 303 and counts(member.request('/meu-dia')[2])['tarefas'] == 12, 'Painel reabre tarefa e atualiza contagem em MariaDB')


def verify_recurrence(helper, admin, member, admin_token, member_token, prefix, check, login, password):
    values = dict(csrf=member_token, title=prefix + ' repetição', description='Teste de recorrência', event_date='2032-01-31', all_day='1', priority='media', category='curso', subject_id='', recurrence='monthly', recurrence_interval=1, recurrence_count=3, recurrence_key=secrets.token_hex(16))
    check(member.request('/agenda/eventos/criar', dict(values, recurrence_count=121))[0] == 400, 'Recorrência limita quantidade em MariaDB')
    check(member.request('/agenda/eventos/criar', dict(values, csrf='bad'))[0] == 403, 'Recorrência exige CSRF em produção')
    twin = test_portal.Client(deploy.SITE)
    check(twin.login(login, password)[0] == 303, 'Segunda sessão da mesma conta autentica para testar concorrência')
    twin_token = twin.csrf()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.request, '/agenda/eventos/criar', dict(values, csrf=token)) for client, token in [(member,member_token),(twin,twin_token)]]
        responses = [future.result() for future in futures]
    check(all(r[0] == 303 for r in responses) and responses[0][1]['Location'] == responses[1][1]['Location'], 'Criação concorrente não duplica série em MariaDB')
    event = int(responses[0][1]['Location'].rsplit('/',1)[1])
    records = helper('recurrences')
    source = next(r for r in records['events'] if int(r['id']) == event)
    series = source['recurrence_id']
    events = sorted([r for r in records['events'] if r['recurrence_id'] == series], key=lambda r:r['occurrence_date'])
    check([r['event_date'] for r in events] == ['2032-01-31','2032-02-29','2032-03-31'], 'Mensal em MariaDB usa fevereiro bissexto e retoma dia 31')
    check(len([r for r in records['series'] if int(r['id']) == int(series)]) == 1, 'Chave de criação mantém uma única série em MariaDB')
    check(admin.request('/agenda/eventos/' + str(event))[0] == 404 and values['title'].encode() not in admin.request('/agenda?mes=2032-01')[2], 'Recorrência privada também diante de administrador em produção')
    task_values = dict(values, title=prefix + ' tarefa repetida', event_date='2032-01-29', event_id=event, recurrence='none', all_day='0', starts_at='08:00', ends_at='09:00')
    response = member.request('/agenda/tarefas/criar', task_values)
    check(response[0] == 303, 'Tarefa de evento recorrente criada em MariaDB')
    task = int(response[1]['Location'].rsplit('/',1)[1])
    tasks = sorted([r for r in helper('recurrences')['tasks'] if r['recurrence_id'] == series], key=lambda r:r['occurrence_date'])
    check(len(tasks) == 3 and [r['task_date'] for r in tasks] == ['2032-01-29','2032-02-27','2032-03-29'], 'Tarefas repetem com deslocamento próprio em MariaDB')
    check(all(r['starts_at'].startswith('08:00') and r['ends_at'].startswith('09:00') and r['completed_at'] is None for r in tasks), 'Cópias mantêm horários e começam pendentes em produção')
    check([int(r['event_id']) for r in tasks] == [int(r['id']) for r in events], 'Cada tarefa copiada pertence à sua ocorrência do evento')
    state = dict(csrf=member_token, id=task, revision=1, complete=1)
    check(member.request('/agenda/tarefas/estado',state)[0] == 303, 'Ocorrência de tarefa pode ser concluída em produção')
    tasks = [r for r in helper('recurrences')['tasks'] if r['recurrence_id'] == series]
    check(sum(r['completed_at'] is not None for r in tasks) == 1, 'Conclusão permanece individual em MariaDB')
    series_revision = next(r['revision'] for r in helper('recurrences')['series'] if int(r['id']) == int(series))
    update = dict(values, id=events[1]['id'], revision=1, recurrence='none', title=prefix + ' exceção', recurrence_scope='this', recurrence_revision=series_revision, event_date=events[1]['event_date'])
    check(member.request('/agenda/eventos/atualizar',update)[0] == 303, 'Edição individual de recorrência em produção')
    record = next(r for r in helper('recurrences')['events'] if int(r['id']) == int(events[1]['id']))
    check(int(record['recurrence_exception']) == 1, 'Exceção individual armazenada em MariaDB')
    series_revision = next(r['revision'] for r in helper('recurrences')['series'] if int(r['id']) == int(series))
    bulk = dict(update, id=event, event_date='2032-01-31', title=prefix + ' série editada', recurrence_scope='all', recurrence_revision=series_revision)
    check(member.request('/agenda/eventos/atualizar',dict(bulk,recurrence_revision=1))[0] == 409, 'Revisão antiga da série é recusada em produção')
    check(admin.request('/agenda/eventos/atualizar',dict(bulk,csrf=admin_token))[0] == 404, 'Outra conta não edita série em produção')
    check(member.request('/agenda/eventos/atualizar',bulk)[0] == 303, 'Edição da série em MariaDB')
    updated_events = sorted([r for r in helper('recurrences')['events'] if r['recurrence_id'] == series],key=lambda r:r['occurrence_date'])
    check([r['title'] for r in updated_events] == [bulk['title'],update['title'],bulk['title']], 'Edição da série preserva exceção em MariaDB')
    series_revision = next(r['revision'] for r in helper('recurrences')['series'] if int(r['id']) == int(series))
    deletion = dict(csrf=member_token,id=event,revision=updated_events[0]['revision'],confirm=1,recurrence_scope='following',recurrence_revision=series_revision)
    check(member.request('/agenda/eventos/excluir',deletion)[0] == 303, 'Exclusão desta e próximas em produção')
    remaining = [r for r in helper('recurrences')['events'] if r['recurrence_id'] == series]
    check(len(remaining) == 1 and int(remaining[0]['id']) == int(events[1]['id']), 'Exclusão de próximas preserva exceção em MariaDB')
    tasks = [r for r in helper('recurrences')['tasks'] if r['recurrence_id'] == series]
    check(sum(r['event_id'] is None for r in tasks) == 2 and len(tasks) == 3, 'Excluir eventos recorrentes preserva tarefas em produção')
    # All these records belong to the temporary users and are removed by cleanup.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--previous-rules', type=Path, help='Cópia conferida das regras anteriores, quando a atualização altera .htaccess')
    args = parser.parse_args()
    password = getpass.getpass('Senha FTP: ')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    payload = {path: (ROOT / path).read_bytes() for path in FILES}
    target_rules = (ROOT / '.htaccess').read_bytes()
    payload['.htaccess'] = target_rules
    report = {'site': deploy.SITE, 'published_at': stamp, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(), 'status': 'planned', 'sha256': {path: digest(data) for path, data in payload.items()}}
    report['uncommitted_application_files'] = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '--', *payload], cwd=ROOT).decode().splitlines()
    if report['uncommitted_application_files']:
        report['base_commit'] = report['commit']
        report['commit'] = None
    with ExitStack() as connections:
        ftp = connections.enter_context(deploy.connect(password))

        def reconnect():
            nonlocal ftp
            # HTTP tests can outlast the hosting provider's FTP idle timeout.
            ftp = connections.enter_context(deploy.connect(password))

        def read_remote(path):
            for attempt in range(3):
                try:
                    return deploy.remote_bytes(ftp, path)
                except (OSError, EOFError, ftplib.error_temp):
                    if attempt == 2:
                        raise
                    report.setdefault('read_retries', []).append(path)
                    print('FTPS_READ_RETRY', path, flush=True)
                    reconnect()

        def write_remote(path, data):
            # A hospedagem derruba a sessão após muitas transferências; STOR no mesmo destino pode ser repetido.
            for attempt in range(3):
                try:
                    return deploy.upload(ftp, path, data)
                except (OSError, EOFError, ftplib.error_temp):
                    if attempt == 2:
                        raise
                    report.setdefault('write_retries', []).append(path)
                    print('FTPS_WRITE_RETRY', path, flush=True)
                    reconnect()

        def optional_remote(path):
            try:
                return read_remote(path)
            except ftplib.error_perm as error:
                if str(error).startswith('550'):
                    return None
                raise

        before = {path: optional_remote(path) for path in FILES}
        root_rules = read_remote('.htaccess')
        if root_rules != target_rules and (args.previous_rules is None or args.previous_rules.read_bytes() != root_rules):
            raise RuntimeError('As regras da raiz diferem da cópia esperada. Nenhum arquivo foi alterado.')
        before['.htaccess'] = root_rules
        changed = [path for path in payload if before[path] != payload[path]]
        report['changed_files'] = changed
        report['previous_sha256'] = {path: digest(data) if data is not None else None for path, data in before.items()}
        print(json.dumps({'changed_files': changed, 'mode': 'publish' if args.publish else 'check_only'}), flush=True)
        if not args.publish:
            return
        backup = ROOT / 'artifacts/backups' / ('runtime-fixes-' + stamp)
        backup.mkdir(parents=True)
        for path, data in before.items():
            if data is not None:
                target = backup / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        (backup / '.htaccess').write_bytes(root_rules)
        report['backup'] = backup.relative_to(ROOT).as_posix()
        suffix = secrets.token_hex(12)
        pending = {path: path + '.pending-' + suffix for path in changed if path != '.htaccess'}
        migration_path = pending.get('portal/src/migrations.php', 'portal/src/migrations.php')
        helper_name = 'portal-update-' + suffix + '.php'
        token = secrets.token_hex(32)
        helper_rules = root_rules.replace(b'RewriteEngine On', b'RewriteEngine On\nRewriteRule ^' + helper_name.replace('.', '\\.').encode() + b'$ - [L]', 1)
        activated = []
        helper_installed = False
        rules_changed = False
        fixtures_possible = False
        completed = False

        def helper(action, **fields):
            status, _, body = deploy.http('/' + helper_name, dict(token=token, action=action, **fields))
            if status != 200:
                raise RuntimeError('Operação de atualização recusada (' + action + ', HTTP ' + str(status) + ').')
            return json.loads(body)

        try:
            for path in pending:
                write_remote(pending[path], payload[path])
                if digest(read_remote(pending[path])) != report['sha256'][path]:
                    raise RuntimeError('Hash do arquivo preparado não confere: ' + path)
            write_remote(helper_name, helper_source(token, migration_path, pending.get('portal/src/bootstrap.php', 'portal/src/bootstrap.php')))
            helper_installed = True
            write_remote('.htaccess', helper_rules)
            rules_changed = True
            baseline = helper('probe')
            report['baseline'] = baseline
            print('SERVER_SCHEMA_READY', baseline['schema_ready'], flush=True)
            maintenance = helper_rules.replace(b'RewriteEngine On', b'RewriteEngine On\nRewriteRule ^trabalho_datait(?:/|$) - [L]', 1)
            maintenance += b'\n'
            marker = b'RewriteRule ^' + helper_name.replace('.', '\\.').encode() + b'$ - [L]'
            maintenance = maintenance.replace(marker, marker + b'\nRewriteRule ^(?!portal/assets/|\\.well-known/acme-challenge/).* - [R=503,L]', 1)
            write_remote('.htaccess', maintenance)
            migration = helper('migrate')
            if not migration['schema_ready']:
                raise RuntimeError('O esquema não ficou compatível após a migração.')
            if migration['snapshot'] != baseline['snapshot']:
                raise RuntimeError('Os registros existentes mudaram durante a migração.')
            report['migration'] = migration
            if migration.get('classification') != baseline.get('classification'):
                raise RuntimeError('A classificação dos arquivos existentes mudou na migração.')
            second_migration = helper('migrate')
            if second_migration['applied'] or not second_migration['schema_ready'] or second_migration['snapshot'] != baseline['snapshot']:
                raise RuntimeError('A segunda migração não foi idempotente.')
            report['migration_second_run'] = second_migration
            for path in pending:
                if optional_remote(path) != before[path]:
                    raise RuntimeError('Arquivo remoto mudou após a comparação: ' + path)
                activated.append(path)
                ftp.rename(deploy.REMOTE + '/' + pending[path], deploy.REMOTE + '/' + path)
                if digest(read_remote(path)) != report['sha256'][path]:
                    raise RuntimeError('Hash publicado não confere: ' + path)
            active_helper_rules = target_rules.replace(b'RewriteEngine On', b'RewriteEngine On\nRewriteRule ^' + helper_name.replace('.', '\\.').encode() + b'$ - [L]', 1)
            write_remote('.htaccess', active_helper_rules)
            print('FILES_ACTIVATED', len(changed), flush=True)
            fixtures_possible = True
            report['checks'] = verify_features(helper, 'Verificacao ' + suffix)
            cleanup = helper('cleanup')
            fixtures_possible = False
            if cleanup['snapshot'] != baseline['snapshot']:
                raise RuntimeError('Os registros não coincidem após limpar os testes temporários.')
            report['after_cleanup'] = cleanup['snapshot']
            reconnect()
            for path in FILES:
                if digest(read_remote(path)) != report['sha256'][path]:
                    raise RuntimeError('Hash final não confere: ' + path)
            if read_remote('.htaccess') != active_helper_rules:
                raise RuntimeError('As regras ativas mudaram durante a verificação.')
            completed = True
            report['status'] = 'verified'
            print('PRODUCTION_CHECKS_PASSED', len(report['checks']), flush=True)
        except Exception:
            report['status'] = 'failed'
            if fixtures_possible:
                helper('cleanup')
                fixtures_possible = False
            reconnect()
            for path in reversed(activated):
                if before[path] is None:
                    ftp.delete(deploy.REMOTE + '/' + path)
                else:
                    write_remote(path, before[path])
            raise
        finally:
            reconnect()
            if rules_changed:
                final_rules = target_rules if completed else root_rules
                write_remote('.htaccess', final_rules)
                if read_remote('.htaccess') != final_rules:
                    raise RuntimeError('Não foi possível conferir a restauração das regras da raiz.')
            if helper_installed:
                ftp.delete(deploy.REMOTE + '/' + helper_name)
            for path in pending.values():
                try:
                    ftp.delete(deploy.REMOTE + '/' + path)
                except ftplib.error_perm as error:
                    if not str(error).startswith('550'):
                        raise
            report['temporary_endpoint_removed'] = helper_installed
            report['root_rules_restored'] = rules_changed
            (ROOT / 'artifacts/runtime-publication.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if completed:
            status, _, body = deploy.http('/entrar')
            if status != 200 or b'Entrar no portal' not in body:
                report['status'] = 'failed_public_check'
                (ROOT / 'artifacts/runtime-publication.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                raise RuntimeError('Login não ficou disponível após remover o verificador.')
            report['checks'].append('Login disponível após remover o verificador e restaurar as regras')
            (ROOT / 'artifacts/runtime-publication.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'status': report['status'], 'changed_files': len(changed), 'production_checks': len(report['checks']), 'backup': report['backup']}), flush=True)


if __name__ == '__main__':
    main()
