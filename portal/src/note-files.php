<?php
declare(strict_types=1);

const NOTE_FILE_MAX = 3;
const NOTE_FILE_EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'html'];

function note_file_limit(): int { return min(10 * 1024 * 1024, available_upload_bytes()); }

function note_files(int $noteId): array {
    return query('SELECT * FROM hc_portal_note_files WHERE note_id = ? ORDER BY id', [$noteId])->fetchAll();
}

function note_file_record(int $id, int $owner): array {
    $row = query('SELECT * FROM hc_portal_note_files WHERE id = ? AND user_id = ?', [$id, $owner])->fetch();
    if (!$row) { fail('Arquivo não encontrado.', 404); }
    return $row;
}

function validate_note_upload(array $upload): array {
    $name = $upload['name'] ?? null;
    $extension = is_string($name) ? strtolower(pathinfo($name, PATHINFO_EXTENSION)) : '';
    if (!in_array($extension, NOTE_FILE_EXTENSIONS, true)) { fail('Anexe apenas PDF, PNG, JPEG, JPG, DOCX ou HTML.'); }
    $item = validate_document_upload($upload);
    if ($item['size'] > note_file_limit()) { fail('Cada arquivo deve ter no máximo ' . pretty_size(note_file_limit()) . '.'); }
    return $item;
}

// Lê um campo de upload (lista ou escalar), ignorando campos deixados em branco.
function note_upload_entries(string $field): array {
    $upload = $_FILES[$field] ?? null;
    if (!is_array($upload) || !isset($upload['name'])) { return []; }
    $entries = [];
    $names = is_array($upload['name']) ? $upload['name'] : [$upload['name']];
    foreach ($names as $key => $name) {
        $error = is_array($upload['name']) ? ($upload['error'][$key] ?? UPLOAD_ERR_NO_FILE) : $upload['error'];
        if ($error === UPLOAD_ERR_NO_FILE) { continue; }
        $entries[$key] = ['name' => $name, 'error' => $error, 'tmp_name' => is_array($upload['name']) ? ($upload['tmp_name'][$key] ?? '') : $upload['tmp_name']];
    }
    return $entries;
}

// Valida tudo antes de abrir a transação: novos arquivos, substituições e remoções pedidas.
function read_note_file_changes(): array {
    $add = note_upload_entries('attachments');
    if (count($add) > NOTE_FILE_MAX) { fail('Cada anotação aceita até ' . NOTE_FILE_MAX . ' arquivos.'); }
    $replace = note_upload_entries('replace');
    $remove = $_POST['remove_files'] ?? [];
    if (!is_array($remove)) { fail('Seleção de arquivos inválida.'); }
    $removeIds = [];
    foreach ($remove as $value) {
        if (!is_string($value) || !ctype_digit($value) || (int) $value < 1) { fail('Seleção de arquivos inválida.'); }
        $removeIds[(int) $value] = true;
    }
    $changes = ['add' => [], 'replace' => [], 'remove' => array_keys($removeIds)];
    foreach ($add as $entry) { $changes['add'][] = validate_note_upload($entry); }
    foreach ($replace as $key => $entry) {
        if (!is_int($key) && !(is_string($key) && ctype_digit($key))) { fail('Seleção de arquivos inválida.'); }
        if (isset($removeIds[(int) $key])) { fail('Escolha substituir ou remover o mesmo arquivo, não os dois.'); }
        $changes['replace'][(int) $key] = validate_note_upload($entry);
    }
    $total = array_sum(array_column($changes['add'], 'size')) + array_sum(array_column($changes['replace'], 'size'));
    if ($total > available_upload_total_bytes()) { fail('Os arquivos excedem o limite total de ' . pretty_size(available_upload_total_bytes()) . '. Envie menos arquivos por vez.', 413); }
    return $changes;
}

function store_note_upload(array $item, array &$moved): void {
    $storage = (string) config('storage_path');
    if (!is_dir($storage) && !mkdir($storage, 0755, true)) { throw new RuntimeException('Não foi possível criar o armazenamento.'); }
    $target = $storage . '/' . $item['stored_path'];
    if (!move_uploaded_file($item['temp'], $target)) { throw new RuntimeException('Falha ao armazenar upload.'); }
    $moved[] = $target;
    @chmod($target, 0600);
}

