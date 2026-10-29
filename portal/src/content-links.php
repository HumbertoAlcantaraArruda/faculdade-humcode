<?php
declare(strict_types=1);

function commitment_record(string $kind, int $id, int $owner, bool $lock = false): array {
    if ($kind === 'event') { return event_record($id, $owner, $lock); }
    if ($kind === 'task') { return task_record($id, $owner, $lock); }
    fail('Selecione um compromisso válido.');
}

function content_types(): array {
    return ['file' => 'Arquivo', 'video' => 'Vídeo', 'folder' => 'Pasta'];
}

function content_link_table(string $kind, string $type): string {
    if (!in_array($kind, ['event', 'task'], true) || !isset(content_types()[$type])) { fail('Selecione um vínculo válido.'); }
    return 'hc_portal_' . $kind . '_' . $type . 's';
}

function commitment_content(string $kind, int $id, int $owner): array {
    commitment_record($kind, $id, $owner);
    $rows = [];
    foreach (content_types() as $type => $label) {
        $title = $type === 'folder' ? 'c.name' : 'c.title';
        $active = $type === 'file' ? ' AND c.deleted_at IS NULL' : '';
        $extra = $type === 'video' ? ', c.youtube_id' : '';
        $table = content_link_table($kind, $type);
        foreach (query('SELECT c.id, ' . $title . ' AS title, c.subject_id, s.name AS subject_name' . $extra . ' FROM ' . $table . ' l JOIN hc_portal_' . $type . 's c ON c.id = l.' . $type . '_id LEFT JOIN hc_portal_subjects s ON s.id = c.subject_id WHERE l.' . $kind . '_id = ?' . $active . ' ORDER BY ' . $title . ', c.id', [$id])->fetchAll() as $row) {
            $row['type'] = $type; $row['type_label'] = $label;
            $rows[] = $row;
        }
    }
    return $rows;
}

function copy_commitment_content(string $kind, int $from, int $to, int $owner): void {
    commitment_record($kind, $to, $owner);
    foreach (commitment_content($kind, $from, $owner) as $row) {
        $table = content_link_table($kind, $row['type']);
        query('INSERT INTO ' . $table . ' (' . $kind . '_id, ' . $row['type'] . '_id) VALUES (?, ?)', [$to, $row['id']]);
    }
}

function commitment_content_url(array $row): string {
    if ($row['type'] === 'video') { return subject_url((int) $row['subject_id']) . '#videos'; }
    return url($row['type'] === 'folder' ? 'folder' : 'view', ['id' => $row['id']]);
}

function change_content_link(array $user): void {
    $kind = $_POST['kind'] ?? '';
    $type = $_POST['type'] ?? '';
    if (!is_string($kind) || !is_string($type)) { fail('Selecione um vínculo válido.'); }
    $table = content_link_table($kind, $type);
    $id = numeric_id($_POST['id'] ?? null);
    $content = numeric_id($_POST['content_id'] ?? null);
    $action = $_POST['action'] ?? '';
    if (!in_array($action, ['add', 'remove'], true)) { fail('Selecione uma operação válida.'); }
    commitment_record($kind, $id, (int) $user['id']);
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $item = commitment_record($kind, $id, (int) $user['id'], true);
        if (!is_string($_POST['revision'] ?? null) || (string) $item['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Este compromisso foi alterado. Reabra a página antes de continuar.', 409); }
        $scope = recurrence_scope($item);
        $targets = recurrence_targets($kind, $item, $scope);
        if ($action === 'add') {
            $active = $type === 'file' ? ' AND deleted_at IS NULL' : '';
            if (!query('SELECT id FROM hc_portal_' . $type . 's WHERE id = ?' . $active . lock_suffix(), [$content])->fetch()) { db()->rollBack(); fail('Conteúdo não encontrado.', 404); }
        }
        foreach ($targets as $target) {
            $exists = query('SELECT id FROM ' . $table . ' WHERE ' . $kind . '_id = ? AND ' . $type . '_id = ?', [$target['id'], $content])->fetch();
            if ($action === 'add' && !$exists) { query('INSERT INTO ' . $table . ' (' . $kind . '_id, ' . $type . '_id) VALUES (?, ?)', [$target['id'], $content]); }
            elseif ($action === 'remove' && $exists) { query('DELETE FROM ' . $table . ' WHERE id = ?', [$exists['id']]); }
            else { continue; }
            $exception = $item['recurrence_id'] !== null && $scope === 'this' ? 1 : $target['recurrence_exception'];
            query('UPDATE hc_portal_' . $kind . 's SET revision = revision + 1, recurrence_exception = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?', [$exception, $target['id'], $user['id']]);
        }
        touch_recurrence($item);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($action === 'add' ? 'Conteúdo vinculado.' : 'Vínculo removido.');
    redirect('commitment-content', ['kind' => $kind, 'item_id' => $id, 'type' => $type]);
}

