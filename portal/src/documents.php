<?php
declare(strict_types=1);

function upload_formats(): array {
    return [
        'pdf' => ['application/pdf'],
        'html' => ['text/html', 'text/plain'], 'htm' => ['text/html', 'text/plain'],
        'txt' => ['text/plain', 'application/x-empty'], 'md' => ['text/plain'],
        'csv' => ['text/plain', 'text/csv', 'application/csv', 'application/vnd.ms-excel'],
        'json' => ['application/json', 'text/plain'], 'sql' => ['text/plain', 'text/x-sql'],
        'png' => ['image/png'], 'jpg' => ['image/jpeg'], 'jpeg' => ['image/jpeg'],
        'gif' => ['image/gif'], 'webp' => ['image/webp'],
        'doc' => ['application/msword', 'application/x-ole-storage', 'application/CDFV2'],
        'xls' => ['application/vnd.ms-excel', 'application/x-ole-storage', 'application/CDFV2'],
        'ppt' => ['application/vnd.ms-powerpoint', 'application/x-ole-storage', 'application/CDFV2'],
        'docx' => ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/zip', 'application/octet-stream'],
        'xlsx' => ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/zip', 'application/octet-stream'],
        'pptx' => ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/zip', 'application/octet-stream'],
        'odt' => ['application/vnd.oasis.opendocument.text', 'application/zip'],
        'ods' => ['application/vnd.oasis.opendocument.spreadsheet', 'application/zip'],
        'odp' => ['application/vnd.oasis.opendocument.presentation', 'application/zip'],
        'zip' => ['application/zip', 'application/x-zip-compressed'],
        'rar' => ['application/x-rar', 'application/vnd.rar', 'application/x-rar-compressed'],
        '7z' => ['application/x-7z-compressed'],
    ];
}
function can_preview(array $file): bool { return in_array($file['extension'], ['pdf', 'html', 'htm', 'txt', 'md', 'csv', 'json', 'sql', 'png', 'jpg', 'jpeg', 'gif', 'webp'], true); }
function document(int $id): array {
    $file = query('SELECT f.*, s.name AS subject_name, s.color AS subject_color FROM hc_portal_files f LEFT JOIN hc_portal_subjects s ON s.id = f.subject_id WHERE f.id = ? AND f.deleted_at IS NULL', [$id])->fetch();
    if (!$file) { fail('Arquivo não encontrado.', 404); }
    return $file;
}
function path_inside(string $base, string $relative): ?string {
    if ($relative === '' || strpos($relative, "\0") !== false || strpos($relative, '\\') !== false || $relative[0] === '/' || preg_match('~(?:^|/)\.{1,2}(?:/|$)~', $relative)) { return null; }
    $root = realpath($base);
    $path = realpath($base . '/' . $relative);
    if (!$root || !$path || !is_file($path)) { return null; }
    $prefix = rtrim(str_replace('\\', '/', $root), '/') . '/';
    $normalized = str_replace('\\', '/', $path);
    $matches = DIRECTORY_SEPARATOR === '\\' ? strncasecmp($normalized, $prefix, strlen($prefix)) === 0 : strncmp($normalized, $prefix, strlen($prefix)) === 0;
    return $matches ? $path : null;
}
function document_path(array $file): string {
    $base = $file['source'] === 'legacy' ? config('document_root') : config('storage_path');
    if ($file['source'] === 'legacy' && preg_match('~^(?:trabalho_datait|portal)(?:/|$)~i', $file['stored_path'])) { fail('Arquivo não encontrado.', 404); }
    $path = path_inside((string) $base, $file['stored_path']);
    if (!$path) { fail('O arquivo não está disponível no servidor.', 404); }
    if ($file['source'] === 'legacy' && strtolower(pathinfo($path, PATHINFO_EXTENSION)) === 'php' && strpos(file_get_contents($path), '<?') !== false) { fail('Este arquivo é uma aplicação e não pode ser entregue como documento.', 404); }
    return $path;
}
function upload_documents(array $user): void {
    $subjectId = numeric_id($_POST['subject_id'] ?? null);
    $folderId = optional_folder_id($_POST['folder_id'] ?? null);
    $kind = file_kind_field();
    if (!query('SELECT id FROM hc_portal_subjects WHERE id = ?', [$subjectId])->fetch()) { fail('Selecione uma matéria válida.'); }
    $uploads = $_FILES['documents'] ?? null;
    if (!$uploads || !isset($uploads['name']) || !is_array($uploads['name']) || !$uploads['name']) { fail('Selecione pelo menos um arquivo.'); }
    if (count($uploads['name']) > available_upload_files()) { fail('Envie até ' . available_upload_files() . ' arquivos por vez.'); }
    $expected = $_POST['expected_files'] ?? null;
    if (!is_string($expected) || !ctype_digit($expected) || (int) $expected !== count($uploads['name'])) { fail('Nem todos os arquivos chegaram ao servidor. Atualize a página e envie o lote novamente.', 400); }
    $pending = [];
    foreach ($uploads['name'] as $index => $name) {
        $pending[] = validate_document_upload(['name' => $name, 'error' => $uploads['error'][$index] ?? UPLOAD_ERR_NO_FILE, 'tmp_name' => $uploads['tmp_name'][$index] ?? '']);
    }
    if (array_sum(array_column($pending, 'size')) > available_upload_total_bytes()) { fail('O lote excede o limite total de ' . pretty_size(available_upload_total_bytes()) . '. Envie menos arquivos por vez.', 413); }
    $storage = (string) config('storage_path');
    if (!is_dir($storage) && !mkdir($storage, 0755, true)) { throw new RuntimeException('Não foi possível criar o armazenamento.'); }
    $moved = [];
    db()->beginTransaction();
    try {
        lock_material_subject($subjectId);
        validate_folder_subject($folderId, $subjectId);
        foreach ($pending as $item) {
            $target = $storage . '/' . $item['stored_path'];
            if (!move_uploaded_file($item['temp'], $target)) { throw new RuntimeException('Falha ao armazenar upload.'); }
            $moved[] = $target;
            @chmod($target, 0600);
            query('INSERT INTO hc_portal_files (subject_id, folder_id, kind, title, original_name, stored_path, source, extension, mime, size, sha256, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$subjectId, $folderId, $kind, $item['title'], $item['name'], $item['stored_path'], 'upload', $item['extension'], $item['mime'], $item['size'], $item['sha256'], $user['id']]);
        }
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        foreach ($moved as $path) { @unlink($path); }
        throw $exception;
    }
    flash(count($pending) === 1 ? 'Arquivo enviado com sucesso.' : count($pending) . ' arquivos enviados com sucesso.');
    redirect_to_folder($folderId, $subjectId);
}
function validate_document_upload(array $upload): array {
    $error = $upload['error'] ?? UPLOAD_ERR_NO_FILE;
    if ($error !== UPLOAD_ERR_OK) {
        fail(in_array($error, [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true) ? 'Um arquivo excedeu o limite de ' . pretty_size(available_upload_bytes()) . '.' : 'O envio de um arquivo falhou. Selecione o arquivo novamente.');
    }
    $name = $upload['name'] ?? null;
    if (!is_string($name) || preg_match('/[\x00-\x1F\x7F]/', $name)) { fail('O nome de um arquivo é inválido.'); }
    $name = basename(str_replace('\\', '/', $name));
    if (strlen($name) > 240 || !preg_match('//u', $name)) { fail('Use um nome de arquivo com até 240 bytes e caracteres válidos.'); }
    $extension = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $formats = upload_formats();
    if (!isset($formats[$extension])) { fail('O formato de “' . $name . '” não é permitido. Envie um documento, imagem, HTML ou arquivo compactado.'); }
    $temp = $upload['tmp_name'] ?? '';
    if (!is_string($temp) || !is_uploaded_file($temp)) { fail('O arquivo enviado é inválido.'); }
    $size = filesize($temp);
    if ($size === false || $size === 0 || $size > available_upload_bytes()) { fail('Cada arquivo deve ter conteúdo e no máximo ' . pretty_size(available_upload_bytes()) . '.'); }
    $mime = (new finfo(FILEINFO_MIME_TYPE))->file($temp);
    if (!in_array($mime, $formats[$extension], true)) { fail('O conteúdo de “' . $name . '” não corresponde ao formato informado.'); }
    $title = pathinfo($name, PATHINFO_FILENAME);
    if (preg_match_all('/./us', $title, $characters) > 180) { $title = implode('', array_slice($characters[0], 0, 180)); }
    return ['temp' => $temp, 'name' => $name, 'extension' => $extension, 'size' => $size, 'mime' => $mime, 'title' => $title, 'sha256' => hash_file('sha256', $temp), 'stored_path' => bin2hex(random_bytes(24)) . '.bin'];
}
function can_manage_document(array $file, array $user): bool {
    return $user['role'] === 'admin';
}
function require_document_manager(array $file, array $user): void {
    if (!can_manage_document($file, $user)) { fail('Somente administradores podem gerenciar materiais.', 403); }
}
function remove_uploaded_binary(array $file): void {
    // Nunca remove originais; somente os nomes aleatórios gerados pelo portal.
    if ($file['source'] !== 'upload' || !preg_match('/^[a-f0-9]{48}\.bin$/D', $file['stored_path'])) { return; }
    $path = path_inside((string) config('storage_path'), $file['stored_path']);
    if ($path && !@unlink($path)) { error_log('Humcode: falha ao remover arquivo privado ' . $file['id']); }
}
function change_document(array $user, bool $delete): void {
    $file = document(numeric_id($_POST['id'] ?? null));
    require_document_manager($file, $user);
    $revision = $_POST['revision'] ?? null;
    if (!is_string($revision) || !hash_equals((string) $file['revision'], $revision)) { fail('Este material foi alterado. Reabra a página antes de continuar.', 409); }
    $replacement = null;
    if ($delete) {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão do material.'); }
    } else {
        $title = field('title', 180);
        $selection = $_POST['subject_id'] ?? null;
        $subjectId = $selection === '' ? null : numeric_id($selection);
        $folderId = optional_folder_id($_POST['folder_id'] ?? null);
        $kind = array_key_exists('kind', $_POST) ? file_kind_field() : $file['kind'];
        if ($subjectId !== null && (!$subjectId || !query('SELECT id FROM hc_portal_subjects WHERE id = ?', [$subjectId])->fetch())) { fail('Selecione uma matéria válida.'); }
        if (isset($_FILES['replacement']) && ($_FILES['replacement']['error'] ?? null) !== UPLOAD_ERR_NO_FILE) { $replacement = validate_document_upload($_FILES['replacement']); }
    }
    $target = null;
    db()->beginTransaction();
    try {
        $lock = db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : '';
        if (!$delete && $subjectId !== null) { lock_material_subject($subjectId); }
        if (!$delete) { validate_folder_subject($folderId, $subjectId); }
        $current = query('SELECT * FROM hc_portal_files WHERE id = ?' . $lock, [$file['id']])->fetch();
        if (!$current || $current['deleted_at'] !== null || (int) $current['revision'] !== (int) $file['revision']) {
            db()->rollBack(); fail('Este material foi alterado. Reabra a página antes de continuar.', 409);
        }
        require_document_manager($current, $user);
        if ($delete) {
            query('UPDATE hc_portal_files SET deleted_at = CURRENT_TIMESTAMP, revision = revision + 1 WHERE id = ?', [$file['id']]);
        } elseif ($replacement) {
            $storage = (string) config('storage_path');
            if (!is_dir($storage) && !mkdir($storage, 0755, true)) { throw new RuntimeException('Armazenamento indisponível.'); }
            $target = $storage . '/' . $replacement['stored_path'];
            if (!move_uploaded_file($replacement['temp'], $target)) { throw new RuntimeException('Falha ao armazenar substituição.'); }
            @chmod($target, 0600);
            query("UPDATE hc_portal_files SET title = ?, subject_id = ?, folder_id = ?, kind = ?, original_name = ?, stored_path = ?, source = 'upload', extension = ?, mime = ?, size = ?, sha256 = ?, trusted_app = 0, revision = revision + 1 WHERE id = ?", [$title, $subjectId, $folderId, $kind, $replacement['name'], $replacement['stored_path'], $replacement['extension'], $replacement['mime'], $replacement['size'], $replacement['sha256'], $file['id']]);
            query('DELETE FROM hc_portal_file_study WHERE file_id = ?', [$file['id']]);
        } else {
            query('UPDATE hc_portal_files SET title = ?, subject_id = ?, folder_id = ?, kind = ?, revision = revision + 1 WHERE id = ?', [$title, $subjectId, $folderId, $kind, $file['id']]);
        }
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        if ($target) { @unlink($target); }
        throw $exception;
    }
    if ($delete || $replacement) { remove_uploaded_binary($file); }
    flash($delete ? 'Material excluído do portal.' : 'Material atualizado.');
    if ($delete && $file['subject_id'] === null) { redirect('unassigned'); }
    redirect($delete ? 'subject' : 'view', ['id' => $delete ? $file['subject_id'] : $file['id']]);
}
function serve_document(array $file, bool $download): void {
    $path = document_path($file);
    if (!$download && !can_preview($file)) { fail('Este formato está disponível para download.', 415); }
    $extension = $file['extension'];
    $types = ['pdf' => 'application/pdf', 'html' => 'text/html', 'htm' => 'text/html', 'png' => 'image/png', 'jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg', 'gif' => 'image/gif', 'webp' => 'image/webp'];
    $mime = $download ? 'application/octet-stream' : ($types[$extension] ?? 'text/plain; charset=utf-8');
    header('Content-Type: ' . $mime);
    header('X-Content-Type-Options: nosniff');
    $ascii = preg_replace('/[^a-zA-Z0-9._-]/', '_', $file['original_name']);
    header('Content-Disposition: ' . ($download ? 'attachment' : 'inline') . '; filename="' . $ascii . '"; filename*=UTF-8\'\'' . rawurlencode($file['original_name']));
    if (!$download && in_array($extension, ['html', 'htm'], true)) {
        // HTML enviado não recebe a origem, cookies ou acesso ao portal.
        if (!$file['trusted_app'] || $file['source'] !== 'legacy') {
            header("Content-Security-Policy: sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads; frame-ancestors 'self'");
        } else {
            header("Content-Security-Policy: frame-ancestors 'self'");
        }
        if ($file['source'] === 'legacy') {
            $content = file_get_contents($path);
            $folder = dirname($file['stored_path']);
            $base = (string) config('base_path') . '/' . ($folder === '.' ? '' : $folder . '/');
            $injection = '<base href="' . e($base) . '">';
            if ($file['stored_path'] === 'trab/index.php') {
                $injection .= '<script src="' . e((string) config('base_path') . '/portal/assets/legacy-bridge.js') . '" data-csrf="' . e($_SESSION['csrf']) . '"></script>';
            }
            $content = preg_replace('/<head\b[^>]*>/i', '$0' . str_replace('$', '\\$', $injection), $content, 1, $inserted);
            if (!$inserted) { $content = $injection . $content; }
            session_write_close();
            echo $content;
            exit;
        }
    } else {
        header("Content-Security-Policy: default-src 'none'; frame-ancestors 'self'");
    }
    header('Content-Length: ' . filesize($path));
    session_write_close();
    $handle = fopen($path, 'rb');
    if (!$handle) { exit; }
    while (!feof($handle) && !connection_aborted()) { echo fread($handle, 65536); }
    fclose($handle);
    exit;
}
function serve_legacy(string $relative): void {
    $relative = ltrim($relative, '/');
    $file = query('SELECT * FROM hc_portal_files WHERE legacy_path = ? AND deleted_at IS NULL', [$relative])->fetch();
    if (!$file) {
        foreach (['index.html', 'index.php'] as $index) {
            $file = query('SELECT * FROM hc_portal_files WHERE legacy_path = ? AND deleted_at IS NULL', [rtrim($relative, '/') . '/' . $index])->fetch();
            if ($file) { break; }
        }
    }
    if ($file) { serve_document($file, false); }
    $path = path_inside((string) config('document_root'), $relative);
    if (!$path) { fail('Arquivo não encontrado.', 404); }
    if ($relative === 'trab/api.php') {
        if (!query("SELECT id FROM hc_portal_files WHERE legacy_path = 'trab/index.php' AND source = 'legacy' AND deleted_at IS NULL")->fetch()) { fail('Arquivo não encontrado.', 404); }
        if ($_SERVER['REQUEST_METHOD'] === 'POST') { require_admin(); check_csrf(); }
        elseif ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
        // Aplicação preexistente: nunca executa arquivos enviados pelo portal.
        header_remove('Content-Security-Policy');
        chdir(dirname($path));
        session_write_close();
        require $path;
        exit;
    }
    $extension = strtolower(pathinfo($relative, PATHINFO_EXTENSION));
    $assetTypes = ['js' => 'text/javascript; charset=utf-8', 'css' => 'text/css; charset=utf-8', 'svg' => 'image/svg+xml'];
    if (strpos($relative, 'portfolio/') === 0 && isset($assetTypes[$extension])) {
        if (!query("SELECT id FROM hc_portal_files WHERE legacy_path = 'portfolio/index.html' AND source = 'legacy' AND deleted_at IS NULL")->fetch()) { fail('Arquivo não encontrado.', 404); }
        header('Content-Type: ' . $assetTypes[$extension]);
        header("Content-Security-Policy: default-src 'none'; frame-ancestors 'self'; sandbox");
        session_write_close();
        readfile($path);
        exit;
    }
    // Fontes PHP, configurações e arquivos fora do catálogo não são expostos.
    fail('Arquivo não encontrado.', 404);
}
