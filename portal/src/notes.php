<?php
declare(strict_types=1);

const NOTE_IMPORTANT_MAX = 5;
const NOTES_PAGE_SIZE = 12;

// Quantas anotações importantes o usuário já tem na matéria (ou sem matéria), ignorando uma anotação.
function important_count(int $owner, ?int $subject, int $except = 0): int {
    $sql = 'SELECT COUNT(*) FROM hc_portal_notes WHERE user_id = ? AND important = 1 AND id <> ? AND ' . ($subject === null ? 'subject_id IS NULL' : 'subject_id = ?');
    return (int) query($sql, $subject === null ? [$owner, $except] : [$owner, $except, $subject])->fetchColumn();
}

function important_limit_message(?int $subject): string {
    return $subject === null ? 'As anotações sem matéria já têm ' . NOTE_IMPORTANT_MAX . ' importantes. Remova uma para marcar outra.' : 'Esta matéria já tem ' . NOTE_IMPORTANT_MAX . ' anotações importantes. Remova uma para marcar outra.';
}

// Mantém só as mais recentes como importantes quando um grupo passa do limite (por exemplo, ao excluir uma matéria).
function trim_important_notes(int $owner, ?int $subject): void {
    $sql = 'SELECT id FROM hc_portal_notes WHERE user_id = ? AND important = 1 AND ' . ($subject === null ? 'subject_id IS NULL' : 'subject_id = ?') . ' ORDER BY updated_at DESC, id DESC';
    $ids = query($sql, $subject === null ? [$owner] : [$owner, $subject])->fetchAll(PDO::FETCH_COLUMN);
    foreach (array_slice($ids, NOTE_IMPORTANT_MAX) as $id) { query('UPDATE hc_portal_notes SET important = 0 WHERE id = ? AND user_id = ?', [(int) $id, $owner]); }
}

function toggle_note_important(array $user): void {
    $id = numeric_id($_POST['id'] ?? null);
    $want = ($_POST['important'] ?? '') === '1' ? 1 : (($_POST['important'] ?? '') === '0' ? 0 : null);
    if ($want === null) { fail('Informe se a anotação é importante.'); }
    note_record($id, (int) $user['id']);
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $note = note_record($id, (int) $user['id'], true);
        $subject = $note['subject_id'] === null ? null : (int) $note['subject_id'];
        if ($want === 1 && (int) $note['important'] !== 1 && important_count((int) $user['id'], $subject, $id) >= NOTE_IMPORTANT_MAX) { db()->rollBack(); fail(important_limit_message($subject), 409); }
        query('UPDATE hc_portal_notes SET important = ? WHERE id = ? AND user_id = ?', [$want, $id, $user['id']]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($want === 1 ? 'Anotação marcada como importante.' : 'Anotação removida dos importantes.');
    redirect_back_to_modal('view-note', ['id' => $id], 'abrir-nota-' . $id);
}

function note_record(int $id, int $owner, bool $lock = false): array {
    $row = query('SELECT n.*, s.name AS subject_name FROM hc_portal_notes n LEFT JOIN hc_portal_subjects s ON s.id = n.subject_id WHERE n.id = ? AND n.user_id = ?' . ($lock ? lock_suffix() : ''), [$id, $owner])->fetch();
    if (!$row) { if (db()->inTransaction()) { db()->rollBack(); } fail('Anotação não encontrada.', 404); }
    return $row;
}

function save_note(array $user, bool $update): void {
    $id = numeric_id($_POST['id'] ?? null);
    if ($update) { note_record($id, (int) $user['id']); }
    $title = field('title', 180); $body = field('body', 20000);
    $raw = $_POST['subject_id'] ?? '';
    if (!is_string($raw) || ($raw !== '' && (!ctype_digit($raw) || (int) $raw < 1))) { fail('Selecione uma matéria válida.'); }
    $subject = $raw === '' ? null : (int) $raw;
    $changes = read_note_file_changes(); $moved = []; $obsolete = [];
    db()->beginTransaction();
    try {
        if ($subject !== null) { lock_material_subject($subject); }
        lock_event_user((int) $user['id']);
        if ($update) {
            $note = note_record($id, (int) $user['id'], true);
            if (!is_string($_POST['revision'] ?? null) || (string) $note['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Esta anotação foi alterada. Reabra a página antes de continuar.', 409); }
            $currentSubject = $note['subject_id'] === null ? null : (int) $note['subject_id'];
            if ((int) $note['important'] === 1 && $currentSubject !== $subject && important_count((int) $user['id'], $subject, $id) >= NOTE_IMPORTANT_MAX) { db()->rollBack(); fail(important_limit_message($subject), 409); }
            query('UPDATE hc_portal_notes SET title = ?, body = ?, subject_id = ?, revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?', [$title, $body, $subject, $id, $user['id']]);
        } else {
            query('INSERT INTO hc_portal_notes (user_id, subject_id, title, body) VALUES (?, ?, ?, ?)', [$user['id'], $subject, $title, $body]);
            $id = (int) db()->lastInsertId();
        }
        $obsolete = apply_note_file_changes($id, (int) $user['id'], $changes, $moved);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } foreach ($moved as $path) { @unlink($path); } throw $error; }
    remove_note_binaries($obsolete);
    flash($update ? 'Anotação atualizada.' : 'Anotação criada.'); redirect('view-note', ['id' => $id]);
}

