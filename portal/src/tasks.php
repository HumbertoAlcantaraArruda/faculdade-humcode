<?php
declare(strict_types=1);

function task_record(int $id, int $userId, bool $lock = false): array {
    $sql = $lock ? 'SELECT t.*, t.task_date AS event_date FROM hc_portal_tasks t WHERE t.id = ? AND t.user_id = ?' . lock_suffix()
        : 'SELECT t.*, t.task_date AS event_date, e.title AS event_title, s.name AS subject_name FROM hc_portal_tasks t LEFT JOIN hc_portal_events e ON e.id = t.event_id AND e.user_id = t.user_id LEFT JOIN hc_portal_subjects s ON s.id = t.subject_id WHERE t.id = ? AND t.user_id = ?';
    $task = query($sql, [$id, $userId])->fetch();
    if (!$task) { if (db()->inTransaction()) { db()->rollBack(); } fail('Tarefa não encontrada.', 404); }
    return $task;
}
function check_task_revision(array $task): void {
    if (!is_string($_POST['revision'] ?? null) || (string) $task['revision'] !== $_POST['revision']) {
        db()->rollBack(); fail('Esta tarefa foi alterada. Reabra a página antes de continuar.', 409);
    }
}
function save_task(array $user, bool $update): void {
    $id = numeric_id($_POST['id'] ?? null);
    if ($update) { task_record($id, (int) $user['id']); }
    [$title, $description, $date, $priority, $start, $end, $subject, $category] = event_fields();
    $rule = recurrence_rule($date);
    $key = $rule ? recurrence_request_key() : null;
    $rawEvent = $_POST['event_id'] ?? '';
    $eventId = $rawEvent === '' ? null : numeric_id($rawEvent);
    if ($eventId !== null) { event_record($eventId, (int) $user['id']); }
    db()->beginTransaction();
    try {
        if ($subject !== null) { lock_material_subject($subject); }
        lock_event_user((int) $user['id']);
        $event = $eventId !== null ? event_record($eventId, (int) $user['id'], true) : null;
        if ($event && $event['recurrence_id'] !== null && $rule) { db()->rollBack(); fail('Esta tarefa acompanha a repetição do evento. Deixe Repetir como Não repetir.'); }
        if (!$update && $rule && ($replayed = recurrence_replayed((int) $user['id'], $key, 'task')) !== null) { db()->commit(); redirect('view-task', ['id' => $replayed]); }
        $notifyOn = $date >= date('Y-m-d') ? $date : null;
        if ($update) {
            $task = task_record($id, (int) $user['id'], true);
            check_task_revision($task);
            if ($rule && $task['recurrence_id'] !== null) { db()->rollBack(); fail('A regra desta repetição permanece a cadastrada. Escolha o alcance para editar os compromissos.'); }
            update_recurrence_items('task', $task, [$title, $description, $date, $priority, $start, $end, $subject, $category], $eventId);
        } else {
            query('INSERT INTO hc_portal_tasks (user_id, title, description, task_date, priority, starts_at, ends_at, subject_id, category, event_id, notify_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$user['id'], $title, $description, $date, $priority, $start, $end, $subject, $category, $eventId, $notifyOn]);
            $id = (int) db()->lastInsertId();
        }
        $saved = task_record($id, (int) $user['id'], true);
        if ($rule) { create_recurrence('task', $saved, $rule, $key); }
        elseif ($event && $event['recurrence_id'] !== null && $saved['recurrence_id'] === null) { repeat_task_with_event($saved, $event); }
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($update ? 'Tarefa atualizada.' : 'Tarefa criada.');
    redirect('view-task', ['id' => $id]);
}
function change_task_state(array $user, bool $delete): void {
    $id = numeric_id($_POST['id'] ?? null);
    task_record($id, (int) $user['id']);
    if ($delete && ($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão da tarefa.'); }
    $complete = $_POST['complete'] ?? '';
    if (!$delete && !in_array($complete, ['0', '1'], true)) { fail('Selecione um estado válido.'); }
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $task = task_record($id, (int) $user['id'], true);
        check_task_revision($task);
        if ($delete) {
            foreach (recurrence_targets('task', $task, recurrence_scope($task)) as $target) { query('DELETE FROM hc_portal_tasks WHERE id = ? AND user_id = ?', [$target['id'], $user['id']]); }
        }
        else {
            query('UPDATE hc_portal_tasks SET completed_at = ' . ($complete === '1' ? 'COALESCE(completed_at, CURRENT_TIMESTAMP)' : 'NULL') . ', revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?', [$id, $user['id']]);
            if ($complete === '1') { query('UPDATE hc_portal_task_notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE task_id = ?', [$id]); }
        }
        touch_recurrence($task);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($delete ? 'Tarefa excluída.' : ($complete === '1' ? 'Tarefa concluída.' : 'Tarefa reaberta.'));
    if (!$delete) {
        $return = local_destination($_POST['return_to'] ?? null);
        if ($return !== null) { header('Location: ' . $return, true, 303); exit; }
        redirect('view-task', ['id' => $id]);
    }
    redirect('agenda', ['mes' => substr($task['task_date'], 0, 7), 'dia' => $task['task_date']]);
}
function task_list(int $userId, ?int $eventId = null, ?string $begin = null, ?string $end = null): array {
    $where = 't.user_id = ?'; $params = [$userId];
    if ($eventId !== null) { $where .= ' AND t.event_id = ?'; $params[] = $eventId; }
    if ($begin !== null && $end !== null) { $where .= ' AND t.task_date BETWEEN ? AND ?'; $params[] = $begin; $params[] = $end; }
    return query('SELECT t.*, t.task_date AS event_date, s.name AS subject_name, e.title AS event_title FROM hc_portal_tasks t LEFT JOIN hc_portal_subjects s ON s.id = t.subject_id LEFT JOIN hc_portal_events e ON e.id = t.event_id AND e.user_id = t.user_id WHERE ' . $where . ' ORDER BY CASE WHEN t.completed_at IS NULL THEN 0 ELSE 1 END, t.task_date, t.starts_at, t.id', $params)->fetchAll();
}
function read_task_notification(array $user): void {
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $notice = query('SELECT n.id FROM hc_portal_task_notifications n JOIN hc_portal_tasks t ON t.id = n.task_id WHERE n.id = ? AND t.user_id = ?', [numeric_id($_POST['id'] ?? null), $user['id']])->fetch();
        if (!$notice) { db()->rollBack(); fail('Notificação não encontrada.', 404); }
        query('UPDATE hc_portal_task_notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ?', [$notice['id']]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    redirect('notifications');
}
