<?php
declare(strict_types=1);

function my_day_data(int $userId, ?DateTimeImmutable $now = null): array {
    // Capture the date once so every list uses the same Brasília day.
    $now = ($now ?? new DateTimeImmutable())->setTimezone(new DateTimeZone('America/Sao_Paulo'));
    $today = $now->format('Y-m-d');
    $tomorrow = $now->modify('+1 day')->format('Y-m-d');
    $last = $now->modify('+7 days')->format('Y-m-d');
    $eventSelect = "SELECT e.id, e.title, e.event_date, e.starts_at, e.ends_at, e.priority, e.category, e.recurrence_id, e.recurrence_exception, s.name AS subject_name, 'event' AS item_kind FROM hc_portal_events e LEFT JOIN hc_portal_subjects s ON s.id = e.subject_id";
    $taskSelect = "SELECT t.id, t.title, t.task_date AS event_date, t.starts_at, t.ends_at, t.priority, t.category, t.recurrence_id, t.recurrence_exception, s.name AS subject_name, 'task' AS item_kind FROM hc_portal_tasks t LEFT JOIN hc_portal_subjects s ON s.id = t.subject_id";
    $taskDetails = 'SELECT t.*, t.task_date AS event_date, s.name AS subject_name, e.title AS event_title FROM hc_portal_tasks t LEFT JOIN hc_portal_subjects s ON s.id = t.subject_id LEFT JOIN hc_portal_events e ON e.id = t.event_id AND e.user_id = t.user_id';
    $upcoming = $eventSelect . ' WHERE e.user_id = ? AND e.event_date BETWEEN ? AND ? UNION ALL ' . $taskSelect . ' WHERE t.user_id = ? AND t.completed_at IS NULL AND t.task_date BETWEEN ? AND ?';
    $definitions = [
        'eventos' => [$eventSelect . ' WHERE e.user_id = ? AND e.event_date = ?', 'SELECT COUNT(*) FROM hc_portal_events WHERE user_id = ? AND event_date = ?', [$userId, $today]],
        'tarefas' => [$taskDetails . ' WHERE t.user_id = ? AND t.task_date = ? AND t.completed_at IS NULL', 'SELECT COUNT(*) FROM hc_portal_tasks WHERE user_id = ? AND task_date = ? AND completed_at IS NULL', [$userId, $today]],
        'atrasadas' => [$taskDetails . ' WHERE t.user_id = ? AND t.task_date < ? AND t.completed_at IS NULL', 'SELECT COUNT(*) FROM hc_portal_tasks WHERE user_id = ? AND task_date < ? AND completed_at IS NULL', [$userId, $today]],
        'proximos' => ['SELECT * FROM (' . $upcoming . ') commitments', 'SELECT COUNT(*) FROM (' . $upcoming . ') commitments', [$userId, $tomorrow, $last, $userId, $tomorrow, $last]],
        'concluidas' => [$taskDetails . ' WHERE t.user_id = ? AND t.task_date = ? AND t.completed_at IS NOT NULL', 'SELECT COUNT(*) FROM hc_portal_tasks WHERE user_id = ? AND task_date = ? AND completed_at IS NOT NULL', [$userId, $today]],
    ];
    $groups = [];
    foreach ($definitions as $key => [$select, $count, $params]) {
        $total = (int) query($count, $params)->fetchColumn();
        $pages = max(1, (int) ceil($total / 10));
        $page = min($pages, max(1, numeric_id($_GET[$key] ?? 1)));
        $order = $key === 'eventos' ? 'e.event_date, e.starts_at, e.title, e.id' : ($key === 'proximos' ? 'event_date, starts_at, title, id, item_kind' : 't.task_date, t.starts_at, t.title, t.id');
        $items = query($select . ' ORDER BY ' . $order . ' LIMIT 10 OFFSET ' . (($page - 1) * 10), $params)->fetchAll();
        $groups[$key] = ['total' => $total, 'pages' => $pages, 'page' => $page, 'items' => $items];
    }
    return ['today' => $today, 'tomorrow' => $tomorrow, 'last' => $last, 'groups' => $groups];
}

function my_day_page_params(array $groups): array {
    $params = [];
    foreach ($groups as $key => $group) { if ($group['page'] > 1) { $params[$key] = $group['page']; } }
    return $params;
}

function render_my_day_pagination(string $key, array $groups, string $label): void {
    $group = $groups[$key];
    if ($group['pages'] <= 1) { return; }
    $params = my_day_page_params($groups); ?>
<nav class="my-day-pagination" aria-label="<?= e('Páginas de ' . $label) ?>">
<?php if ($group['page'] > 1): ?><a class="button button-secondary" href="<?= e(url('my-day', array_merge($params, [$key => $group['page'] - 1]))) ?>#<?= e($key) ?>">Anterior</a><?php endif; ?>
<span>Página <?= $group['page'] ?> de <?= $group['pages'] ?></span>
<?php if ($group['page'] < $group['pages']): ?><a class="button button-secondary" href="<?= e(url('my-day', array_merge($params, [$key => $group['page'] + 1]))) ?>#<?= e($key) ?>">Próxima</a><?php endif; ?>
</nav>
<?php }