function delete_note(array $user): void {
    $id = numeric_id($_POST['id'] ?? null);
    note_record($id, (int) $user['id']);
    if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão da anotação.'); }
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']); $note = note_record($id, (int) $user['id'], true);
        if (!is_string($_POST['revision'] ?? null) || (string) $note['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Esta anotação foi alterada. Reabra a página antes de continuar.', 409); }
        $files = note_files($id);
        query('DELETE FROM hc_portal_note_files WHERE note_id = ? AND user_id = ?', [$id, $user['id']]);
        query('DELETE FROM hc_portal_notes WHERE id = ? AND user_id = ?', [$id, $user['id']]); db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    remove_note_binaries($files);
    flash('Anotação excluída.'); redirect('notes', ['subject_id' => $note['subject_id'] ?? '0']);
}

function render_note_row(array $note): void {
    preg_match('/^.{0,160}/us', $note['body'], $excerpt); ?>
<article class="note-card<?= !empty($note['important']) ? ' is-important' : '' ?>" data-note-row="<?= (int) $note['id'] ?>"><?php if (!empty($note['important'])): ?><span class="note-important-badge" data-note-important><?= icon('star') ?>Importante</span><?php endif; ?><h3 class="note-card-title"><a href="<?= e(url('view-note', ['id' => $note['id']])) ?>" data-detail-link data-detail-key="abrir-nota-<?= (int) $note['id'] ?>"><?= e($note['title']) ?></a></h3><p class="note-card-meta"><?= e($note['subject_name'] ?? 'Sem matéria') ?> - <?= e(pretty_date($note['updated_at'])) ?></p><p class="note-card-excerpt"><?= e($excerpt[0] ?? '') ?><?= preg_match_all('/./us', $note['body']) > 160 ? '...' : '' ?></p></article>
<?php }

function render_subject_notes(int $subject): void {
    $owner = (int) current_user()['id'];
    $count = (int) query('SELECT COUNT(*) FROM hc_portal_notes WHERE user_id = ? AND subject_id = ?', [$owner, $subject])->fetchColumn();
    $notes = query('SELECT n.*, s.name AS subject_name FROM hc_portal_notes n JOIN hc_portal_subjects s ON s.id = n.subject_id WHERE n.user_id = ? AND n.subject_id = ? ORDER BY n.important DESC, n.updated_at DESC, n.id DESC LIMIT 5', [$owner, $subject])->fetchAll(); ?>
<section class="private-notes" aria-labelledby="subject-notes-heading"><div class="calendar-toolbar"><div><h2 id="subject-notes-heading">Minhas anotações</h2><p class="muted" data-note-count="<?= $count ?>">Só você pode ver estas anotações.</p></div><button type="button" class="button button-secondary" data-open="note-dialog"><?= icon('plus') ?>Nova anotação</button></div><?php if (!$notes): ?><p class="muted">Registre seus resumos, dúvidas e observações.</p><?php endif; ?><?php if ($notes): ?><div class="note-grid"><?php foreach ($notes as $note): render_note_row($note); endforeach; ?></div><?php endif; ?><a href="<?= e(url('notes', ['subject_id' => $subject])) ?>">Ver todas as anotações desta matéria (<?= $count ?>)</a></section><?php render_note_dialog($subject); ?>
<?php }

