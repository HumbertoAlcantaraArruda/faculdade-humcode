<?php
declare(strict_types=1);

$requestPath = rawurldecode(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/');
$prefix = rtrim((string) config('base_path'), '/') . '/';
$relative = strpos($requestPath, $prefix) === 0 ? substr($requestPath, strlen($prefix)) : $requestPath;
$pathRoute = $relative === '' && array_key_exists('route', $_GET) ? null : route_from_path($relative);
if ($pathRoute !== null) {
    unset($_GET['route'], $_GET['id'], $_GET['legacy_path']);
    $_GET = array_merge($_GET, $pathRoute);
} elseif ($relative !== 'index.php' && $relative !== '') {
    $_GET['legacy_path'] = $relative;
}
$legacyPath = $_GET['legacy_path'] ?? null;
$routeValue = $_GET['route'] ?? 'home';
$route = is_string($routeValue) ? $routeValue : 'home';
if ($legacyPath !== null) { $route = 'legacy'; }
// Links antigos continuam válidos; somente GET recebe o endereço atualizado.
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($relative === 'index.php' || ($relative === '' && isset($_GET['route']))) && $legacyPath === null && isset(route_paths()[$route])) {
    header('Location: ' . url($route, $_GET), true, 308); exit;
}
if ($_SERVER['REQUEST_METHOD'] === 'POST' && empty($_POST) && (int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 0) {
    fail('O envio excedeu o limite total do servidor. Envie menos arquivos por vez.', 413);
}

if ($route === 'login') {
    if (current_user()) { redirect(); }
    $error = null;
    $login = '';
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_csrf();
        $login = strtolower(field('login', 100));
        $password = $_POST['password'] ?? '';
        if (!is_string($password) || strlen($password) > 1024) { fail('Dados de acesso inválidos.'); }
        // Limites independentes por conta e IP evitam tentativas distribuídas.
        $keys = [hash('sha256', 'account:' . $login), hash('sha256', 'ip:' . ($_SERVER['REMOTE_ADDR'] ?? ''))];
        $attempts = [];
        $blocked = false;
        foreach ($keys as $key) {
            $attempt = query('SELECT * FROM hc_portal_login_attempts WHERE attempt_key = ?', [$key])->fetch();
            $attempts[$key] = $attempt;
            if ($attempt && (int) $attempt['blocked_until'] > time()) { $blocked = true; }
        }
        if ($blocked) {
            http_response_code(429);
            header('Retry-After: 900');
            $error = 'Muitas tentativas. Aguarde 15 minutos para tentar novamente.';
        } else {
            $user = query('SELECT * FROM hc_portal_users WHERE login = ?', [$login])->fetch();
            $dummy = '$2y$10$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2uheWG/igi.';
            $valid = password_verify($password, $user ? $user['password_hash'] : $dummy);
            if (!$user || !$valid || !(int) $user['active']) {
                foreach ($keys as $key) {
                    $attempt = $attempts[$key];
                    $withinWindow = $attempt && time() - (int) $attempt['first_at'] < 900;
                    $count = $withinWindow ? (int) $attempt['failures'] + 1 : 1;
                    $first = $withinWindow ? (int) $attempt['first_at'] : time();
                    $threshold = $key === $keys[0] ? 8 : 25;
                    $until = $count >= $threshold ? time() + 900 : 0;
                    if ($attempt) { query('UPDATE hc_portal_login_attempts SET failures = ?, first_at = ?, blocked_until = ? WHERE attempt_key = ?', [$count, $first, $until, $key]); }
                    else { query('INSERT INTO hc_portal_login_attempts (attempt_key, failures, first_at, blocked_until) VALUES (?, ?, ?, ?)', [$key, $count, $first, $until]); }
                }
                $error = 'Usuário ou senha inválidos.';
                http_response_code(401);
            } else {
                foreach ($keys as $key) { query('DELETE FROM hc_portal_login_attempts WHERE attempt_key = ?', [$key]); }
                query('DELETE FROM hc_portal_login_attempts WHERE first_at < ? AND blocked_until < ?', [time() - 86400, time()]);
                if (password_needs_rehash($user['password_hash'], PASSWORD_DEFAULT)) { query('UPDATE hc_portal_users SET password_hash = ? WHERE id = ?', [password_hash($password, PASSWORD_DEFAULT), $user['id']]); }
                continue_login($user);
            }
        }
    } elseif ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_login($error, $login);
    exit;
}

if ($route === 'two-factor') { handle_two_factor_login(); }

