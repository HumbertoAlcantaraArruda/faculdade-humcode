<?php
declare(strict_types=1);

function profile_photo_name(array $user): string { return 'avatar-' . (int) $user['id'] . '.image'; }
function profile_photo_path(array $user): ?string {
    return path_inside((string) config('storage_path'), profile_photo_name($user));
}
function profile_photo_limit(): int { return min(2 * 1024 * 1024, available_upload_bytes()); }

// Remove a conta e seus dados privados; materiais compartilhados ficam sem autor.
// Exclusões explícitas, sem depender de ON DELETE CASCADE nas tabelas já criadas em produção.
function delete_user_records(int $id): array {
    $events = 'SELECT id FROM hc_portal_events WHERE user_id = ?';
    $tasks = 'SELECT id FROM hc_portal_tasks WHERE user_id = ?';
    $noteFiles = query('SELECT id, stored_path FROM hc_portal_note_files WHERE user_id = ? OR note_id IN (SELECT id FROM hc_portal_notes WHERE user_id = ?)', [$id, $id])->fetchAll();
    query('DELETE FROM hc_portal_invitations WHERE sender_id = ? OR recipient_id = ?', [$id, $id]);
    query('UPDATE hc_portal_invitations SET source_event_id = NULL WHERE source_event_id IN (' . $events . ')', [$id]);
    query('UPDATE hc_portal_invitations SET accepted_event_id = NULL WHERE accepted_event_id IN (' . $events . ')', [$id]);
    foreach (['hc_portal_task_notifications', 'hc_portal_task_files', 'hc_portal_task_videos', 'hc_portal_task_folders'] as $table) { query('DELETE FROM ' . $table . ' WHERE task_id IN (' . $tasks . ')', [$id]); }
    query('UPDATE hc_portal_tasks SET event_id = NULL WHERE user_id <> ? AND event_id IN (' . $events . ')', [$id, $id]);
    query('DELETE FROM hc_portal_tasks WHERE user_id = ?', [$id]);
    foreach (['hc_portal_event_notifications', 'hc_portal_event_files', 'hc_portal_event_videos', 'hc_portal_event_folders'] as $table) { query('DELETE FROM ' . $table . ' WHERE event_id IN (' . $events . ')', [$id]); }
    query('DELETE FROM hc_portal_events WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_recurrences WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_note_files WHERE user_id = ? OR note_id IN (SELECT id FROM hc_portal_notes WHERE user_id = ?)', [$id, $id]);
    query('DELETE FROM hc_portal_notes WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_file_study WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_video_study WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_two_factor_codes WHERE user_id = ?', [$id]);
    query('DELETE FROM hc_portal_trusted_devices WHERE user_id = ?', [$id]);
    foreach (['hc_portal_subjects', 'hc_portal_folders', 'hc_portal_videos'] as $table) { query('UPDATE ' . $table . ' SET created_by = NULL WHERE created_by = ?', [$id]); }
    query('UPDATE hc_portal_files SET uploaded_by = NULL WHERE uploaded_by = ?', [$id]);
    query('DELETE FROM hc_portal_users WHERE id = ?', [$id]);
    return $noteFiles;
}

function update_profile_photo(array $user): void {
    $action = $_POST['action'] ?? '';
    if ($action === 'remove') {
        $path = profile_photo_path($user);
        if ($path && !unlink($path)) { throw new RuntimeException('Falha ao remover foto.'); }
        flash('Sua foto foi removida.');
        redirect('password');
    }
    if ($action !== 'upload') { fail('Operação inválida.'); }
    $upload = $_FILES['photo'] ?? null;
    if (!is_array($upload) || ($upload['error'] ?? null) !== UPLOAD_ERR_OK) { fail('Selecione uma foto de até ' . pretty_size(profile_photo_limit()) . '.'); }
    $temp = $upload['tmp_name'] ?? null;
    $name = $upload['name'] ?? null;
    if (!is_string($temp) || !is_uploaded_file($temp) || !is_string($name)) { fail('A foto enviada é inválida.'); }
    $extension = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    $types = ['jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg', 'png' => 'image/png', 'webp' => 'image/webp'];
    $size = filesize($temp);
    if (!$size || $size > profile_photo_limit()) { fail('A foto deve ter até ' . pretty_size(profile_photo_limit()) . '.'); }
    $image = @getimagesize($temp);
    $mime = (new finfo(FILEINFO_MIME_TYPE))->file($temp);
    if (!isset($types[$extension]) || $types[$extension] !== $mime || !$image || ($image['mime'] ?? '') !== $mime) { fail('Envie uma imagem JPG, PNG ou WebP válida.'); }
    if ($image[0] > 4096 || $image[1] > 4096) { fail('Use uma foto com até 4096 pixels de largura e altura.'); }
    $storage = (string) config('storage_path');
    if (!is_dir($storage) && !mkdir($storage, 0755, true)) { throw new RuntimeException('Armazenamento indisponível.'); }
    $pending = $storage . '/avatar-pending-' . bin2hex(random_bytes(16)) . '.image';
    try {
        if (!move_uploaded_file($temp, $pending)) { throw new RuntimeException('Falha ao armazenar foto.'); }
        @chmod($pending, 0600);
        if (!rename($pending, $storage . '/' . profile_photo_name($user))) { throw new RuntimeException('Falha ao substituir foto.'); }
    } finally {
        if (is_file($pending)) { @unlink($pending); }
    }
    flash('Sua foto foi atualizada.');
    redirect('password');
}

function serve_profile_photo(array $user): void {
    $path = profile_photo_path($user);
    if (!$path) { fail('Foto não encontrada.', 404); }
    $image = @getimagesize($path);
    if (!$image || !in_array($image['mime'] ?? '', ['image/jpeg', 'image/png', 'image/webp'], true)) { fail('Foto não encontrada.', 404); }
    header('Content-Type: ' . $image['mime']);
    header('Content-Length: ' . filesize($path));
    header('Content-Disposition: inline; filename="foto"');
    header("Content-Security-Policy: default-src 'none'; sandbox");
    session_write_close();
    readfile($path);
    exit;
}