// Roda dentro da transação, com a anotação já travada. Devolve os arquivos físicos a apagar após o commit.
function apply_note_file_changes(int $noteId, int $owner, array $changes, array &$moved): array {
    $current = [];
    foreach (note_files($noteId) as $row) { $current[(int) $row['id']] = $row; }
    foreach (array_merge($changes['remove'], array_keys($changes['replace'])) as $id) {
        if (!isset($current[$id])) { if (db()->inTransaction()) { db()->rollBack(); } fail('Um dos arquivos selecionados não pertence a esta anotação.', 400); }
    }
    if (count($current) - count($changes['remove']) + count($changes['add']) > NOTE_FILE_MAX) {
        if (db()->inTransaction()) { db()->rollBack(); }
        fail('Cada anotação aceita até ' . NOTE_FILE_MAX . ' arquivos. Remova algum antes de adicionar outro.');
    }
    $obsolete = [];
    foreach ($changes['remove'] as $id) {
        query('DELETE FROM hc_portal_note_files WHERE id = ? AND note_id = ? AND user_id = ?', [$id, $noteId, $owner]);
        $obsolete[] = $current[$id];
    }
    foreach ($changes['replace'] as $id => $item) {
        store_note_upload($item, $moved);
        query('UPDATE hc_portal_note_files SET original_name = ?, stored_path = ?, extension = ?, mime = ?, size = ?, sha256 = ?, created_at = CURRENT_TIMESTAMP WHERE id = ? AND note_id = ? AND user_id = ?', [$item['name'], $item['stored_path'], $item['extension'], $item['mime'], $item['size'], $item['sha256'], $id, $noteId, $owner]);
        $obsolete[] = $current[$id];
    }
    foreach ($changes['add'] as $item) {
        store_note_upload($item, $moved);
        query('INSERT INTO hc_portal_note_files (note_id, user_id, original_name, stored_path, extension, mime, size, sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [$noteId, $owner, $item['name'], $item['stored_path'], $item['extension'], $item['mime'], $item['size'], $item['sha256']]);
    }
    return $obsolete;
}

function remove_note_binaries(array $rows): void {
    foreach ($rows as $row) { remove_uploaded_binary(['id' => $row['id'], 'source' => 'upload', 'stored_path' => $row['stored_path']]); }
}

function note_file_return(int $noteId): void {
    if (($_POST['return'] ?? '') === 'edit') { redirect('edit-note', ['id' => $noteId]); }
    redirect_back_to_modal('view-note', ['id' => $noteId], 'abrir-nota-' . $noteId);
}

// Substitui ou exclui um único arquivo direto da página da anotação.
function change_note_file(array $user, bool $delete): void {
    $fileId = numeric_id($_POST['id'] ?? null);
    $file = note_file_record($fileId, (int) $user['id']);
    $noteId = (int) $file['note_id'];
    $changes = ['add' => [], 'replace' => [], 'remove' => []];
    if ($delete) {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão do arquivo.'); }
        $changes['remove'][] = $fileId;
    } else {
        $entries = note_upload_entries('file');
        if (count($entries) !== 1) { fail('Escolha o arquivo substituto.'); }
        $item = validate_note_upload(reset($entries));
        if ($item['size'] > available_upload_total_bytes()) { fail('O arquivo excede o limite total de ' . pretty_size(available_upload_total_bytes()) . '.', 413); }
        $changes['replace'][$fileId] = $item;
    }
    $moved = []; $obsolete = [];
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        note_record($noteId, (int) $user['id'], true);
        $obsolete = apply_note_file_changes($noteId, (int) $user['id'], $changes, $moved);
        query('UPDATE hc_portal_notes SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?', [$noteId, $user['id']]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } foreach ($moved as $path) { @unlink($path); } throw $error; }
    remove_note_binaries($obsolete);
    flash($delete ? 'Arquivo excluído.' : 'Arquivo substituído.'); note_file_return($noteId);
}

