<?php
declare(strict_types=1);

function install_portal(string $adminLogin, string $adminName, string $adminPassword): array {
    if (PHP_VERSION_ID < 70400) { throw new RuntimeException('O portal requer PHP 7.4 ou superior.'); }
    foreach (['pdo', 'pdo_mysql', 'fileinfo', 'session'] as $extension) {
        if (!extension_loaded($extension)) { throw new RuntimeException('Extensão PHP necessária: ' . $extension); }
    }
    if (strpos($adminPassword, "\0") !== false || !preg_match('//u', $adminPassword) || preg_match_all('/./us', $adminPassword) < 12 || strlen($adminPassword) > 72) { throw new RuntimeException('A senha inicial deve ter ao menos 12 caracteres e até 72 bytes.'); }
    $manifest = json_decode(file_get_contents(dirname(__DIR__) . '/import-manifest.json'), true, 512, JSON_THROW_ON_ERROR);
    foreach ($manifest['files'] as $file) {
        $path = path_inside((string) config('document_root'), $file['stored_path']);
        if (!$path || !hash_equals($file['sha256'], hash_file('sha256', $path))) { throw new RuntimeException('O arquivo original mudou ou está indisponível: ' . $file['stored_path']); }
    }
    $storage = (string) config('storage_path');
    if ((!is_dir($storage) && !mkdir($storage, 0755, true)) || !is_writable($storage)) { throw new RuntimeException('Armazenamento indisponível.'); }
    if (!chmod($storage, 0755) || file_put_contents($storage . '/.htaccess', "Require all denied\nOptions -Indexes\n") === false) { throw new RuntimeException('Não foi possível proteger o armazenamento.'); }
    // As únicas tabelas criadas têm o prefixo hc_portal_.
    $schema = file_get_contents(dirname(__DIR__) . '/schema.sql');
    foreach (explode(';', $schema) as $statement) { if (trim($statement) !== '') { db()->exec($statement); } }
    if (!portal_schema_ready()) { throw new RuntimeException('Execute portal/bin/migrate.php antes de usar uma instalação existente.'); }
    $createdUsers = 0; $createdFiles = 0; $createdSubjects = 0;
    db()->beginTransaction();
    try {
        if (!(int) query('SELECT COUNT(*) FROM hc_portal_users')->fetchColumn()) {
            query("INSERT INTO hc_portal_users (login, name, password_hash, role) VALUES (?, ?, ?, 'admin')", [$adminLogin, $adminName, password_hash($adminPassword, PASSWORD_DEFAULT)]);
            $createdUsers++;
        }
        $subjects = [];
        foreach ($manifest['subjects'] as $subject) {
            $id = query('SELECT id FROM hc_portal_subjects WHERE name = ?', [$subject['name']])->fetchColumn();
            if (!$id) {
                query('INSERT INTO hc_portal_subjects (name, description, color) VALUES (?, ?, ?)', [$subject['name'], $subject['description'], $subject['color']]);
                $id = db()->lastInsertId(); $createdSubjects++;
            }
            $subjects[$subject['key']] = $id;
        }
        foreach ($manifest['files'] as $file) {
            if (query('SELECT id FROM hc_portal_files WHERE legacy_path = ?', [$file['stored_path']])->fetchColumn()) { continue; }
            $timestamp = DateTime::createFromFormat('YmdHis', substr($file['modified'], 0, 14), new DateTimeZone('UTC'));
            $createdAt = $timestamp ? $timestamp->setTimezone(new DateTimeZone('America/Sao_Paulo'))->format('Y-m-d H:i:s') : date('Y-m-d H:i:s');
            query('INSERT INTO hc_portal_files (subject_id, title, original_name, stored_path, legacy_path, source, extension, mime, size, sha256, trusted_app, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$subjects[$file['subject']], $file['title'], $file['original_name'], $file['stored_path'], $file['stored_path'], 'legacy', $file['extension'], $file['mime'], $file['size'], $file['sha256'], (int) $file['trusted_app'], $createdAt]);
            $createdFiles++;
        }
        db()->commit();
    } catch (Throwable $exception) { if (db()->inTransaction()) { db()->rollBack(); } throw $exception; }
    return ['php' => PHP_VERSION, 'created_users' => $createdUsers, 'created_subjects' => $createdSubjects, 'created_files' => $createdFiles, 'upload_limit_bytes' => available_upload_bytes()];
}
