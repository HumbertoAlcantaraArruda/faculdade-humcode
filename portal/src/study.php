<?php
declare(strict_types=1);

function study_table(string $type): string {
    if (!in_array($type, ['file', 'video'], true)) { fail('Selecione um conteúdo válido.'); }
    return 'hc_portal_' . $type . '_study';
}

function study_content(string $type, int $id, bool $lock = false): array {
    study_table($type);
    $row = query('SELECT * FROM hc_portal_' . $type . 's WHERE id = ?' . ($type === 'file' ? ' AND deleted_at IS NULL' : '') . ($lock ? lock_suffix() : ''), [$id])->fetch();
    if (!$row) { if (db()->inTransaction()) { db()->rollBack(); } fail('Conteúdo não encontrado.', 404); }
    return $row;
}

function study_marked(string $type, int $id, int $user): bool {
    return (bool) query('SELECT id FROM ' . study_table($type) . ' WHERE user_id = ? AND ' . $type . '_id = ?', [$user, $id])->fetch();
}

function change_study_state(array $user): void {
    $type = $_POST['type'] ?? '';
    if (!is_string($type)) { fail('Selecione um conteúdo válido.'); }
    $table = study_table($type);
    $id = numeric_id($_POST['id'] ?? null);
    $state = $_POST['studied'] ?? '';
    if (!in_array($state, ['0', '1'], true)) { fail('Selecione uma marcação válida.'); }
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $content = study_content($type, $id, true);
        if (!is_string($_POST['content_revision'] ?? null) || (string) $content['revision'] !== $_POST['content_revision']) { db()->rollBack(); fail('Este conteúdo foi alterado. Reabra a página antes de marcar o estudo.', 409); }
        $marked = study_marked($type, $id, (int) $user['id']);
        if ($state === '1' && !$marked) { query('INSERT INTO ' . $table . ' (user_id, ' . $type . '_id) VALUES (?, ?)', [$user['id'], $id]); }
        elseif ($state === '0' && $marked) { query('DELETE FROM ' . $table . ' WHERE user_id = ? AND ' . $type . '_id = ?', [$user['id'], $id]); }
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($state === '1' ? ($type === 'file' ? 'Material marcado como estudado.' : 'Vídeo marcado como assistido.') : 'Marcação removida.');
    $destination = local_destination($_POST['return_to'] ?? null);
    if ($destination !== null) { header('Location: ' . $destination, true, 303); exit; }
    if ($type === 'video') { redirect_to_videos((int) $content['subject_id']); }
    redirect('view', ['id' => $id]);
}

function subject_study_progress(int $subject, int $user): array {
    $result = [];
    foreach (['file', 'video'] as $type) {
        $where = 'c.subject_id = ?' . ($type === 'file' ? ' AND c.deleted_at IS NULL' : '');
        $result[$type] = query('SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN m.id IS NULL THEN 0 ELSE 1 END), 0) AS done FROM hc_portal_' . $type . 's c LEFT JOIN ' . study_table($type) . ' m ON m.' . $type . '_id = c.id AND m.user_id = ? WHERE ' . $where, [$user, $subject])->fetch();
    }
    $result['all'] = ['total' => (int) $result['file']['total'] + (int) $result['video']['total'], 'done' => (int) $result['file']['done'] + (int) $result['video']['done']];
    return $result;
}

function render_study_form(string $type, array $content, string $returnTo): void {
    $done = study_marked($type, (int) $content['id'], (int) current_user()['id']);
    $label = $type === 'file' ? 'Estudado' : 'Assistido'; ?>
<form class="study-form" method="post" action="<?= e(url('study-state')) ?>"><?= csrf() ?><input type="hidden" name="type" value="<?= e($type) ?>"><input type="hidden" name="id" value="<?= (int) $content['id'] ?>"><input type="hidden" name="content_revision" value="<?= (int) $content['revision'] ?>"><input type="hidden" name="studied" value="<?= $done ? '0' : '1' ?>"><input type="hidden" name="return_to" value="<?= e($returnTo) ?>"><button class="button button-secondary study-toggle" role="checkbox" aria-checked="<?= $done ? 'true' : 'false' ?>" aria-label="<?= e(($done ? 'Desmarcar: ' : 'Marcar como ' . strtolower($label) . ': ') . $content['title']) ?>"><?= icon($done ? 'check' : 'square') ?><?= $done ? $label : 'Marcar como ' . strtolower($label) ?></button></form>
<?php }

function render_study_badge(array $content): void {
    if (study_marked('file', (int) $content['id'], (int) current_user()['id'])): ?><span class="study-badge"><?= icon('check') ?>Estudado</span><?php endif;
}

function render_study_progress(int $subject): void {
    $progress = subject_study_progress($subject, (int) current_user()['id']); ?>
<section class="study-progress" aria-labelledby="study-progress-heading"><h2 id="study-progress-heading">Meu progresso de estudo</h2><p class="form-hint">Marcações pessoais. Arquivos incluem Materiais, Trabalhos e Provas, em todas as pastas.</p><div class="study-progress-grid"><?php foreach (['file' => 'Arquivos', 'video' => 'Vídeos', 'all' => 'Total'] as $type => $label): $row = $progress[$type]; $total = (int) $row['total']; $done = (int) $row['done']; $percent = $total ? (int) round($done * 100 / $total) : 0; ?><div data-study-progress="<?= e($type) ?>" data-study-done="<?= $done ?>" data-study-total="<?= $total ?>"><strong><?= e($label) ?></strong><?php if ($total): ?><p><?= $done ?> de <?= $total ?> · <?= $percent ?>%</p><progress value="<?= $done ?>" max="<?= $total ?>" aria-label="<?= e($label . ': ' . $done . ' de ' . $total) ?>"></progress><?php else: ?><p>Sem conteúdo</p><?php endif; ?></div><?php endforeach; ?></div></section>
<?php }
