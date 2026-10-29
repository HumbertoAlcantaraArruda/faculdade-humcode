<?php
declare(strict_types=1);

function event_date($value): string {
    if (!is_string($value) || !preg_match('/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}$/D', $value)) { fail('Informe uma data válida.'); }
    $date = DateTimeImmutable::createFromFormat('!Y-m-d', $value);
    if (!$date || $date->format('Y-m-d') !== $value) { fail('Informe uma data válida.'); }
    return $value;
}
function event_priorities(): array { return ['baixa' => 'Baixa', 'media' => 'Média', 'urgente' => 'Urgente']; }
function event_categories(): array {
    return ['faculdade' => 'Faculdade', 'curso' => 'Curso', 'certificacao' => 'Certificação', 'concurso' => 'Concurso', 'estudo_independente' => 'Estudo independente', 'pesquisa' => 'Pesquisa', 'evento_academico' => 'Evento acadêmico'];
}
function event_category_label(array $event): string { return event_categories()[$event['category'] ?? ''] ?? 'Sem categoria'; }
function event_record(int $id, int $userId, bool $lock = false): array {
    $event = query($lock ? 'SELECT * FROM hc_portal_events WHERE id = ? AND user_id = ?' . lock_suffix() : 'SELECT e.*, s.name AS subject_name FROM hc_portal_events e LEFT JOIN hc_portal_subjects s ON s.id = e.subject_id WHERE e.id = ? AND e.user_id = ?', [$id, $userId])->fetch();
    if (!$event) { if (db()->inTransaction()) { db()->rollBack(); } fail('Evento não encontrado.', 404); }
    return $event;
}
function event_fields(): array {
    $title = field('title', 180);
    $description = field('description', 5000, false);
    $date = event_date($_POST['event_date'] ?? null);
    $priority = $_POST['priority'] ?? '';
    if (!is_string($priority) || !isset(event_priorities()[$priority])) { fail('Selecione uma prioridade válida.'); }
    $category = $_POST['category'] ?? '';
    if (!is_string($category) || !isset(event_categories()[$category])) { fail('Selecione uma categoria válida.'); }
    $allDay = $_POST['all_day'] ?? '';
    if (!in_array($allDay, ['0', '1'], true)) { fail('Selecione o tipo de evento.'); }
    $start = $end = null;
    if ($allDay === '0') {
        $start = $_POST['starts_at'] ?? '';
        $end = $_POST['ends_at'] ?? '';
        foreach ([$start, $end] as $time) {
            if (!is_string($time) || !preg_match('/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/D', $time)) { fail('Informe os horários de início e fim.'); }
        }
        if ($end <= $start) { fail('O fim deve ser depois do início, no mesmo dia.'); }
    }
    $rawSubject = $_POST['subject_id'] ?? '';
    $subject = $rawSubject === '' ? null : numeric_id($rawSubject);
    if ($subject === 0) { fail('Selecione uma matéria válida.'); }
    return [$title, $description, $date, $priority, $start, $end, $subject, $category];
}
function lock_event_user(int $userId): void { query('SELECT id FROM hc_portal_users WHERE id = ?' . lock_suffix(), [$userId])->fetch(); }
function save_event(array $user, bool $update): void {
    $id = numeric_id($_POST['id'] ?? null);
    // Ownership is checked before accepting any changes, including malformed foreign forms.
    if ($update) { event_record($id, (int) $user['id']); }
    [$title, $description, $date, $priority, $start, $end, $subject, $category] = event_fields();
    $rule = recurrence_rule($date);
    $key = $rule ? recurrence_request_key() : null;
    db()->beginTransaction();
    try {
        if ($subject !== null) { lock_material_subject($subject); }
        lock_event_user((int) $user['id']);
        if (!$update && $rule && ($replayed = recurrence_replayed((int) $user['id'], $key, 'event')) !== null) { db()->commit(); redirect('view-event', ['id' => $replayed]); }
        $notifyOn = $date >= date('Y-m-d') ? $date : null;
        if ($update) {
            $event = event_record($id, (int) $user['id'], true);
            if (!is_string($_POST['revision'] ?? null) || (string) $event['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Este evento foi alterado. Reabra a página antes de continuar.', 409); }
            if ($rule && $event['recurrence_id'] !== null) { db()->rollBack(); fail('A regra desta repetição permanece a cadastrada. Escolha o alcance para editar os compromissos.'); }
            update_recurrence_items('event', $event, [$title, $description, $date, $priority, $start, $end, $subject, $category]);
        } else {
            query('INSERT INTO hc_portal_events (user_id, title, description, event_date, priority, starts_at, ends_at, subject_id, notify_on, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$user['id'], $title, $description, $date, $priority, $start, $end, $subject, $notifyOn, $category]);
            $id = (int) db()->lastInsertId();
        }
        if ($rule) { create_recurrence('event', event_record($id, (int) $user['id'], true), $rule, $key); }
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($update ? 'Evento atualizado.' : 'Evento criado.');
    redirect('view-event', ['id' => $id]);
}
function delete_event(array $user): void {
    $id = numeric_id($_POST['id'] ?? null);
    event_record($id, (int) $user['id']);
    if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão do evento.'); }
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $event = event_record($id, (int) $user['id'], true);
        if (!is_string($_POST['revision'] ?? null) || (string) $event['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Este evento foi alterado. Reabra a página antes de continuar.', 409); }
        $scope = recurrence_scope($event);
        foreach (recurrence_targets('event', $event, $scope) as $target) {
            cancel_event_invitations((int) $target['id']);
            query('UPDATE hc_portal_tasks SET event_id = NULL, revision = revision + 1 WHERE event_id = ? AND user_id = ?', [$target['id'], $user['id']]);
            query('DELETE FROM hc_portal_events WHERE id = ? AND user_id = ?', [$target['id'], $user['id']]);
        }
        touch_recurrence($event);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash('Evento excluído.');
    redirect('agenda', ['mes' => substr($event['event_date'], 0, 7), 'dia' => $event['event_date']]);
}
function sync_event_notifications(int $userId): void {
    sync_invitation_states($userId);
    db()->beginTransaction();
    try {
        // Serializes access for this owner, including simultaneous browser tabs and edits.
        lock_event_user($userId);
        query('INSERT INTO hc_portal_event_notifications (event_id, event_date) SELECT e.id, e.event_date FROM hc_portal_events e WHERE e.user_id = ? AND e.notify_on IS NOT NULL AND e.notify_on <= ? AND NOT EXISTS (SELECT 1 FROM hc_portal_event_notifications n WHERE n.event_id = e.id)', [$userId, date('Y-m-d')]);
        query('INSERT INTO hc_portal_task_notifications (task_id, task_date) SELECT t.id, t.task_date FROM hc_portal_tasks t WHERE t.user_id = ? AND t.completed_at IS NULL AND t.notify_on IS NOT NULL AND t.notify_on <= ? AND NOT EXISTS (SELECT 1 FROM hc_portal_task_notifications n WHERE n.task_id = t.id)', [$userId, date('Y-m-d')]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
}
function event_notifications(int $userId, bool $unreadOnly = false, int $limit = 20, int $offset = 0): array {
    $unread = $unreadOnly ? ' AND n.read_at IS NULL' : '';
    $events = "SELECT n.id AS notification_id, n.read_at, e.id, e.title, e.event_date, e.starts_at, e.ends_at, e.priority, e.category, e.recurrence_id, e.recurrence_exception, s.name AS subject_name, 'event' AS item_kind, NULL AS invitation_state FROM hc_portal_event_notifications n JOIN hc_portal_events e ON e.id = n.event_id LEFT JOIN hc_portal_subjects s ON s.id = e.subject_id WHERE e.user_id = ?" . $unread;
    $tasks = "SELECT n.id AS notification_id, n.read_at, t.id, t.title, t.task_date AS event_date, t.starts_at, t.ends_at, t.priority, t.category, t.recurrence_id, t.recurrence_exception, s.name AS subject_name, 'task' AS item_kind, NULL AS invitation_state FROM hc_portal_task_notifications n JOIN hc_portal_tasks t ON t.id = n.task_id LEFT JOIN hc_portal_subjects s ON s.id = t.subject_id WHERE t.user_id = ?" . $unread;
    $invites = "SELECT i.id AS notification_id, i.read_at, i.id, i.title, i.event_date, i.starts_at, i.ends_at, i.priority, i.category, NULL AS recurrence_id, 0 AS recurrence_exception, s.name AS subject_name, 'invitation' AS item_kind, i.state AS invitation_state FROM hc_portal_invitations i LEFT JOIN hc_portal_subjects s ON s.id = i.subject_id WHERE i.recipient_id = ?" . ($unreadOnly ? ' AND i.read_at IS NULL' : '');
    return query('SELECT * FROM (' . $events . ' UNION ALL ' . $tasks . ' UNION ALL ' . $invites . ') AS notices ORDER BY CASE WHEN read_at IS NULL THEN 0 ELSE 1 END, event_date DESC, item_kind, notification_id DESC LIMIT ' . max(1, $limit) . ' OFFSET ' . max(0, $offset), [$userId, $userId, $userId])->fetchAll();
}
function notification_count(int $userId, bool $unreadOnly = false): int {
    $unread = $unreadOnly ? ' AND n.read_at IS NULL' : '';
    return (int) query('SELECT COUNT(*) FROM hc_portal_event_notifications n JOIN hc_portal_events e ON e.id = n.event_id WHERE e.user_id = ?' . $unread, [$userId])->fetchColumn()
        + (int) query('SELECT COUNT(*) FROM hc_portal_task_notifications n JOIN hc_portal_tasks t ON t.id = n.task_id WHERE t.user_id = ?' . $unread, [$userId])->fetchColumn()
        + (int) query('SELECT COUNT(*) FROM hc_portal_invitations WHERE recipient_id = ?' . ($unreadOnly ? ' AND read_at IS NULL' : ''), [$userId])->fetchColumn();
}
function read_event_notification(array $user): void {
    db()->beginTransaction();
    try {
        lock_event_user((int) $user['id']);
        $notification = query('SELECT n.id FROM hc_portal_event_notifications n JOIN hc_portal_events e ON e.id = n.event_id WHERE n.id = ? AND e.user_id = ?', [numeric_id($_POST['id'] ?? null), $user['id']])->fetch();
        if (!$notification) { db()->rollBack(); fail('Notificação não encontrada.', 404); }
        query('UPDATE hc_portal_event_notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ?', [$notification['id']]);
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    redirect('notifications');
}