// Adiciona arquivos pela página da anotação, respeitando o mesmo limite, formatos e tamanho do formulário.
function add_note_files(array $user): void {
    $noteId = numeric_id($_POST['note_id'] ?? null);
    note_record($noteId, (int) $user['id']);
    $changes = read_note_file_changes();
    if (!$changes['add']) { fail('Escolha ao menos um arquivo.'); }
    $moved = []; $obsolete = [];
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        note_record($noteId, (int) $user['id'], true);
        $obsolete = apply_note_file_changes($noteId, (int) $user['id'], $changes, $moved);
        query('UPDATE hc_portal_notes SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?', [$noteId, $user['id']]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } foreach ($moved as $path) { @unlink($path); } throw $error; }
    remove_note_binaries($obsolete);
    flash(count($changes['add']) === 1 ? 'Arquivo adicionado.' : 'Arquivos adicionados.'); note_file_return($noteId);
}

function serve_note_file(array $user, bool $download): void {
    $row = note_file_record(numeric_id($_GET['id'] ?? null), (int) $user['id']);
    serve_document(['source' => 'upload', 'trusted_app' => 0, 'stored_path' => $row['stored_path'], 'extension' => $row['extension'], 'original_name' => $row['original_name']], $download);
}

function render_note_file_list(array $files, bool $manage = false, string $return = ''): void { ?>
<ul class="note-file-list"><?php foreach ($files as $file): ?><li><span class="file-badge ext-<?= e($file['extension']) ?>"><?= e(strtoupper($file['extension'])) ?></span><span class="note-file-name"><strong><?= e($file['original_name']) ?></strong><small><?= e(pretty_size((int) $file['size'])) ?></small></span><span class="note-file-actions"><?php if (can_preview($file)): ?><a class="button button-primary note-edit-button" href="<?= e(url('note-file', ['id' => $file['id']])) ?>" target="_blank" rel="noopener" title="Abrir arquivo"><?= icon('eye') ?><span class="sr-only">Abrir arquivo <?= e($file['original_name']) ?></span></a><?php endif; ?><a class="button button-primary note-edit-button" href="<?= e(url('note-file-download', ['id' => $file['id']])) ?>" title="Baixar arquivo"><?= icon('download') ?><span class="sr-only">Baixar arquivo <?= e($file['original_name']) ?></span></a><?php if ($manage): ?><form method="post" enctype="multipart/form-data" action="<?= e(url('update-note-file')) ?>" class="note-file-form"><?= csrf() ?><?php if ($return !== ''): ?><input type="hidden" name="return" value="<?= e($return) ?>"><?php endif; ?><input type="hidden" name="id" value="<?= (int) $file['id'] ?>"><label class="button button-primary note-edit-button note-file-replace" title="Substituir arquivo"><?= icon('edit') ?><span class="sr-only">Substituir arquivo <?= e($file['original_name']) ?></span><input type="file" class="sr-only" name="file" accept=".pdf,.png,.jpg,.jpeg,.docx,.html" required data-auto-submit></label><noscript><button type="submit" class="button button-primary">Salvar arquivo</button></noscript></form><form method="post" action="<?= e(url('delete-note-file')) ?>" class="note-file-form"><?= csrf() ?><?php if ($return !== ''): ?><input type="hidden" name="return" value="<?= e($return) ?>"><?php endif; ?><input type="hidden" name="id" value="<?= (int) $file['id'] ?>"><input type="hidden" name="confirm" value="1" disabled data-swal-enable><noscript><label class="confirmation-check"><input type="checkbox" name="confirm" value="1" required>Confirmo a exclusão do arquivo.</label></noscript><button class="button button-primary note-edit-button" type="submit" title="Excluir arquivo" data-swal-confirm><?= icon('trash') ?><span class="sr-only">Excluir arquivo <?= e($file['original_name']) ?></span></button></form><?php endif; ?></span></li><?php endforeach; ?></ul>
<?php }

