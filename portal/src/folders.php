<?php
declare(strict_types=1);

function file_kinds(): array { return ['material' => 'Materiais', 'trabalho' => 'Trabalhos', 'prova' => 'Provas']; }
function valid_file_kind(string $kind): bool { return isset(file_kinds()[$kind]); }
function file_kind_field(): string {
    $kind = $_POST['kind'] ?? 'material';
    if (!is_string($kind) || !valid_file_kind($kind)) { fail('Selecione uma categoria válida.'); }
    return $kind;
}
function optional_folder_id($value): ?int {
    if ($value === '' || $value === null) { return null; }
    $id = numeric_id($value);
    if (!$id) { fail('Selecione uma pasta válida.'); }
    return $id;
}
function validate_folder_subject(?int $folderId, ?int $subjectId): void {
    if ($folderId !== null && ($subjectId === null || !query('SELECT id FROM hc_portal_folders WHERE id = ? AND subject_id = ?', [$folderId, $subjectId])->fetch())) {
        if (db()->inTransaction()) { db()->rollBack(); }
        fail('A pasta selecionada não pertence à matéria.');
    }
}
function subject_folders(int $subjectId): array {
    return query('SELECT p.*, (SELECT COUNT(*) FROM hc_portal_folders c WHERE c.parent_id = p.id) + (SELECT COUNT(*) FROM hc_portal_files f WHERE f.folder_id = p.id AND f.deleted_at IS NULL) AS item_count FROM hc_portal_folders p WHERE p.subject_id = ? ORDER BY p.name, p.id', [$subjectId])->fetchAll();
}
function folder_record(int $id): array {
    $folder = query('SELECT p.*, s.name AS subject_name FROM hc_portal_folders p JOIN hc_portal_subjects s ON s.id = p.subject_id WHERE p.id = ?', [$id])->fetch();
    if (!$folder) { fail('Pasta não encontrada.', 404); }
    return $folder;
}
function folder_index(array $folders): array { return array_column($folders, null, 'id'); }
function folder_children(array $folders, ?int $parentId): array {
    return array_values(array_filter($folders, function ($folder) use ($parentId) { return ($folder['parent_id'] === null ? null : (int) $folder['parent_id']) === $parentId; }));
}
function folder_path(array $folders, ?int $id): array {
    $index = folder_index($folders); $path = []; $seen = [];
    while ($id !== null && isset($index[$id]) && !isset($seen[$id])) {
        $seen[$id] = true; $folder = $index[$id]; $path[] = $folder;
        $id = $folder['parent_id'] === null ? null : (int) $folder['parent_id'];
    }
    return array_reverse($path);
}
function folder_path_label(array $folders, ?int $id): string {
    return $id === null ? 'Raiz da matéria' : implode(' › ', array_column(folder_path($folders, $id), 'name'));
}
function folder_descendant_ids(array $folders, int $id): array {
    $seen = [$id => true]; $queue = [$id];
    for ($i = 0; $i < count($queue); $i++) {
        foreach (folder_children($folders, $queue[$i]) as $child) {
            $childId = (int) $child['id'];
            if (!isset($seen[$childId])) { $seen[$childId] = true; $queue[] = $childId; }
        }
    }
    return array_slice($queue, 1);
}
function folder_options(int $subjectId, ?int $exclude = null): array {
    $folders = subject_folders($subjectId);
    $excluded = $exclude === null ? [] : array_merge([$exclude], folder_descendant_ids($folders, $exclude));
    $options = [];
    foreach ($folders as $folder) {
        if (!in_array((int) $folder['id'], $excluded, true)) { $options[] = ['id' => (int) $folder['id'], 'label' => folder_path_label($folders, (int) $folder['id'])]; }
    }
    usort($options, function ($a, $b) { return strnatcasecmp($a['label'], $b['label']); });
    return $options;
}
function unique_folder_name(array $folders, ?int $parentId, string $name, ?int $exclude = null): void {
    foreach (folder_children($folders, $parentId) as $folder) {
        if ((int) $folder['id'] !== $exclude && preg_match('~^' . preg_quote($name, '~') . '$~iuD', $folder['name'])) {
            db()->rollBack(); fail('Já existe uma pasta com esse nome neste local.');
        }
    }
}
function redirect_to_folder(?int $folderId, int $subjectId): void {
    redirect($folderId === null ? 'subject' : 'folder', ['id' => $folderId ?? $subjectId]);
}
function create_folder(array $user): void {
    $subjectId = numeric_id($_POST['subject_id'] ?? null);
    $parentId = optional_folder_id($_POST['parent_id'] ?? null);
    $name = field('name', 120);
    db()->beginTransaction();
    try {
        lock_material_subject($subjectId);
        validate_folder_subject($parentId, $subjectId);
        unique_folder_name(subject_folders($subjectId), $parentId, $name);
        query('INSERT INTO hc_portal_folders (subject_id, parent_id, name, created_by) VALUES (?, ?, ?, ?)', [$subjectId, $parentId, $name, $user['id']]);
        db()->commit();
    } catch (Throwable $exception) { if (db()->inTransaction()) { db()->rollBack(); } throw $exception; }
    flash('Pasta criada.'); redirect_to_folder($parentId, $subjectId);
}
function change_folder(string $action): void {
    $id = numeric_id($_POST['id'] ?? null);
    $original = folder_record($id);
    $subjectId = (int) $original['subject_id'];
    $revision = $_POST['revision'] ?? null;
    if (!is_string($revision) || !ctype_digit($revision)) { fail('Reabra a pasta antes de continuar.', 409); }
    if ($action === 'delete') {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão da pasta.'); }
    } else { $name = field('name', 120); $parentId = optional_folder_id($_POST['parent_id'] ?? null); }
    db()->beginTransaction();
    try {
        lock_material_subject($subjectId);
        $folder = query('SELECT * FROM hc_portal_folders WHERE id = ?' . lock_suffix(), [$id])->fetch();
        if (!$folder) { db()->rollBack(); fail('Pasta não encontrada.', 404); }
        if (!hash_equals((string) $folder['revision'], $revision)) { db()->rollBack(); fail('Esta pasta foi alterada. Reabra a página antes de continuar.', 409); }
        $folders = subject_folders($subjectId);
        if ($action === 'delete') {
            if (folder_children($folders, $id) || query('SELECT id FROM hc_portal_files WHERE folder_id = ? AND deleted_at IS NULL LIMIT 1', [$id])->fetch()) {
                db()->rollBack(); fail('Mova ou exclua todas as subpastas e arquivos ativos antes de excluir esta pasta.');
            }
            query('UPDATE hc_portal_files SET folder_id = NULL WHERE folder_id = ?', [$id]);
            query('DELETE FROM hc_portal_folders WHERE id = ?', [$id]);
            $parentId = $folder['parent_id'] === null ? null : (int) $folder['parent_id'];
        } else {
            validate_folder_subject($parentId, $subjectId);
            if ($parentId === $id || in_array($parentId, folder_descendant_ids($folders, $id), true)) { db()->rollBack(); fail('Uma pasta não pode ser movida para si mesma ou para suas descendentes.'); }
            unique_folder_name($folders, $parentId, $name, $id);
            query('UPDATE hc_portal_folders SET name = ?, parent_id = ?, revision = revision + 1 WHERE id = ?', [$name, $parentId, $id]);
        }
        db()->commit();
    } catch (Throwable $exception) { if (db()->inTransaction()) { db()->rollBack(); } throw $exception; }
    flash($action === 'delete' ? 'Pasta excluída.' : 'Pasta atualizada.');
    redirect_to_folder($action === 'delete' ? $parentId : $id, $subjectId);
}
