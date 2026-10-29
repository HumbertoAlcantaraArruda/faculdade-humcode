<?php
declare(strict_types=1);

// Vídeo aulas do YouTube. Cada matéria pode ter nenhuma ou muitas, em ordem definida pelo administrador.

function youtube_video_id(string $link): ?string {
    $link = trim($link);
    if ($link === '' || strlen($link) > 300 || preg_match('/[\x00-\x20\x7F\\\\]/', $link)) { return null; }
    if (!preg_match('~^[a-z][a-z0-9+.-]*://~i', $link)) { $link = 'https://' . $link; }
    $parts = parse_url($link);
    if ($parts === false || !in_array(strtolower($parts['scheme'] ?? ''), ['http', 'https'], true) || isset($parts['user']) || isset($parts['pass']) || isset($parts['port'])) { return null; }
    $host = strtolower($parts['host'] ?? '');
    $path = $parts['path'] ?? '/';
    $candidate = null;
    if ($host === 'youtu.be') {
        $candidate = explode('/', ltrim($path, '/'))[0];
    } elseif (in_array($host, ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'], true)) {
        if ($path === '/watch') {
            parse_str($parts['query'] ?? '', $query);
            $candidate = is_string($query['v'] ?? null) ? $query['v'] : null;
        } elseif (preg_match('~^/(?:shorts|embed|live|v)/([^/]+)/?$~', $path, $match)) {
            $candidate = $match[1];
        }
    }
    return is_string($candidate) && preg_match('/^[A-Za-z0-9_-]{11}$/', $candidate) ? $candidate : null;
}
function video_embed_url(string $id): string { return 'https://www.youtube-nocookie.com/embed/' . rawurlencode($id) . '?rel=0'; }
function video_watch_url(string $id): string { return 'https://www.youtube.com/watch?v=' . rawurlencode($id); }
function video_thumbnail_url(string $id): string { return 'https://i.ytimg.com/vi/' . rawurlencode($id) . '/mqdefault.jpg'; }

function subject_videos(int $subjectId): array {
    return query('SELECT * FROM hc_portal_videos WHERE subject_id = ? ORDER BY sort_order, id', [$subjectId])->fetchAll();
}
function video_record(int $id): array {
    $video = query('SELECT v.*, s.name AS subject_name FROM hc_portal_videos v JOIN hc_portal_subjects s ON s.id = v.subject_id WHERE v.id = ?', [$id])->fetch();
    if (!$video) { fail('Vídeo não encontrado.', 404); }
    return $video;
}
function lock_suffix(): string { return db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : ''; }
function redirect_to_videos(int $subjectId): void { header('Location: ' . subject_url($subjectId) . '#videos', true, 303); exit; }
function video_link_field(): string {
    $id = youtube_video_id(field('url', 300));
    if ($id === null) { fail('Informe um link válido de vídeo do YouTube, como https://www.youtube.com/watch?v=… ou https://youtu.be/….'); }
    return $id;
}

function create_video(array $user): void {
    $subjectId = numeric_id($_POST['subject_id'] ?? null);
    $title = field('title', 180);
    $youtubeId = video_link_field();
    db()->beginTransaction();
    try {
        lock_material_subject($subjectId);
        $next = (int) query('SELECT COALESCE(MAX(sort_order), 0) + 1 FROM hc_portal_videos WHERE subject_id = ?', [$subjectId])->fetchColumn();
        query('INSERT INTO hc_portal_videos (subject_id, title, youtube_id, sort_order, created_by) VALUES (?, ?, ?, ?, ?)', [$subjectId, $title, $youtubeId, $next, $user['id']]);
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        throw $exception;
    }
    flash('Vídeo adicionado à matéria.');
    redirect_to_videos($subjectId);
}

function change_video(bool $delete): void {
    $id = numeric_id($_POST['id'] ?? null);
    $revision = $_POST['revision'] ?? null;
    if (!is_string($revision) || !ctype_digit($revision)) { fail('Reabra o vídeo antes de continuar.', 409); }
    if ($delete) {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a remoção do vídeo.'); }
    } else {
        $title = field('title', 180);
        $youtubeId = video_link_field();
    }
    db()->beginTransaction();
    try {
        $video = query('SELECT * FROM hc_portal_videos WHERE id = ?' . lock_suffix(), [$id])->fetch();
        if (!$video) { db()->rollBack(); fail('Vídeo não encontrado.', 404); }
        if (!hash_equals((string) $video['revision'], $revision)) {
            db()->rollBack(); fail('Este vídeo foi alterado. Reabra a página antes de continuar.', 409);
        }
        if ($delete) { query('DELETE FROM hc_portal_videos WHERE id = ?', [$id]); }
        else {
            query('UPDATE hc_portal_videos SET title = ?, youtube_id = ?, revision = revision + 1 WHERE id = ?', [$title, $youtubeId, $id]);
            if ($video['youtube_id'] !== $youtubeId) { query('DELETE FROM hc_portal_video_study WHERE video_id = ?', [$id]); }
        }
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        throw $exception;
    }
    flash($delete ? 'Vídeo removido da matéria.' : 'Vídeo atualizado.');
    redirect_to_videos((int) $video['subject_id']);
}

function move_video(): void {
    $id = numeric_id($_POST['id'] ?? null);
    $direction = $_POST['direction'] ?? '';
    if (!in_array($direction, ['up', 'down'], true)) { fail('Direção inválida.'); }
    $subjectId = (int) query('SELECT subject_id FROM hc_portal_videos WHERE id = ?', [$id])->fetchColumn();
    if ($subjectId === 0) { fail('Vídeo não encontrado.', 404); }
    db()->beginTransaction();
    try {
        // A matéria é o ponto de serialização: duas trocas simultâneas não embaralham a ordem.
        lock_material_subject($subjectId);
        $ids = array_map('intval', query('SELECT id FROM hc_portal_videos WHERE subject_id = ? ORDER BY sort_order, id', [$subjectId])->fetchAll(PDO::FETCH_COLUMN));
        $index = array_search($id, $ids, true);
        if ($index === false) { db()->rollBack(); fail('Vídeo não encontrado.', 404); }
        $other = $direction === 'up' ? $index - 1 : $index + 1;
        if (isset($ids[$other])) {
            [$ids[$index], $ids[$other]] = [$ids[$other], $ids[$index]];
            foreach ($ids as $position => $videoId) { query('UPDATE hc_portal_videos SET sort_order = ? WHERE id = ?', [$position + 1, $videoId]); }
        }
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        throw $exception;
    }
    redirect_to_videos($subjectId);
}