function render_content_scope(array $item): void {
    if ($item['recurrence_id'] === null) { return; }
    $series = recurrence_record((int) $item['recurrence_id'], (int) $item['user_id']); ?>
<input type="hidden" name="recurrence_revision" value="<?= (int) $series['revision'] ?>"><label>Aplicar vínculo a<select name="recurrence_scope"><option value="this">Somente esta ocorrência</option><option value="following">Esta e as próximas</option><option value="all">Série inteira</option></select></label><p class="form-hint">Alterações em várias ocorrências preservam as passadas, as exceções e as tarefas concluídas.</p>
<?php }

function render_content_link_fields(string $kind, array $item, string $type, string $action): void { ?>
<?= csrf() ?><input type="hidden" name="kind" value="<?= e($kind) ?>"><input type="hidden" name="id" value="<?= (int) $item['id'] ?>"><input type="hidden" name="revision" value="<?= (int) $item['revision'] ?>"><input type="hidden" name="type" value="<?= e($type) ?>"><input type="hidden" name="action" value="<?= e($action) ?>">
<?php render_content_scope($item); }

function render_content_rows(array $rows, ?string $kind = null, ?array $item = null): void {
    if (!$rows): ?><p class="muted">Nenhum conteúdo vinculado.</p><?php endif;
    foreach ($rows as $row): ?>
<article class="content-link-row"><div><a href="<?= e(commitment_content_url($row)) ?>"><strong><?= e($row['title']) ?></strong></a><p class="muted"><?= e($row['type_label'] . ' · ' . ($row['subject_name'] ?? 'Sem matéria')) ?></p></div><?php if ($item !== null): ?><form method="post" action="<?= e(url('change-content-link')) ?>"><?php render_content_link_fields($kind, $item, $row['type'], 'remove'); ?><input type="hidden" name="content_id" value="<?= (int) $row['id'] ?>"><button class="button button-secondary" type="submit" aria-label="<?= e('Remover vínculo: ' . $row['title']) ?>">Remover vínculo</button></form><?php endif; ?></article>
<?php endforeach;
}

function render_content_section(string $kind, array $item): void {
    $owner = (int) current_user()['id']; ?>
<section class="form-card content-links" aria-labelledby="content-links-heading"><div class="calendar-toolbar"><h2 id="content-links-heading">Conteúdos vinculados</h2><a class="button button-secondary" href="<?= e(url('commitment-content', ['kind' => $kind, 'item_id' => $item['id']])) ?>"><?= icon('plus') ?>Gerenciar vínculos</a></div><?php render_content_rows(commitment_content($kind, (int) $item['id'], $owner)); ?><?php if ($kind === 'task' && $item['event_id'] !== null): ?><h3>Conteúdos do evento</h3><p class="form-hint">Gerencie estes vínculos pelo evento relacionado.</p><?php render_content_rows(commitment_content('event', (int) $item['event_id'], $owner)); ?><?php endif; ?></section>
<?php }