function notes_filter(array $user): array {
    $raw = $_GET['subject_id'] ?? '';
    if (!is_string($raw) || ($raw !== '' && !ctype_digit($raw))) { fail('Selecione uma matéria válida.'); }
    $where = 'n.user_id = ?'; $params = [$user['id']];
    if ($raw === '0') { $where .= ' AND n.subject_id IS NULL'; }
    elseif ($raw !== '') { subject_record((int) $raw); $where .= ' AND n.subject_id = ?'; $params[] = (int) $raw; }
    return [$raw, $where, $params];
}

// As importantes vêm primeiro; dentro de cada grupo, as alteradas mais recentemente.
function notes_page_rows(string $where, array $params, int $page, int $size): array {
    return query('SELECT n.*, s.name AS subject_name FROM hc_portal_notes n LEFT JOIN hc_portal_subjects s ON s.id = n.subject_id WHERE ' . $where . ' ORDER BY n.important DESC, n.updated_at DESC, n.id DESC LIMIT ' . $size . ' OFFSET ' . (($page - 1) * $size), $params)->fetchAll();
}

function note_card_data(array $note): array {
    preg_match('/^.{0,160}/us', $note['body'], $excerpt);
    return ['id' => (int) $note['id'], 'title' => $note['title'], 'subject' => $note['subject_name'] ?? 'Sem matéria', 'date' => pretty_date($note['updated_at']), 'excerpt' => ($excerpt[0] ?? '') . (preg_match_all('/./us', $note['body']) > 160 ? '...' : ''), 'important' => (int) $note['important'] === 1, 'url' => url('view-note', ['id' => $note['id']])];
}

// Alimenta a tabela da rota /anotacoes com paginação remota (page e size, como o Tabulator envia).
function render_notes_data(array $user): void {
    [$raw, $where, $params] = notes_filter($user);
    $size = min(NOTES_PAGE_SIZE, max(1, numeric_id($_GET['size'] ?? NOTES_PAGE_SIZE)));
    $total = (int) query('SELECT COUNT(*) FROM hc_portal_notes n WHERE ' . $where, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / $size)); $page = min($pages, max(1, numeric_id($_GET['page'] ?? 1)));
    $rows = array_map('note_card_data', notes_page_rows($where, $params, $page, $size));
    header('Content-Type: application/json; charset=utf-8'); header('Cache-Control: no-store');
    echo json_encode(['last_page' => $pages, 'total' => $total, 'data' => $rows], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT);
}

function render_notes(array $user): void {
    [$raw, $where, $params] = notes_filter($user);
    $total = (int) query('SELECT COUNT(*) FROM hc_portal_notes n WHERE ' . $where, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / NOTES_PAGE_SIZE)); $page = min($pages, max(1, numeric_id($_GET['pagina'] ?? 1)));
    $notes = notes_page_rows($where, $params, $page, NOTES_PAGE_SIZE);
    page_start('Minhas anotações', 'notes'); ?>