function render_my_day_commitment(array $item): void {
    $isTask = $item['item_kind'] === 'task'; ?>
<article class="agenda-event-row" data-commitment-kind="<?= $isTask ? 'task' : 'event' ?>" data-commitment-id="<?= (int) $item['id'] ?>"><div><small class="muted"><?= $isTask ? 'Tarefa' : 'Evento' ?></small><a class="my-day-title" href="<?= e(url($isTask ? 'view-task' : 'view-event', ['id' => $item['id']])) ?>"><strong><?= e($item['title']) ?></strong></a><p><?= e(event_day_label($item['event_date'])) ?> · <?= e(event_time_label($item)) ?> · <?= e(event_category_label($item)) ?><?php if ($item['subject_name'] !== null): ?> · <?= e($item['subject_name']) ?><?php endif; ?></p></div><?= event_badge($item) ?></article>
<?php }

function render_my_day(array $user): void {
    $data = my_day_data((int) $user['id']);
    $groups = $data['groups'];
    $labels = ['eventos' => 'Eventos de hoje', 'tarefas' => 'Tarefas pendentes de hoje', 'atrasadas' => 'Tarefas atrasadas', 'proximos' => 'Próximos compromissos'];
    $empty = ['eventos' => 'Nenhum evento hoje. Consulte a agenda ou planeje um novo compromisso.', 'tarefas' => 'Nenhuma tarefa pendente hoje.', 'atrasadas' => 'Nenhuma tarefa atrasada.', 'proximos' => 'Nenhum evento ou tarefa pendente nos próximos sete dias.'];
    $returnTo = url('my-day', my_day_page_params($groups));
    page_start('Meu dia', 'my-day'); ?>
<div class="page-heading"><div><span class="eyebrow">SEU DIA, ORGANIZADO</span><h1>Meu dia</h1><p><?= e(event_day_label($data['today'])) ?> · Só você vê seus compromissos e pendências.</p></div><div class="heading-actions"><a class="button button-secondary" href="<?= e(url('agenda')) ?>"><?= icon('calendar') ?>Agenda completa</a><a class="button button-secondary" href="<?= e(url('new-task', ['dia' => $data['today']])) ?>"><?= icon('check') ?>Nova tarefa</a><a class="button button-primary" href="<?= e(url('new-event', ['dia' => $data['today']])) ?>"><?= icon('plus') ?>Novo evento</a></div></div>
<nav class="my-day-summary" aria-label="Resumo do meu dia"><?php foreach ($labels as $key => $label): ?><a href="#<?= $key ?>"><strong data-my-day-count="<?= $key ?>"><?= $groups[$key]['total'] ?></strong><span><?= e($label) ?></span></a><?php endforeach; ?></nav>
<p class="form-hint">Tarefas ficam atrasadas no dia seguinte à data marcada, com ou sem horário. Horários de Brasília.</p>
<div class="my-day-grid"><?php foreach ($labels as $key => $label): $group = $groups[$key]; ?>
<section class="my-day-section" id="<?= $key ?>" aria-labelledby="<?= $key ?>-heading"><h2 id="<?= $key ?>-heading"><?= e($label) ?></h2><?php if ($key === 'proximos'): ?><p class="muted"><?= e(event_day_label($data['tomorrow'])) ?> a <?= e(event_day_label($data['last'])) ?></p><?php endif; ?>
<?php if (!$group['total']): ?><div class="agenda-empty"><p><?= e($empty[$key]) ?></p></div><?php endif; ?>
<?php foreach ($group['items'] as $item): if ($key === 'tarefas' || $key === 'atrasadas') { render_task_row($item, $returnTo); } else { render_my_day_commitment($item); } endforeach; ?>
<?php render_my_day_pagination($key, $groups, $label); ?>
<?php if ($key === 'tarefas' && $groups['concluidas']['total']): ?><details class="my-day-completed" id="concluidas" <?= isset($_GET['concluidas']) ? 'open' : '' ?>><summary>Tarefas de hoje concluídas (<?= $groups['concluidas']['total'] ?>)</summary><?php foreach ($groups['concluidas']['items'] as $task): render_task_row($task, $returnTo); endforeach; render_my_day_pagination('concluidas', $groups, 'tarefas de hoje concluídas'); ?></details><?php endif; ?>
</section><?php endforeach; ?></div>
<?php page_end();
}