function render_commitment_content(string $kind, array $item): void {
    $type = $_GET['type'] ?? 'file'; $search = $_GET['q'] ?? '';
    if (!is_string($type) || !isset(content_types()[$type]) || !is_string($search) || strlen($search) > 400 || !preg_match('//u', $search)) { fail('Informe uma busca válida.'); }
    $search = trim($search);
    $title = $type === 'folder' ? 'c.name' : 'c.title';
    $where = $type === 'file' ? 'c.deleted_at IS NULL' : '1 = 1'; $params = [];
    if ($search !== '') { $where .= ' AND (' . $title . ' LIKE ? OR s.name LIKE ?)'; $params = ['%' . $search . '%', '%' . $search . '%']; }
    $from = ' FROM hc_portal_' . $type . 's c LEFT JOIN hc_portal_subjects s ON s.id = c.subject_id WHERE ' . $where;
    $total = (int) query('SELECT COUNT(*)' . $from, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / 20)); $page = min($pages, max(1, numeric_id($_GET['pagina'] ?? 1)));
    $choices = query('SELECT c.id, ' . $title . ' AS title, s.name AS subject_name' . $from . ' ORDER BY ' . $title . ', c.id LIMIT 20 OFFSET ' . (($page - 1) * 20), $params)->fetchAll();
    page_start('Vincular conteúdos', 'agenda'); ?>
<a class="back-link" href="<?= e(url('view-' . $kind, ['id' => $item['id']])) ?>"><?= icon('back') ?>Voltar ao compromisso</a><div class="page-heading"><div><h1>Vincular conteúdos</h1><p><?= e($item['title']) ?></p></div></div>
<section class="form-card content-links"><h2>Adicionar conteúdo</h2><form method="get" action="<?= e(url('commitment-content')) ?>"><input type="hidden" name="kind" value="<?= e($kind) ?>"><input type="hidden" name="item_id" value="<?= (int) $item['id'] ?>"><label>Tipo de conteúdo<select name="type"><?php foreach (content_types() as $key => $label): ?><option value="<?= e($key) ?>" <?= $type === $key ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select></label><label>Buscar conteúdo ou matéria<input name="q" value="<?= e($search) ?>" maxlength="100"></label><button class="button button-secondary" type="submit">Buscar conteúdo</button></form>
<?php if ($choices): ?><form class="content-add-form" method="post" action="<?= e(url('change-content-link')) ?>"><?php render_content_link_fields($kind, $item, $type, 'add'); ?><label>Conteúdo<select name="content_id" required><?php foreach ($choices as $choice): ?><option value="<?= (int) $choice['id'] ?>"><?= e($choice['title'] . ' · ' . ($choice['subject_name'] ?? 'Sem matéria')) ?></option><?php endforeach; ?></select></label><button class="button button-primary" type="submit"><?= icon('plus') ?>Vincular conteúdo</button></form><?php else: ?><p class="muted">Nenhum conteúdo encontrado.</p><?php endif; ?>
<?php if ($pages > 1): ?><nav class="calendar-toolbar" aria-label="Paginação de conteúdos"><?php if ($page > 1): ?><a href="<?= e(url('commitment-content', ['kind' => $kind, 'item_id' => $item['id'], 'type' => $type, 'q' => $search, 'pagina' => $page - 1])) ?>">Anterior</a><?php endif; ?><span>Página <?= $page ?> de <?= $pages ?></span><?php if ($page < $pages): ?><a href="<?= e(url('commitment-content', ['kind' => $kind, 'item_id' => $item['id'], 'type' => $type, 'q' => $search, 'pagina' => $page + 1])) ?>">Próxima</a><?php endif; ?></nav><?php endif; ?></section>
<section class="form-card content-links"><h2>Vínculos próprios</h2><?php render_content_rows(commitment_content($kind, (int) $item['id'], (int) current_user()['id']), $kind, $item); ?></section>
<?php page_end();
}
