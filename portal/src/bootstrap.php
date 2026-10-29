<?php
declare(strict_types=1);

ini_set('display_errors', '0');
ini_set('log_errors', '1');
date_default_timezone_set('America/Sao_Paulo');

$configFile = getenv('HUMCODE_CONFIG_FILE') ?: dirname(__DIR__) . '/config.php';
if (!is_file($configFile)) {
    if (PHP_SAPI === 'cli') { fwrite(STDERR, "Configuração do portal não encontrada.\n"); exit(1); }
    http_response_code(503);
    header('Content-Type: text/html; charset=utf-8');
    exit('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Humcode</title><p>O portal está sendo preparado. Volte em instantes.</p></html>');
}
$config = require $configFile;

function config(string $key) { global $config; return $config[$key] ?? null; }
function e($value): string { return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function route_paths(): array {
    return [
        'home' => 'biblioteca', 'login' => 'entrar', 'two-factor' => 'entrar/verificacao', 'logout' => 'sair',
        'my-day' => 'meu-dia', 'agenda' => 'agenda', 'new-event' => 'agenda/novo',
        'commitment-content' => 'agenda/conteudos', 'change-content-link' => 'agenda/conteudos/alterar',
        'study-state' => 'estudo/marcar',
        'notes' => 'anotacoes', 'new-note' => 'anotacoes/nova', 'view-note' => 'anotacoes/{id}', 'edit-note' => 'anotacoes/{id}/editar',
        'note-file' => 'anotacoes/arquivo/{id}', 'note-file-download' => 'anotacoes/arquivo/{id}/download',
        'add-note-files' => 'anotacoes/arquivos/adicionar', 'update-note-file' => 'anotacoes/arquivos/atualizar', 'delete-note-file' => 'anotacoes/arquivos/excluir', 'notes-data' => 'anotacoes/dados', 'toggle-note-important' => 'anotacoes/importante', 'create-note' => 'anotacoes/criar', 'update-note' => 'anotacoes/atualizar', 'delete-note' => 'anotacoes/excluir',
        'invitations' => 'convites', 'invite-users' => 'agenda/convidar', 'send-invitations' => 'convites/enviar',
        'view-invitation' => 'convites/{id}', 'answer-invitation' => 'convites/responder', 'read-invitation' => 'notificacoes/convites/ler',
        'save-email' => 'minha-conta/email', 'two-factor-settings' => 'minha-conta/verificacao',
        'new-task' => 'agenda/tarefas/nova', 'view-task' => 'agenda/tarefas/{id}', 'edit-task' => 'agenda/tarefas/{id}/editar',
        'create-task' => 'agenda/tarefas/criar', 'update-task' => 'agenda/tarefas/atualizar', 'delete-task' => 'agenda/tarefas/excluir',
        'set-task-status' => 'agenda/tarefas/estado', 'read-task-notification' => 'notificacoes/tarefas/ler',
        'view-event' => 'agenda/eventos/{id}', 'edit-event' => 'agenda/eventos/{id}/editar',
        'create-event' => 'agenda/eventos/criar', 'update-event' => 'agenda/eventos/atualizar', 'delete-event' => 'agenda/eventos/excluir',
        'notifications' => 'notificacoes', 'read-notification' => 'notificacoes/ler',
        'password' => 'minha-conta', 'photo' => 'minha-conta/foto', 'update-photo' => 'minha-conta/foto/atualizar',
        'subject' => 'materias/{id}', 'unassigned' => 'materiais/sem-materia',
        'view' => 'materiais/{id}', 'file' => 'materiais/{id}/arquivo', 'download' => 'materiais/{id}/download',
        'edit-material' => 'materiais/{id}/editar', 'update-material' => 'materiais/atualizar',
        'delete-material' => 'materiais/excluir', 'upload' => 'materiais/enviar',
        'create-subject' => 'materias/criar', 'edit-subject' => 'materias/{id}/editar',
        'update-subject' => 'materias/atualizar', 'delete-subject' => 'materias/excluir',
        'create-video' => 'videos/criar', 'edit-video' => 'videos/{id}/editar', 'update-video' => 'videos/atualizar',
        'delete-video' => 'videos/excluir', 'move-video' => 'videos/mover',
        'folder' => 'pastas/{id}', 'edit-folder' => 'pastas/{id}/editar',
        'create-folder' => 'pastas/criar', 'update-folder' => 'pastas/atualizar', 'delete-folder' => 'pastas/excluir',
        'users' => 'contas', 'create-user' => 'contas/criar', 'update-user' => 'contas/atualizar',
    ];
}
function route_from_path(string $relative): ?array {
    if ($relative === '') { return ['route' => 'home']; }
    foreach (route_paths() as $route => $template) {
        $pattern = str_replace('\{id\}', '([0-9]+)', preg_quote($template, '~'));
        if (preg_match('~^' . $pattern . '/?$~D', $relative, $matches)) {
            $params = ['route' => $route === 'download' ? 'file' : $route];
            if (isset($matches[1])) { $params['id'] = $matches[1]; }
            if ($route === 'download') { $params['download'] = '1'; }
            return $params;
        }
    }
    return null;
}
function url(string $route = 'home', array $params = []): string {
    $paths = route_paths();
    if ($route === 'file' && !empty($params['download'])) { $route = 'download'; unset($params['download']); }
    if (!isset($paths[$route])) {
        return rtrim((string) config('base_path'), '/') . '/index.php?' . http_build_query(array_merge(['route' => $route], $params), '', '&', PHP_QUERY_RFC3986);
    }
    $path = $paths[$route];
    if (strpos($path, '{id}') !== false) { $path = str_replace('{id}', (string) numeric_id($params['id'] ?? null), $path); unset($params['id']); }
    unset($params['route'], $params['legacy_path']);
    foreach ($params as $key => $value) { if ($value === '' || $value === null || ($key === 'sort' && $value === 'recent')) { unset($params[$key]); } }
    $query = http_build_query($params, '', '&', PHP_QUERY_RFC3986);
    return rtrim((string) config('base_path'), '/') . '/' . $path . ($query === '' ? '' : '?' . $query);
}
function redirect(string $route = 'home', array $params = []): void { header('Location: ' . url($route, $params), true, 303); exit; }
function is_https(): bool { return isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off'; }
function local_destination($value, bool $readOnly = true): ?string {
    if (!is_string($value) || $value === '' || strlen($value) > 2048 || preg_match('/[\x00-\x20\x7F\\\\]/', $value)) { return null; }
    $parts = parse_url($value);
    if ($parts === false || isset($parts['scheme']) || isset($parts['host']) || isset($parts['fragment'])) { return null; }
    $path = rawurldecode($parts['path'] ?? '');
    $prefix = rtrim((string) config('base_path'), '/') . '/';
    if (strpos($path, $prefix) !== 0 || strpos($path, '//') !== false || strpos($path, '\\') !== false || preg_match('~(?:^|/)\.{1,2}(?:/|$)~', $path) || preg_match('/[\x00-\x20\x7F]/', $path)) { return null; }
    $relative = substr($path, strlen($prefix));
    if (preg_match('~^(?:portal|trabalho_datait)(?:/|$)~i', $relative)) { return null; }
    $matched = route_from_path($relative);
    if ($readOnly && $matched !== null && !in_array($matched['route'], ['home', 'subject', 'folder', 'unassigned', 'view', 'file', 'my-day', 'agenda', 'new-event', 'view-event', 'edit-event', 'new-task', 'view-task', 'edit-task', 'notifications', 'commitment-content', 'notes', 'notes-data', 'new-note', 'view-note', 'edit-note', 'note-file', 'note-file-download', 'invitations', 'view-invitation', 'invite-users'], true)) { return null; }
    if ($readOnly && ($relative === 'index.php' || $relative === '')) {
        parse_str($parts['query'] ?? '', $params);
        $route = $params['route'] ?? 'home';
        if (!is_string($route) || !in_array($route, ['home', 'subject', 'folder', 'unassigned', 'view', 'file', 'legacy', 'my-day', 'agenda', 'new-event', 'view-event', 'edit-event', 'new-task', 'view-task', 'edit-task', 'notifications'], true)) { return null; }
    }
    return $value;
}
function remember_destination(): void {
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
        $destination = local_destination($_SERVER['REQUEST_URI'] ?? null);
        if ($destination !== null) { $_SESSION['return_to'] = $destination; }
    }
}
function redirect_to_destination(): void {
    $destination = local_destination($_SESSION['return_to'] ?? null);
    unset($_SESSION['return_to']);
    if ($destination !== null) { header('Location: ' . $destination, true, 303); exit; }
    redirect();
}

if (PHP_SAPI !== 'cli') {
    if (config('force_https') && !is_https()) {
        $destination = local_destination($_SERVER['REQUEST_URI'] ?? null, false) ?? url();
        header('Location: ' . rtrim((string) config('site_url'), '/') . $destination, true, 302);
        exit;
    }
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store, private');
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: same-origin');
    header('X-Frame-Options: SAMEORIGIN');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    if (is_https()) { header('Strict-Transport-Security: max-age=31536000'); }
    header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://i.ytimg.com; frame-src 'self' https://www.youtube-nocookie.com; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'");
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    session_name('humcode_portal');
    session_set_cookie_params(['lifetime' => 0, 'path' => (config('base_path') ?: '') . '/', 'secure' => is_https(), 'httponly' => true, 'samesite' => 'Lax']);
    session_start();
    $now = time();
    if (isset($_SESSION['user_id']) && ($now - ($_SESSION['last_activity'] ?? 0) > 7200 || $now - ($_SESSION['signed_at'] ?? 0) > 43200)) {
        $_SESSION = [];
        session_regenerate_id(true);
    }
    $_SESSION['last_activity'] = $now;
    if (empty($_SESSION['csrf'])) { $_SESSION['csrf'] = bin2hex(random_bytes(32)); }
}

set_exception_handler(function (Throwable $exception): void {
    error_log('Humcode portal: ' . $exception->getMessage());
    http_response_code(500);
    if (PHP_SAPI === 'cli') { fwrite(STDERR, "Falha na operação. Consulte o log do PHP.\n"); exit(1); }
    if (function_exists('render_error')) { render_error('Não foi possível concluir a operação. Tente novamente.', 500); }
    else { echo '<p>Não foi possível concluir a operação. Tente novamente.</p>'; }
});

function db(): PDO {
    static $pdo;
    if (!$pdo) {
        $options = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC, PDO::ATTR_EMULATE_PREPARES => false];
        $settings = config('db');
        $driverClass = strpos($settings['dsn'], 'sqlite:') === 0 && class_exists('Pdo\\Sqlite') ? 'Pdo\\Sqlite' : 'PDO';
        $pdo = new $driverClass($settings['dsn'], $settings['user'] ?? null, $settings['password'] ?? null, $options);
        if ($pdo->getAttribute(PDO::ATTR_DRIVER_NAME) === 'sqlite') { $pdo->exec('PRAGMA foreign_keys = ON'); }
        if ($pdo->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql') { $pdo->exec('SET time_zone = ' . $pdo->quote(date('P'))); }
    }
    return $pdo;
}
function query(string $sql, array $params = []): PDOStatement { $stmt = db()->prepare($sql); $stmt->execute($params); return $stmt; }
function csrf(): string { return '<input type="hidden" name="csrf" value="' . e($_SESSION['csrf']) . '">'; }
function check_csrf(): void {
    $token = $_POST['csrf'] ?? $_SERVER['HTTP_X_CSRF_TOKEN'] ?? '';
    if (!is_string($token) || !hash_equals($_SESSION['csrf'], $token)) { fail('A sessão do formulário expirou. Atualize a página e tente novamente.', 403); }
}
function flash(string $message, string $type = 'success'): void { $_SESSION['flash'] = ['message' => $message, 'type' => $type]; }
function fail(string $message, int $status = 400): void { http_response_code($status); render_error($message, $status); exit; }
function current_user(): ?array {
    static $loaded = false, $user = null;
    if (!$loaded) {
        $loaded = true;
        if (!empty($_SESSION['user_id'])) {
            $found = query('SELECT * FROM hc_portal_users WHERE id = ? AND active = 1', [$_SESSION['user_id']])->fetch();
            if ($found && (int) $found['session_version'] === (int) ($_SESSION['session_version'] ?? 0)) { $user = $found; }
            else { unset($_SESSION['user_id'], $_SESSION['session_version']); }
        }
    }
    return $user;
}
function require_user(): array { $user = current_user(); if (!$user) { remember_destination(); redirect('login'); } return $user; }
function require_admin(): array { $user = require_user(); if ($user['role'] !== 'admin') { fail('Esta área é exclusiva dos administradores.', 403); } return $user; }
// Caminho interno enviado pelo navegador para voltar à lista de onde o modal foi aberto.
function safe_return_path($value): ?string {
    if (!is_string($value) || $value === '' || strlen($value) > 500 || $value[0] !== '/') { return null; }
    if (isset($value[1]) && ($value[1] === '/' || $value[1] === '\\')) { return null; }
    if (preg_match('/[\x00-\x1f\x7f\\\\#]/', $value)) { return null; }
    return $value;
}
function redirect_back_to_modal(string $fallbackRoute, array $fallbackParams, string $key): void {
    $path = safe_return_path($_POST['return'] ?? null);
    if ($path !== null) { header('Location: ' . $path . '#' . $key, true, 303); exit; }
    redirect($fallbackRoute, $fallbackParams);
}
function post_only(): void { if ($_SERVER['REQUEST_METHOD'] !== 'POST') { header('Allow: POST'); fail('Use o formulário para realizar esta operação.', 405); } check_csrf(); }
function field(string $name, int $max, bool $required = true): string {
    $value = $_POST[$name] ?? '';
    if (!is_string($value)) { fail('O campo informado é inválido.'); }
    $value = trim($value);
    if (($required && $value === '') || strlen($value) > $max * 4 || preg_match('/[\x00-\x08\x0B\x0C\x0E-\x1F]/', $value) || !preg_match('//u', $value)) { fail('Preencha os campos com valores válidos.'); }
    $length = preg_match_all('/./us', $value, $matches);
    if ($length > $max) { fail('Um dos campos excedeu o tamanho permitido.'); }
    return $value;
}
function new_password(string $name = 'password'): string {
    $value = $_POST[$name] ?? '';
    if (!is_string($value) || strpos($value, "\0") !== false || !preg_match('//u', $value) || preg_match_all('/./us', $value) < 12 || strlen($value) > 72) { fail('Use pelo menos 12 caracteres e até 72 bytes. Acentos e símbolos podem ocupar mais de um byte.'); }
    return $value;
}
function numeric_id($value): int { return is_scalar($value) && ctype_digit((string) $value) ? (int) $value : 0; }
function pretty_size(int $bytes): string {
    if ($bytes < 1024) { return $bytes . ' B'; }
    if ($bytes < 1048576) { return number_format($bytes / 1024, 0, ',', '.') . ' KB'; }
    return number_format($bytes / 1048576, 1, ',', '.') . ' MB';
}
function pretty_date(?string $date): string { return $date ? date('d/m/Y', strtotime($date)) : '—'; }
function subject_list(): array { return query('SELECT s.*, (SELECT COUNT(*) FROM hc_portal_files f WHERE f.subject_id = s.id AND f.deleted_at IS NULL) AS file_count FROM hc_portal_subjects s ORDER BY s.name')->fetchAll(); }
function available_upload_bytes(): int {
    $limits = [(int) config('max_upload_bytes')];
    foreach (['upload_max_filesize', 'post_max_size'] as $key) {
        $raw = trim((string) ini_get($key));
        $number = (float) $raw;
        $unit = strtolower(substr($raw, -1));
        if ($unit === 'g') { $number *= 1073741824; } elseif ($unit === 'm') { $number *= 1048576; } elseif ($unit === 'k') { $number *= 1024; }
        if ($number > 0) { $limits[] = $key === 'post_max_size' ? max(0, (int) $number - 65536) : (int) $number; }
    }
    return max(0, min($limits));
}
function available_upload_files(): int {
    if (!filter_var(ini_get('file_uploads'), FILTER_VALIDATE_BOOLEAN)) { return 0; }
    return max(0, min((int) config('max_upload_files'), (int) ini_get('max_file_uploads')));
}
function available_upload_total_bytes(): int {
    $limit = available_upload_files() * available_upload_bytes();
    $raw = trim((string) ini_get('post_max_size'));
    $bytes = (float) $raw;
    $unit = strtolower(substr($raw, -1));
    if ($unit === 'g') { $bytes *= 1073741824; } elseif ($unit === 'm') { $bytes *= 1048576; } elseif ($unit === 'k') { $bytes *= 1024; }
    return $bytes > 0 ? min($limit, max(0, (int) $bytes - 65536)) : $limit;
}

require $humcodeMigrationFile ?? __DIR__ . '/migrations.php';