function render_note_files(array $files, int $noteId, string $return = ''): void {
    $full = count($files) >= NOTE_FILE_MAX; ?>
<section class="form-card note-files<?= $return === 'edit' ? ' note-files-edit' : '' ?>" aria-labelledby="note-files-heading"><div class="note-files-heading"><h2 id="note-files-heading">Arquivos</h2><form method="post" enctype="multipart/form-data" action="<?= e(url('add-note-files')) ?>" class="note-file-form"><?= csrf() ?><input type="hidden" name="note_id" value="<?= $noteId ?>"><?php if ($return !== ''): ?><input type="hidden" name="return" value="<?= e($return) ?>"><?php endif; ?><label class="button button-primary note-file-replace<?= $full ? ' is-disabled' : '' ?>" title="<?= $full ? 'Limite de ' . NOTE_FILE_MAX . ' arquivos atingido' : 'Adicionar arquivo' ?>"><?= icon('plus') ?><span>Adicionar</span><input type="file" class="sr-only" name="attachments[]" multiple accept=".pdf,.png,.jpg,.jpeg,.docx,.html" required data-auto-submit data-max-files="<?= max(0, NOTE_FILE_MAX - count($files)) ?>" data-total-files="<?= NOTE_FILE_MAX ?>" data-max-bytes="<?= note_file_limit() ?>"<?= $full ? ' disabled' : '' ?>></label><noscript><button type="submit" class="button button-primary">Enviar arquivos</button></noscript></form></div><?php if ($files): render_note_file_list($files, true, $return); else: ?><p class="muted">Nenhum arquivo.</p><?php endif; ?></section>
<?php }

function render_note_file_fields(?array $note, bool $modal = false): void {
    $files = $note ? note_files((int) $note['id']) : []; ?>
<fieldset class="note-attachments" data-note-files data-max-files="<?= NOTE_FILE_MAX ?>" data-max-bytes="<?= note_file_limit() ?>"><legend>Arquivos da anotação</legend><?php if (!$modal): ?><p class="form-hint">Até <?= NOTE_FILE_MAX ?> arquivos por anotação: PDF, PNG, JPEG, JPG, DOCX ou HTML, com até <?= e(pretty_size(note_file_limit())) ?> cada. Só você pode ver, alterar ou excluir.</p><?php endif; ?>
<?php if ($files): ?><ul class="note-file-list"><?php foreach ($files as $file): ?><li><span class="file-badge ext-<?= e($file['extension']) ?>"><?= e(strtoupper($file['extension'])) ?></span><span class="note-file-name"><strong><?= e($file['original_name']) ?></strong><small><?= e(pretty_size((int) $file['size'])) ?></small></span><span class="note-file-edit"><label>Substituir<input type="file" name="replace[<?= (int) $file['id'] ?>]" accept=".pdf,.png,.jpg,.jpeg,.docx,.html"></label><label class="confirmation-check"><input type="checkbox" name="remove_files[]" value="<?= (int) $file['id'] ?>" data-remove-note-file>Remover</label></span></li><?php endforeach; ?></ul><?php endif; ?>
<label>Adicionar arquivos<input type="file" name="attachments[]" multiple accept=".pdf,.png,.jpg,.jpeg,.docx,.html" data-note-attachments data-existing="<?= count($files) ?>"></label><ul class="note-file-list note-selected-files" data-note-selected hidden></ul><template data-note-selected-item><li><span class="file-badge" data-selected-ext></span><span class="note-file-name"><strong data-selected-name></strong><small data-selected-size></small></span><span class="note-file-actions"><button type="button" class="button button-primary note-edit-button" data-selected-remove title="Remover arquivo"><?= icon('trash') ?><span class="sr-only" data-selected-label></span></button></span></li></template><?php if ($modal): ?><p class="form-hint">Até <?= NOTE_FILE_MAX ?> arquivos por anotação: PDF, PNG, JPEG, JPG, DOCX ou HTML, com até <?= e(pretty_size(note_file_limit())) ?> cada</p><?php endif; ?><p class="form-error" data-note-files-error role="alert" hidden></p></fieldset>
<?php }
