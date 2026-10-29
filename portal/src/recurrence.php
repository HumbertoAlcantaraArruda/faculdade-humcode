<?php
declare(strict_types=1);

function recurrence_rule(string $date): ?array {
    $frequency = $_POST['recurrence'] ?? 'none';
    if ($frequency === 'none') { return null; }
    if (!in_array($frequency, ['weekly', 'monthly'], true)) { fail('Selecione uma repetição válida.'); }
    $interval = $_POST['recurrence_interval'] ?? '';
    $count = $_POST['recurrence_count'] ?? '';
    if (!is_string($interval) || !ctype_digit($interval) || (int) $interval < 1 || (int) $interval > ($frequency === 'weekly' ? 52 : 12)) { fail('Informe um intervalo válido de repetição.'); }
    if (!is_string($count) || !ctype_digit($count) || (int) $count < 2 || (int) $count > 120) { fail('Informe de 2 a 120 ocorrências, incluindo a primeira.'); }
    $weekdays = [];
    if ($frequency === 'weekly') {
        $days = $_POST['recurrence_days'] ?? [];
        if (!is_array($days) || !$days || count($days) > 7) { fail('Selecione os dias da semana.'); }
        foreach ($days as $day) {
            if (!is_string($day) || !preg_match('/^[0-6]$/D', $day) || in_array((int) $day, $weekdays, true)) { fail('Selecione dias da semana válidos, sem repetição.'); }
            $weekdays[] = (int) $day;
        }
        sort($weekdays);
        if (!in_array((int) (new DateTimeImmutable($date))->format('w'), $weekdays, true)) { fail('Inclua o dia da primeira ocorrência nos dias da semana.'); }
    }
    $rule = ['frequency' => $frequency, 'interval_count' => (int) $interval, 'occurrence_count' => (int) $count, 'weekdays' => implode(',', $weekdays), 'anchor_date' => $date];
    recurrence_dates($rule);
    return $rule;
}

function recurrence_dates(array $rule): array {
    $anchor = new DateTimeImmutable($rule['anchor_date']);
    $dates = [];
    if ($rule['frequency'] === 'monthly') {
        $first = $anchor->modify('first day of this month');
        for ($i = 0; $i < (int) $rule['occurrence_count']; $i++) {
            $month = $first->modify('+' . ($i * (int) $rule['interval_count']) . ' months');
            $day = min((int) $anchor->format('j'), (int) $month->format('t'));
            $date = $month->setDate((int) $month->format('Y'), (int) $month->format('n'), $day);
            if ((int) $date->format('Y') > 9999) { fail('A repetição ultrapassa o ano 9999.'); }
            $dates[] = $date->format('Y-m-d');
        }
    } else {
        $days = array_map('intval', explode(',', $rule['weekdays']));
        $week = $anchor->modify('-' . $anchor->format('w') . ' days');
        for ($n = 0; count($dates) < (int) $rule['occurrence_count']; $n++) {
            foreach ($days as $day) {
                $date = $week->modify('+' . ($n * 7 * (int) $rule['interval_count'] + $day) . ' days');
                if ($date < $anchor) { continue; }
                if ((int) $date->format('Y') > 9999) { fail('A repetição ultrapassa o ano 9999.'); }
                $dates[] = $date->format('Y-m-d');
                if (count($dates) === (int) $rule['occurrence_count']) { break; }
            }
        }
    }
    return $dates;
}

function recurrence_record(int $id, int $owner): array {
    $series = query('SELECT * FROM hc_portal_recurrences WHERE id = ? AND user_id = ?', [$id, $owner])->fetch();
    if (!$series) { if (db()->inTransaction()) { db()->rollBack(); } fail('Repetição não encontrada.', 404); }
    return $series;
}

function recurrence_scope(array $item): string {
    $scope = $_POST['recurrence_scope'] ?? 'this';
    if (!in_array($scope, ['this', 'following', 'all'], true)) { fail('Selecione o alcance da alteração.'); }
    if ($item['recurrence_id'] === null && $scope !== 'this') { fail('Este compromisso não faz parte de uma repetição.'); }
    if ($item['recurrence_id'] !== null && $scope !== 'this') {
        $series = recurrence_record((int) $item['recurrence_id'], (int) $item['user_id']);
        if (!is_string($_POST['recurrence_revision'] ?? null) || (string) $series['revision'] !== $_POST['recurrence_revision']) { db()->rollBack(); fail('Esta repetição foi alterada. Reabra a página antes de continuar.', 409); }
    }
    return $scope;
}