<link rel="stylesheet" href="<?= e(config('base_path')) ?>/portal/assets/vendor/tabulator-6.3.1.min.css"><script src="<?= e(config('base_path')) ?>/portal/assets/vendor/tabulator-6.3.1.min.js" defer></script>
<div class="page-heading"><div><h1>Minhas anotações</h1><p>Resumos, dúvidas e observações privados.</p></div><button type="button" class="button button-primary" data-open="note-dialog"><?= icon('plus') ?>Nova anotação</button></div><section class="form-card notes-card"><form method="get" action="<?= e(url('notes')) ?>" class="notes-filter-form"><label for="notes-subject-filter">Filtrar anotações por matéria</label><div class="notes-filter-group"><select id="notes-subject-filter" name="subject_id" aria-label="Filtrar anotações por matéria"><option value="">Todas as matérias</option><option value="0" <?= $raw === '0' ? 'selected' : '' ?>>Sem matéria</option><?php foreach (subject_list() as $subject): ?><option value="<?= (int) $subject['id'] ?>" <?= (string) $subject['id'] === $raw ? 'selected' : '' ?>><?= e($subject['name']) ?></option><?php endforeach; ?></select><button class="button button-secondary" type="submit" title="Filtrar"><?= icon('search') ?><span>Filtrar</span></button></div></form><p class="muted" data-note-total="<?= $total ?>"><?= $total ?> anotações</p><div class="notes-table" data-notes-table data-url="<?= e(url('notes-data')) ?>" data-subject="<?= e($raw) ?>" data-size="<?= NOTES_PAGE_SIZE ?>"></div><noscript><?php if (!$notes): ?><p>Nenhuma anotação encontrada.</p><?php endif; ?><?php if ($notes): ?><div class="note-grid"><?php foreach ($notes as $note): render_note_row($note); endforeach; ?></div><?php endif; ?></noscript></section>
<?php render_note_dialog($raw !== '' && $raw !== '0' ? (int) $raw : null); ?>
<?php if ($pages > 1): ?><noscript><nav class="calendar-toolbar" aria-label="Paginação de anotações"><?php if ($page > 1): ?><a href="<?= e(url('notes', ['subject_id' => $raw, 'pagina' => $page - 1])) ?>">Anterior</a><?php endif; ?><span>Página <?= $page ?> de <?= $pages ?></span><?php if ($page < $pages): ?><a href="<?= e(url('notes', ['subject_id' => $raw, 'pagina' => $page + 1])) ?>">Próxima</a><?php endif; ?></nav></noscript><?php endif; page_end();
}

function render_note_dialog(?int $subject): void { ?>
<dialog id="note-dialog" class="modal modal-wide" aria-labelledby="note-dialog-title"><div class="modal-heading"><div><span class="eyebrow">ANOTAÇÃO PRIVADA</span><h2 id="note-dialog-title">Nova anotação</h2></div><button type="button" class="icon-button" data-close aria-label="Fechar"><?= icon('close') ?></button></div><form method="post" enctype="multipart/form-data" action="<?= e(url('create-note')) ?>"><?= csrf() ?><label>Título<input name="title" maxlength="180" required></label><label>Matéria<select name="subject_id"><option value="">Sem matéria</option><?php foreach (subject_list() as $row): ?><option value="<?= (int) $row['id'] ?>" <?= $subject === (int) $row['id'] ? 'selected' : '' ?>><?= e($row['name']) ?></option><?php endforeach; ?></select></label><label for="note-body">Conteúdo</label><textarea id="note-body" class="note-editor" name="body" rows="10" maxlength="20000" required></textarea><?php render_note_file_fields(null, true); ?><div class="modal-actions"><button type="button" class="button button-secondary" data-close>Cancelar</button><button class="button button-primary" type="submit"><?= icon('check') ?>Salvar anotação</button></div></form></dialog>
<?php }