$user = require_user();
if (!portal_schema_ready()) { fail('O portal está em atualização. Tente novamente em instantes.', 503); }
if ((int) $user['must_change_password'] && !in_array($route, ['password', 'logout', 'photo'], true)) { remember_destination(); redirect('password'); }
// Perfis obrigatórios (administradores) só acessam a Minha conta até ativar a validação em 2 etapas.
if (two_factor_required($user) && !two_factor_active($user) && !in_array($route, ['password', 'logout', 'photo', 'update-photo', 'save-email', 'two-factor-settings'], true)) { remember_destination(); redirect('password'); }

if ($route === 'photo') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    serve_profile_photo($user);
}
if ($route === 'update-photo') { post_only(); update_profile_photo($user); }

if ($route === 'logout') {
    post_only();
    $_SESSION = [];
    $cookie = session_get_cookie_params();
    setcookie(session_name(), '', ['expires' => time() - 3600, 'path' => $cookie['path'], 'secure' => $cookie['secure'], 'httponly' => true, 'samesite' => 'Lax']);
    session_destroy();
    redirect('login');
}
if ($route === 'password') {
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_csrf();
        $current = $_POST['current_password'] ?? '';
        if (!is_string($current) || !password_verify($current, $user['password_hash'])) { fail('A senha atual não confere.'); }
        $password = new_password();
        if ($password !== ($_POST['password_confirmation'] ?? null)) { fail('A confirmação da senha não confere.'); }
        if (password_verify($password, $user['password_hash'])) { fail('Escolha uma senha diferente da atual.'); }
        query('UPDATE hc_portal_users SET password_hash = ?, must_change_password = 0, session_version = session_version + 1 WHERE id = ?', [password_hash($password, PASSWORD_DEFAULT), $user['id']]);
        $_SESSION['session_version'] = (int) $user['session_version'] + 1;
        $_SESSION['csrf'] = bin2hex(random_bytes(32));
        session_regenerate_id(true);
        flash('Sua senha foi alterada.');
        redirect_to_destination();
    }
    render_password($user);
    exit;
}
if ($route === 'save-email') { post_only(); save_contact_email($user); }
if ($route === 'two-factor-settings') { post_only(); update_two_factor($user); }
if ($route === 'send-invitations') { post_only(); send_invitations($user); }
if ($route === 'answer-invitation') { post_only(); answer_invitation($user); }
if ($route === 'read-invitation') { post_only(); read_invitation_notice($user); }
if (in_array($route, ['invitations', 'view-invitation', 'invite-users'], true)) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    sync_invitation_states((int) $user['id']);
    if ($route === 'invitations') { render_invitations($user); }
    elseif ($route === 'invite-users') { render_invite_users(event_record(numeric_id($_GET['event_id'] ?? null), (int) $user['id'])); }
    else { render_invitation(invitation_record(numeric_id($_GET['id'] ?? null), (int) $user['id']), $user); }
    exit;
}
if ($route === 'notes') { if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); } render_notes($user); exit; }
if ($route === 'notes-data') { if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); } render_notes_data($user); exit; }
if ($route === 'toggle-note-important') { post_only(); toggle_note_important($user); }
if (in_array($route, ['new-note', 'view-note', 'edit-note'], true)) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    if ($route === 'new-note') { render_note_form(null); }
    else { $note = note_record(numeric_id($_GET['id'] ?? null), (int) $user['id']); if ($route === 'edit-note') { render_note_form($note); } else { render_note($note); } }
    exit;
}
if ($route === 'note-file' || $route === 'note-file-download') { if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); } serve_note_file($user, $route === 'note-file-download'); }
if ($route === 'create-note' || $route === 'update-note') { post_only(); save_note($user, $route === 'update-note'); }
if ($route === 'delete-note') { post_only(); delete_note($user); }
if ($route === 'add-note-files') { post_only(); add_note_files($user); }
if ($route === 'update-note-file' || $route === 'delete-note-file') { post_only(); change_note_file($user, $route === 'delete-note-file'); }
if ($route === 'study-state') { post_only(); change_study_state($user); }
if ($route === 'change-content-link') { post_only(); change_content_link($user); }
if ($route === 'commitment-content') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    $kind = $_GET['kind'] ?? '';
    if (!is_string($kind)) { fail('Selecione um compromisso válido.'); }
    render_commitment_content($kind, commitment_record($kind, numeric_id($_GET['item_id'] ?? null), (int) $user['id'])); exit;
}
if (in_array($route, ['new-task', 'view-task', 'edit-task'], true)) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    if ($route === 'new-task') { render_task_form($user, null); }
    else {
        $task = task_record(numeric_id($_GET['id'] ?? null), (int) $user['id']);
        if ($route === 'edit-task') { render_task_form($user, $task); } else { render_task($task); }
    }
    exit;
}
if ($route === 'create-task' || $route === 'update-task') { post_only(); save_task($user, $route === 'update-task'); }
if ($route === 'delete-task' || $route === 'set-task-status') { post_only(); change_task_state($user, $route === 'delete-task'); }
if ($route === 'read-task-notification') { post_only(); read_task_notification($user); }
if ($route === 'my-day') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_my_day($user); exit;
}
if (in_array($route, ['agenda', 'new-event', 'view-event', 'edit-event', 'notifications'], true)) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    if ($route === 'agenda') { render_agenda($user); }
    elseif ($route === 'notifications') { render_notifications($user); }
    elseif ($route === 'new-event') { render_event_form(null); }
    else {
        $event = event_record(numeric_id($_GET['id'] ?? null), (int) $user['id']);
        if ($route === 'edit-event') { render_event_form($event); } else { render_event($event); }
    }
    exit;
}
if ($route === 'create-event' || $route === 'update-event') { post_only(); save_event($user, $route === 'update-event'); }
if ($route === 'delete-event') { post_only(); delete_event($user); }
if ($route === 'read-notification') { post_only(); read_event_notification($user); }
if (in_array($route, ['create-subject', 'edit-subject', 'update-subject', 'delete-subject', 'upload', 'edit-material', 'update-material', 'delete-material', 'create-video', 'edit-video', 'update-video', 'delete-video', 'move-video', 'create-folder', 'edit-folder', 'update-folder', 'delete-folder'], true)) { require_admin(); }
if ($route === 'edit-folder') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_edit_folder(folder_record(numeric_id($_GET['id'] ?? null))); exit;
}
if ($route === 'create-folder') { post_only(); create_folder($user); }
if (in_array($route, ['update-folder', 'delete-folder'], true)) { post_only(); change_folder($route === 'delete-folder' ? 'delete' : 'update'); }
if ($route === 'edit-video') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_edit_video(video_record(numeric_id($_GET['id'] ?? null))); exit;
}
if ($route === 'create-video') { post_only(); create_video($user); }
if (in_array($route, ['update-video', 'delete-video'], true)) { post_only(); change_video($route === 'delete-video'); }
if ($route === 'move-video') { post_only(); move_video(); }
if ($route === 'edit-subject') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_edit_subject(subject_record(numeric_id($_GET['id'] ?? null))); exit;
}
if (in_array($route, ['update-subject', 'delete-subject'], true)) { post_only(); change_subject($route === 'delete-subject'); }
if ($route === 'create-subject') {
    post_only();
    $name = field('name', 120);
    $description = field('description', 255, false);
    $color = $_POST['color'] ?? 'teal';
    if (!in_array($color, ['teal', 'blue', 'violet', 'orange', 'rose'], true)) { $color = 'teal'; }
    try {
        query('INSERT INTO hc_portal_subjects (name, description, color, created_by) VALUES (?, ?, ?, ?)', [$name, $description, $color, $user['id']]);
        $id = (int) db()->lastInsertId();
        flash('Matéria criada. Agora você pode adicionar materiais.');
        redirect('subject', ['id' => $id]);
    } catch (PDOException $exception) {
        if (in_array((string) $exception->getCode(), ['23000', '23505'], true)) { flash('Já existe uma matéria com esse nome.', 'error'); redirect(); }
        throw $exception;
    }
}
if ($route === 'upload') { post_only(); upload_documents($user); }
if ($route === 'edit-material') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    $file = document(numeric_id($_GET['id'] ?? null));
    require_document_manager($file, $user);
    render_edit_document($file); exit;
}
if (in_array($route, ['update-material', 'delete-material'], true)) {
    post_only(); change_document($user, $route === 'delete-material');
}
if ($route === 'file') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    serve_document(document(numeric_id($_GET['id'] ?? null)), ($_GET['download'] ?? '') === '1');
}
if ($route === 'view') { render_document(document(numeric_id($_GET['id'] ?? null))); exit; }
if ($route === 'legacy') {
    $path = $legacyPath ?? $_GET['path'] ?? '';
    if (!is_string($path)) { fail('Arquivo não encontrado.', 404); }
    serve_legacy($path);
}
if ($route === 'users') { require_admin(); render_users(); exit; }
if ($route === 'create-user') {
    require_admin(); post_only();
    $name = field('name', 120);
    $login = strtolower(field('login', 100));
    if (!preg_match('/^[a-z0-9][a-z0-9._@+\-]{2,99}$/', $login)) { fail('Use um usuário com 3 a 100 caracteres: letras sem acentos, números, ponto, hífen, @ ou sublinhado.'); }
    $password = new_password();
    $role = ($_POST['role'] ?? '') === 'admin' ? 'admin' : 'member';
    try {
        query('INSERT INTO hc_portal_users (login, name, password_hash, role) VALUES (?, ?, ?, ?)', [$login, $name, password_hash($password, PASSWORD_DEFAULT), $role]);
    } catch (PDOException $exception) {
        if (in_array((string) $exception->getCode(), ['23000', '23505'], true)) { flash('Esse usuário já está cadastrado.', 'error'); redirect('users'); }
        throw $exception;
    }
    flash('Conta criada. A pessoa deverá trocar a senha no primeiro acesso.');
    redirect('users');
}
if ($route === 'update-user') {
    require_admin(); post_only();
    $id = numeric_id($_POST['id'] ?? null);
    if ($id === (int) $user['id']) { fail('Altere sua própria senha em Minha conta. Sua conta não pode ser desativada por você.'); }
    $target = query('SELECT * FROM hc_portal_users WHERE id = ?', [$id])->fetch();
    if (!$target) { fail('Conta não encontrada.', 404); }
    $action = $_POST['action'] ?? '';
    if ($action === 'reset') {
        $password = new_password();
        query('UPDATE hc_portal_users SET password_hash = ?, must_change_password = 1, session_version = session_version + 1 WHERE id = ?', [password_hash($password, PASSWORD_DEFAULT), $id]);
        flash('Senha redefinida. As sessões antigas foram encerradas.');
    } elseif ($action === 'toggle') {
        db()->beginTransaction();
        try {
            $lock = db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : '';
            $admins = query("SELECT id FROM hc_portal_users WHERE role = 'admin' AND active = 1 ORDER BY id" . $lock)->fetchAll();
            $target = query('SELECT * FROM hc_portal_users WHERE id = ?', [$id])->fetch();
            if ($target['role'] === 'admin' && (int) $target['active'] && count($admins) <= 1) { db()->rollBack(); fail('Mantenha pelo menos um administrador ativo.'); }
            query('UPDATE hc_portal_users SET active = ?, session_version = session_version + 1 WHERE id = ?', [(int) $target['active'] ? 0 : 1, $id]);
            db()->commit();
        } catch (Throwable $exception) { if (db()->inTransaction()) { db()->rollBack(); } throw $exception; }
        flash((int) $target['active'] ? 'Conta desativada e sessões encerradas.' : 'Conta reativada.');
    } elseif ($action === 'delete') {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão da conta.'); }
        db()->beginTransaction();
        try {
            $lock = db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : '';
            $admins = query("SELECT id FROM hc_portal_users WHERE role = 'admin' AND active = 1 ORDER BY id" . $lock)->fetchAll();
            $target = query('SELECT * FROM hc_portal_users WHERE id = ?' . $lock, [$id])->fetch();
            if (!$target) { db()->rollBack(); fail('Conta não encontrada.', 404); }
            if ($target['role'] === 'admin' && (int) $target['active'] && count($admins) <= 1) { db()->rollBack(); fail('Mantenha pelo menos um administrador ativo.'); }
            $noteFiles = delete_user_records($id);
            db()->commit();
        } catch (Throwable $exception) { if (db()->inTransaction()) { db()->rollBack(); } throw $exception; }
        remove_note_binaries($noteFiles);
        $photo = profile_photo_path($target);
        if ($photo) { @unlink($photo); }
        flash('Conta excluída.');
    } else { fail('Operação inválida.'); }
    redirect('users');
}
if (in_array($route, ['home', 'subject', 'folder', 'unassigned'], true)) {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    // A biblioteca mostra apenas os cards das matérias; a lista de materiais fica dentro de cada matéria.
    if ($route === 'home') { render_home(null, [], 0, '', 1, 1); exit; }
    $subject = null;
    $folder = null; $folders = []; $counts = []; $category = $_GET['categoria'] ?? '';
    $categories = ['materiais' => 'material', 'trabalhos' => 'trabalho', 'provas' => 'prova'];
    if (!is_string($category) || ($category !== '' && !isset($categories[$category]))) { fail('Selecione uma categoria válida.'); }
    if ($route === 'subject') {
        $subject = subject_record(numeric_id($_GET['id'] ?? null));
    }
    if ($route === 'folder') {
        $folder = folder_record(numeric_id($_GET['id'] ?? null));
        $subject = subject_record((int) $folder['subject_id']);
    }
    if ($subject) {
        $folders = subject_folders((int) $subject['id']);
        foreach (query('SELECT kind, COUNT(*) AS total FROM hc_portal_files WHERE subject_id = ? AND deleted_at IS NULL GROUP BY kind', [$subject['id']])->fetchAll() as $row) { $counts[$row['kind']] = (int) $row['total']; }
    }
    if ($route === 'unassigned') { $subject = ['id' => 0, 'name' => 'Sem matéria', 'description' => 'Materiais preservados, disponíveis para consulta e realocação em outra matéria.']; }
    $search = $_GET['q'] ?? '';
    if (!is_string($search) || strlen($search) > 400) { fail('A pesquisa deve ter até 100 caracteres.'); }
    $search = trim($search);
    $flat = $category !== '' || $search !== '';
    $types = ['pdf' => ['pdf'], 'html' => ['html', 'htm'], 'office' => ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp'], 'image' => ['png', 'jpg', 'jpeg', 'gif', 'webp'], 'text' => ['txt', 'md', 'csv', 'json', 'sql'], 'archive' => ['zip', 'rar', '7z', 'gz']];
    $type = $_GET['type'] ?? '';
    if (!is_string($type) || ($type !== '' && !isset($types[$type]))) { fail('Selecione um formato válido.', 400); }
    $orders = ['recent' => 'f.created_at DESC, f.id DESC', 'title' => 'f.title ASC, f.id ASC', 'oldest' => 'f.created_at ASC, f.id ASC'];
    $sort = $_GET['sort'] ?? 'recent';
    if (!is_string($sort) || !isset($orders[$sort])) { fail('Selecione uma ordenação válida.', 400); }
    $params = [];
    $where = ['f.deleted_at IS NULL'];
    if ($route === 'unassigned') { $where[] = 'f.subject_id IS NULL'; }
    elseif ($subject) { $where[] = 'f.subject_id = ?'; $params[] = $subject['id']; }
    if (in_array($route, ['subject', 'folder'], true) && !$flat) {
        if ($folder) { $where[] = 'f.folder_id = ?'; $params[] = $folder['id']; }
        else { $where[] = 'f.folder_id IS NULL'; }
    }
    if ($category !== '') { $where[] = 'f.kind = ?'; $params[] = $categories[$category]; }
    if ($type !== '') {
        $where[] = 'f.extension IN (' . implode(',', array_fill(0, count($types[$type]), '?')) . ')';
        array_push($params, ...$types[$type]);
    }
    if ($search !== '') {
        $where[] = '(f.title LIKE ? OR f.original_name LIKE ? OR s.name LIKE ? OR EXISTS (SELECT 1 FROM hc_portal_folders p WHERE p.id = f.folder_id AND p.name LIKE ?))';
        $needle = '%' . $search . '%';
        array_push($params, $needle, $needle, $needle, $needle);
    }
    $sqlWhere = $where ? ' WHERE ' . implode(' AND ', $where) : '';
    $total = (int) query('SELECT COUNT(*) FROM hc_portal_files f LEFT JOIN hc_portal_subjects s ON s.id = f.subject_id' . $sqlWhere, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / 12));
    $page = min($pages, max(1, numeric_id($_GET['page'] ?? '1')));
    $files = query('SELECT f.*, s.name AS subject_name, s.color AS subject_color, u.name AS uploader_name FROM hc_portal_files f LEFT JOIN hc_portal_subjects s ON s.id = f.subject_id LEFT JOIN hc_portal_users u ON u.id = f.uploaded_by' . $sqlWhere . ' ORDER BY ' . $orders[$sort] . ' LIMIT 12 OFFSET ' . (($page - 1) * 12), $params)->fetchAll();
    render_home($subject, $files, $total, $search, $page, $pages, $type, $sort, $route === 'subject' && !$flat ? subject_videos((int) $subject['id']) : [], ['folder' => $folder, 'folders' => $folders, 'counts' => $counts, 'category' => $category, 'flat' => $flat]);
    exit;
}
fail('Página não encontrada.', 404);