function recurrence_targets(string $kind, array $item, string $scope): array {
    if ($scope === 'this') { return [$item]; }
    $table = $kind === 'event' ? 'hc_portal_events' : 'hc_portal_tasks';
    $dateColumn = $kind === 'event' ? 'event_date' : 'task_date';
    $where = 'recurrence_id = ? AND user_id = ? AND ' . $dateColumn . ' >= ? AND (recurrence_exception = 0 OR id = ?)';
    $params = [$item['recurrence_id'], $item['user_id'], date('Y-m-d'), $item['id']];
    if ($kind === 'task') { $where .= ' AND recurrence_slot = ? AND completed_at IS NULL'; $params[] = $item['recurrence_slot']; }
    if ($scope === 'following') { $where .= ' AND occurrence_date >= ?'; $params[] = $item['occurrence_date']; }
    $targets = query('SELECT * FROM ' . $table . ' WHERE ' . $where . ' ORDER BY id' . lock_suffix(), $params)->fetchAll();
    if (!$targets) { db()->rollBack(); fail('Nenhuma ocorrência disponível neste alcance. Ocorrências passadas, exceções e tarefas concluídas são preservadas.'); }
    return $targets;
}

function touch_recurrence(array $item): void {
    if ($item['recurrence_id'] !== null) { query('UPDATE hc_portal_recurrences SET revision = revision + 1 WHERE id = ? AND user_id = ?', [$item['recurrence_id'], $item['user_id']]); }
}

function recurrence_request_key(): string {
    $key = $_POST['recurrence_key'] ?? '';
    if (!is_string($key) || !preg_match('/^[a-f0-9]{32}$/D', $key)) { fail('Reabra o formulário antes de criar a repetição.'); }
    return $key;
}

function recurrence_replayed(int $owner, string $key, string $kind): ?int {
    $series = query('SELECT id, item_kind FROM hc_portal_recurrences WHERE user_id = ? AND request_key = ?', [$owner, $key])->fetch();
    if (!$series) { return null; }
    if ($series['item_kind'] !== $kind) { db()->rollBack(); fail('Este formulário já foi utilizado. Reabra o cadastro.', 409); }
    $table = $kind === 'event' ? 'hc_portal_events' : 'hc_portal_tasks';
    $id = query('SELECT i.id FROM ' . $table . ' i JOIN hc_portal_recurrences r ON r.id = i.recurrence_id AND r.user_id = i.user_id WHERE r.user_id = ? AND r.request_key = ? AND r.item_kind = ? ORDER BY i.occurrence_date, i.id LIMIT 1', [$owner, $key, $kind])->fetchColumn();
    if ($id === false) { db()->rollBack(); fail('A repetição criada por este formulário já foi excluída. Reabra o cadastro.', 409); }
    return (int) $id;
}