function render_note_form(?array $note): void {
    $raw = $_GET['subject_id'] ?? '';
    if (!$note && (!is_string($raw) || ($raw !== '' && !ctype_digit($raw)))) { fail('Selecione uma matéria válida.'); }
    $subject = $note ? $note['subject_id'] : ($raw === '' ? null : numeric_id($raw));
    if ($subject !== null) { subject_record((int) $subject); }
    page_start($note ? 'Editar anotação' : 'Nova anotação', 'notes'); ?>
<a class="back-link" href="<?= e($note ? url('view-note', ['id' => $note['id']]) : url('notes', ['subject_id' => $subject ?? '0'])) ?>"><?= icon('back') ?>Voltar</a><div class="page-heading"><div><h1><?= $note ? 'Editar anotação' : 'Nova anotação' ?></h1><p>Esta anotação é privada.</p></div></div><section class="form-card form-card-centered"><form method="post" enctype="multipart/form-data" action="<?= e(url($note ? 'update-note' : 'create-note')) ?>"><?= csrf() ?><?php if ($note): ?><input type="hidden" name="id" value="<?= (int) $note['id'] ?>"><input type="hidden" name="revision" value="<?= (int) $note['revision'] ?>"><?php endif; ?><label>Título<input name="title" maxlength="180" value="<?= e($note['title'] ?? '') ?>" required></label><label>Matéria<select name="subject_id"><option value="">Sem matéria</option><?php foreach (subject_list() as $row): ?><option value="<?= (int) $row['id'] ?>" <?= (int) $subject === (int) $row['id'] ? 'selected' : '' ?>><?= e($row['name']) ?></option><?php endforeach; ?></select></label><label for="note-body">Conteúdo</label><textarea id="note-body" class="note-editor" name="body" rows="12" maxlength="20000" required><?= e($note['body'] ?? '') ?></textarea><p class="form-hint">Texto simples, até 20.000 caracteres. Ao excluir a matéria, a anotação será preservada em Minhas anotações, sem matéria.</p><?php if (!$note) { render_note_file_fields($note); } ?><button class="button button-primary" type="submit"><?= icon('check') ?>Salvar anotação</button></form></section><?php if ($note) { render_note_files(note_files((int) $note['id']), (int) $note['id'], 'edit'); } ?>
<?php page_end();
}

function render_note(array $note): void {
    detail_start('Anotação', 'notes'); ?>
<?php if (!modal_request()): ?><a class="back-link" href="<?= e(url('notes', ['subject_id' => $note['subject_id'] ?? '0'])) ?>"><?= icon('back') ?>Voltar às anotações</a><?php endif; ?><div class="page-heading"><div><span class="eyebrow">ANOTAÇÃO PRIVADA</span><h1><?= e($note['title']) ?></h1><p><?= e($note['subject_name'] ?? 'Sem matéria') ?> · <?= e(pretty_date($note['updated_at'])) ?></p></div><div class="heading-actions"><form method="post" action="<?= e(url('toggle-note-important')) ?>" class="note-important-form"><?= csrf() ?><input type="hidden" name="id" value="<?= (int) $note['id'] ?>"><input type="hidden" name="important" value="<?= (int) $note['important'] === 1 ? '0' : '1' ?>"><?php if (modal_request()): ?><input type="hidden" name="return" value="modal" data-return-path><?php endif; ?><button class="button button-primary note-edit-button note-important-button<?= (int) $note['important'] === 1 ? ' is-active' : '' ?>" type="submit" aria-pressed="<?= (int) $note['important'] === 1 ? 'true' : 'false' ?>" title="<?= (int) $note['important'] === 1 ? 'Remover dos importantes' : 'Marcar como importante' ?>"><?= icon('star') ?><span class="sr-only"><?= (int) $note['important'] === 1 ? 'Remover dos importantes' : 'Marcar como importante' ?></span></button></form><a class="button button-primary note-edit-button" href="<?= e(url('edit-note', ['id' => $note['id']])) ?>" title="Editar anotação"><?= icon('edit') ?><span class="sr-only">Editar anotação</span></a><form method="post" action="<?= e(url('delete-note')) ?>" class="note-delete-form"><?= csrf() ?><input type="hidden" name="id" value="<?= (int) $note['id'] ?>"><input type="hidden" name="revision" value="<?= (int) $note['revision'] ?>"><input type="hidden" name="confirm" value="1" disabled data-swal-enable><noscript><label class="confirmation-check"><input type="checkbox" name="confirm" value="1" required>Confirmo a exclusão desta anotação.</label></noscript><button class="button button-primary note-edit-button" type="submit" title="Excluir anotação" data-swal-confirm><?= icon('trash') ?><span class="sr-only">Excluir anotação</span></button></form><?php if (modal_request()): ?><button type="button" class="button button-primary note-edit-button" data-close title="Fechar"><?= icon('close') ?><span class="sr-only">Fechar</span></button><?php endif; ?></div></div><section class="form-card note-body"><?= e($note['body']) ?></section><?php render_note_files(note_files((int) $note['id']), (int) $note['id'], modal_request() ? 'modal' : ''); ?>
<?php detail_end();
}