function create_recurrence(string $kind, array $item, array $rule, string $key): void {
    query('INSERT INTO hc_portal_recurrences (user_id, item_kind, frequency, interval_count, occurrence_count, weekdays, anchor_date, request_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [$item['user_id'], $kind, $rule['frequency'], $rule['interval_count'], $rule['occurrence_count'], $rule['weekdays'], $rule['anchor_date'], $key]);
    $seriesId = (int) db()->lastInsertId();
    $table = $kind === 'event' ? 'hc_portal_events' : 'hc_portal_tasks';
    $dateColumn = $kind === 'event' ? 'event_date' : 'task_date';
    $dates = recurrence_dates($rule);
    query('UPDATE ' . $table . ' SET recurrence_id = ?, occurrence_date = ? WHERE id = ? AND user_id = ?', [$seriesId, $dates[0], $item['id'], $item['user_id']]);
    if ($kind === 'event') {
        $tasks = query('SELECT * FROM hc_portal_tasks WHERE event_id = ? AND user_id = ? ORDER BY id', [$item['id'], $item['user_id']])->fetchAll();
        foreach ($tasks as $i => &$task) {
            if ($task['recurrence_id'] !== null) { fail('Uma tarefa deste evento já tem repetição própria. Remova seu vínculo antes de repetir o evento.'); }
            $task['recurrence_slot'] = $i + 1;
            query('UPDATE hc_portal_tasks SET recurrence_id = ?, occurrence_date = ?, recurrence_slot = ?, revision = revision + 1 WHERE id = ?', [$seriesId, $dates[0], $i + 1, $task['id']]);
        }
        unset($task);
    }
    foreach (array_slice($dates, 1) as $date) {
        $copy = $item;
        $copy[$dateColumn] = $date;
        $copy['recurrence_id'] = $seriesId; $copy['occurrence_date'] = $date; $copy['recurrence_slot'] = 0;
        $id = insert_recurrence_item($kind, $copy);
        if ($kind === 'event') {
            foreach ($tasks as $task) {
                $task['task_date'] = shift_recurrence_date($task['task_date'], $item['event_date'], $date);
                $task['event_id'] = $id; $task['recurrence_id'] = $seriesId; $task['occurrence_date'] = $date;
                insert_recurrence_item('task', $task);
            }
        }
    }
}

function shift_recurrence_date(string $date, string $from, string $to): string {
    $utc = new DateTimeZone('UTC');
    $delta = (new DateTimeImmutable($from, $utc))->diff(new DateTimeImmutable($to, $utc))->format('%r%a');
    $result = (new DateTimeImmutable($date))->modify($delta . ' days')->format('Y-m-d');
    return event_date($result);
}

function insert_recurrence_item(string $kind, array $item): int {
    $table = $kind === 'event' ? 'hc_portal_events' : 'hc_portal_tasks';
    $dateColumn = $kind === 'event' ? 'event_date' : 'task_date';
    $columns = ['user_id', 'subject_id', 'title', 'description', $dateColumn, 'starts_at', 'ends_at', 'priority', 'category', 'recurrence_id', 'occurrence_date'];
    if ($kind === 'task') { $columns[] = 'event_id'; $columns[] = 'recurrence_slot'; }
    $values = []; foreach ($columns as $column) { $values[] = $item[$column]; }
    $columns[] = 'notify_on'; $values[] = $item[$dateColumn] >= date('Y-m-d') ? $item[$dateColumn] : null;
    query('INSERT INTO ' . $table . ' (' . implode(', ', $columns) . ') VALUES (' . implode(', ', array_fill(0, count($columns), '?')) . ')', $values);
    $id = (int) db()->lastInsertId();
    copy_commitment_content($kind, (int) $item['id'], $id, (int) $item['user_id']);
    return $id;
}

function repeat_task_with_event(array $task, array $event): void {
    $seriesId = (int) $event['recurrence_id'];
    $slot = 1 + (int) query('SELECT COALESCE(MAX(recurrence_slot), 0) FROM hc_portal_tasks WHERE recurrence_id = ? AND user_id = ?', [$seriesId, $task['user_id']])->fetchColumn();
    query('UPDATE hc_portal_tasks SET recurrence_id = ?, occurrence_date = ?, recurrence_slot = ? WHERE id = ?', [$seriesId, $event['occurrence_date'], $slot, $task['id']]);
    $events = query('SELECT * FROM hc_portal_events WHERE recurrence_id = ? AND user_id = ? AND id <> ? AND event_date >= ? AND recurrence_exception = 0 ORDER BY id', [$seriesId, $task['user_id'], $event['id'], date('Y-m-d')])->fetchAll();
    foreach ($events as $copyEvent) {
        $copy = $task;
        $copy['task_date'] = shift_recurrence_date($task['task_date'], $event['event_date'], $copyEvent['event_date']);
        $copy['recurrence_id'] = $seriesId; $copy['occurrence_date'] = $copyEvent['occurrence_date']; $copy['recurrence_slot'] = $slot; $copy['event_id'] = $copyEvent['id'];
        insert_recurrence_item('task', $copy);
    }
    touch_recurrence($event);
}

function update_recurrence_items(string $kind, array $item, array $fields, ?int $eventId = null): int {
    [$title, $description, $date, $priority, $start, $end, $subject, $category] = $fields;
    $scope = recurrence_scope($item);
    if ($kind === 'task' && $scope !== 'this' && $eventId !== ($item['event_id'] === null ? null : (int) $item['event_id'])) { db()->rollBack(); fail('Para trocar o evento relacionado, altere somente esta ocorrência.'); }
    $targets = recurrence_targets($kind, $item, $scope);
    $table = $kind === 'event' ? 'hc_portal_events' : 'hc_portal_tasks';
    $notices = $kind === 'event' ? 'hc_portal_event_notifications' : 'hc_portal_task_notifications';
    $dateColumn = $kind === 'event' ? 'event_date' : 'task_date';
    foreach ($targets as $target) {
        $newDate = shift_recurrence_date($target[$dateColumn], $item[$dateColumn], $date);
        $notifyOn = $target['notify_on'];
        if ($newDate !== $target[$dateColumn]) { query('DELETE FROM ' . $notices . ' WHERE ' . $kind . '_id = ?', [$target['id']]); $notifyOn = $newDate >= date('Y-m-d') ? $newDate : null; }
        $exception = $item['recurrence_id'] !== null && $scope === 'this' ? 1 : $target['recurrence_exception'];
        $sql = 'UPDATE ' . $table . ' SET title = ?, description = ?, ' . $dateColumn . ' = ?, priority = ?, starts_at = ?, ends_at = ?, subject_id = ?, category = ?, notify_on = ?, recurrence_exception = ?, revision = revision + 1, updated_at = CURRENT_TIMESTAMP';
        $params = [$title, $description, $newDate, $priority, $start, $end, $subject, $category, $notifyOn, $exception];
        if ($kind === 'task') { $sql .= ', event_id = ?'; $params[] = $scope === 'this' ? $eventId : $target['event_id']; }
        $sql .= ' WHERE id = ? AND user_id = ?'; $params[] = $target['id']; $params[] = $item['user_id'];
        query($sql, $params);
        if ($kind === 'event') { cancel_event_invitations((int) $target['id']); }
    }
    touch_recurrence($item);
    return count($targets);
}

function render_recurrence_fields(?array $item, string $date, string $kind = 'event'): void {
    if ($item && $item['recurrence_id'] !== null) {
        $series = recurrence_record((int) $item['recurrence_id'], (int) $item['user_id']); ?>
<fieldset class="recurrence-fields"><legend>Repetição</legend><p><?= e(($series['frequency'] === 'weekly' ? 'Semanal' : 'Mensal') . ' · Intervalo: ' . $series['interval_count'] . ' · ' . $series['occurrence_count'] . ' ocorrências') ?></p><input type="hidden" name="recurrence_revision" value="<?= (int) $series['revision'] ?>"><label>Aplicar alteração a<select name="recurrence_scope"><option value="this">Somente esta ocorrência</option><option value="following">Esta e as próximas</option><option value="all">Série inteira</option></select></label><p class="form-hint">Em alterações de várias ocorrências, as passadas, as exceções individuais e as tarefas concluídas são preservadas. A quantidade e a regra de repetição permanecem as cadastradas.</p></fieldset>
<?php return; } ?>
<fieldset class="recurrence-fields" data-recurrence-fields><legend>Repetição</legend><input type="hidden" name="recurrence_key" value="<?= e(bin2hex(random_bytes(16))) ?>"><label><?= $kind === 'task' ? 'Repetição própria' : 'Repetir' ?><select name="recurrence" data-recurrence-select><option value="none">Não repetir</option><option value="weekly">Semanalmente</option><option value="monthly">Mensalmente</option></select></label><div data-recurrence-options><div class="event-form-grid"><label>Intervalo de semanas ou meses<input type="number" name="recurrence_interval" min="1" max="52" value="1"></label><label>Quantidade de ocorrências<input type="number" name="recurrence_count" min="2" max="120" value="2"></label></div><div class="recurrence-weekdays" data-recurrence-weekdays><span>Dias da semana</span><?php foreach (['Domingo','Segunda-feira','Terça-feira','Quarta-feira','Quinta-feira','Sexta-feira','Sábado'] as $day => $label): ?><label><input type="checkbox" name="recurrence_days[]" value="<?= $day ?>" <?= $day === (int) (new DateTimeImmutable($date))->format('w') ? 'checked' : '' ?>><?= e($label) ?></label><?php endforeach; ?></div><p class="form-hint">De 2 a 120 ocorrências, incluindo a primeira. Intervalo semanal: 1 a 52 semanas; mensal: 1 a 12 meses. Se o dia não existir no mês, será usado o último dia. Ao repetir um evento, suas tarefas também se repetem, com datas relativas e cada nova tarefa pendente.</p></div></fieldset>
<?php }

function render_recurrence_delete_scope(array $item): void {
    if ($item['recurrence_id'] === null) { return; }
    $series = recurrence_record((int) $item['recurrence_id'], (int) $item['user_id']); ?>
<input type="hidden" name="recurrence_revision" value="<?= (int) $series['revision'] ?>"><label>Excluir<select name="recurrence_scope"><option value="this">Somente esta ocorrência</option><option value="following">Esta e as próximas</option><option value="all">Série inteira</option></select></label><p class="form-hint">Excluir várias ocorrências preserva as passadas, as exceções individuais e as tarefas concluídas.</p>
<?php }

function recurrence_badge(array $item): string {
    return !empty($item['recurrence_id']) ? '<span class="recurrence-badge">' . icon('clock') . 'Recorrente' . (!empty($item['recurrence_exception']) ? ' · Exceção' : '') . '</span>' : '';
}
