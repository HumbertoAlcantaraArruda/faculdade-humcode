<?php
declare(strict_types=1);

function invitation_states(): array { return ['pending' => 'Pendente', 'accepted' => 'Aceito', 'declined' => 'Recusado', 'canceled' => 'Cancelado']; }

function invitation_record(int $id, int $user, bool $lock = false): array {
    $sql = $lock ? 'SELECT * FROM hc_portal_invitations WHERE id = ? AND (sender_id = ? OR recipient_id = ?)' . lock_suffix()
        : 'SELECT i.*, a.name AS sender_name, b.name AS recipient_name, s.name AS subject_name FROM hc_portal_invitations i JOIN hc_portal_users a ON a.id = i.sender_id JOIN hc_portal_users b ON b.id = i.recipient_id LEFT JOIN hc_portal_subjects s ON s.id = i.subject_id WHERE i.id = ? AND (i.sender_id = ? OR i.recipient_id = ?)';
    $row = query($sql, [$id, $user, $user])->fetch();
    if (!$row) { if (db()->inTransaction()) { db()->rollBack(); } fail('Convite não encontrado.', 404); }
    return $row;
}

function cancel_event_invitations(int $event): void {
    query("UPDATE hc_portal_invitations SET state = 'canceled', revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE source_event_id = ? AND state = 'pending'", [$event]);
}

function sync_invitation_states(int $user, ?int $only = null): void {
    $params = [$user, $user, date('Y-m-d')];
    if ($only !== null) { $params[] = $only; }
    $ids = query("SELECT i.id FROM hc_portal_invitations i LEFT JOIN hc_portal_events e ON e.id = i.source_event_id AND e.user_id = i.sender_id LEFT JOIN hc_portal_users a ON a.id = i.sender_id LEFT JOIN hc_portal_users b ON b.id = i.recipient_id WHERE i.state = 'pending' AND (i.sender_id = ? OR i.recipient_id = ?) AND (i.event_date < ? OR e.id IS NULL OR e.revision <> i.source_revision OR a.active <> 1 OR b.active <> 1)" . ($only !== null ? ' AND i.id = ?' : '') . ' ORDER BY i.id', $params)->fetchAll(PDO::FETCH_COLUMN);
    // Read other accounts without locks; update only pending rows, preserving concurrent responses.
    foreach (array_chunk($ids, 100) as $batch) {
        query("UPDATE hc_portal_invitations SET state = 'canceled', revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE state = 'pending' AND id IN (" . implode(',', array_fill(0, count($batch), '?')) . ')', $batch);
    }
}

function lock_invitation_users(array $ids): array {
    $ids = array_values(array_unique(array_map('intval', $ids))); sort($ids);
    return query('SELECT id, active FROM hc_portal_users WHERE id IN (' . implode(',', array_fill(0, count($ids), '?')) . ') ORDER BY id' . lock_suffix(), $ids)->fetchAll();
}

function send_invitations(array $user): void {
    $eventId = numeric_id($_POST['event_id'] ?? null);
    $before = event_record($eventId, (int) $user['id']);
    $raw = $_POST['recipient_ids'] ?? [];
    if (!is_array($raw) || !$raw || count($raw) > 10) { fail('Selecione de um a dez destinatários.'); }
    $ids = [];
    foreach ($raw as $value) {
        if (!is_string($value) || !ctype_digit($value) || (int) $value < 1 || (int) $value === (int) $user['id'] || in_array((int) $value, $ids, true)) { fail('Selecione destinatários válidos, sem repetição nem autoenvio.'); }
        $ids[] = (int) $value;
    }
    db()->beginTransaction();
    try {
        if ($before['subject_id'] !== null) { query('SELECT id FROM hc_portal_subjects WHERE id = ?' . lock_suffix(), [$before['subject_id']])->fetch(); }
        $users = lock_invitation_users(array_merge([(int) $user['id']], $ids));
        if (count($users) !== count($ids) + 1 || count(array_filter($users, function ($row) { return (int) $row['active'] === 1; })) !== count($users)) { db()->rollBack(); fail('Um destinatário não está disponível.'); }
        $event = event_record($eventId, (int) $user['id'], true);
        if (!is_string($_POST['revision'] ?? null) || (string) $event['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Este evento foi alterado. Reabra a página antes de convidar.', 409); }
        if ($event['event_date'] < date('Y-m-d')) { db()->rollBack(); fail('Não é possível convidar para um evento passado.'); }
        $new = [];
        foreach ($ids as $recipient) {
            if (!query('SELECT id FROM hc_portal_invitations WHERE source_event_id = ? AND recipient_id = ? AND source_revision = ?', [$eventId, $recipient, $event['revision']])->fetch()) { $new[] = $recipient; }
        }
        $recent = (int) query('SELECT COUNT(*) FROM hc_portal_invitations WHERE sender_id = ? AND created_at >= ?', [$user['id'], date('Y-m-d H:i:s', time() - 86400)])->fetchColumn();
        if ($recent + count($new) > 50) { db()->rollBack(); fail('O limite é de cinquenta convites em 24 horas.', 429); }
        foreach ($new as $recipient) {
            query('INSERT INTO hc_portal_invitations (source_event_id, sender_id, recipient_id, source_revision, title, description, event_date, starts_at, ends_at, category, priority, subject_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$eventId, $user['id'], $recipient, $event['revision'], $event['title'], $event['description'], $event['event_date'], $event['starts_at'], $event['ends_at'], $event['category'], $event['priority'], $event['subject_id'], date('Y-m-d H:i:s'), date('Y-m-d H:i:s')]);
        }
        db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($new ? count($new) . ' convite(s) enviado(s) pelo portal.' : 'Esses convites já foram enviados.'); redirect('view-event', ['id' => $eventId]);
}

function answer_invitation(array $user): void {
    $id = numeric_id($_POST['id'] ?? null); $choice = $_POST['choice'] ?? '';
    $before = invitation_record($id, (int) $user['id']);
    if ((int) $before['recipient_id'] !== (int) $user['id']) { fail('Convite não encontrado.', 404); }
    if (!in_array($choice, ['accepted', 'declined'], true)) { fail('Selecione aceitar ou recusar.'); }
    db()->beginTransaction();
    try {
        if ($before['subject_id'] !== null) { query('SELECT id FROM hc_portal_subjects WHERE id = ?' . lock_suffix(), [$before['subject_id']])->fetch(); }
        $users = lock_invitation_users([(int) $before['sender_id'], (int) $user['id']]);
        sync_invitation_states((int) $user['id'], $id);
        $invite = invitation_record($id, (int) $user['id'], true);
        if ($invite['state'] === $choice) { db()->commit(); redirect_back_to_modal('view-invitation', ['id' => $id], 'abrir-convite-' . $id); }
        if ($invite['state'] !== 'pending') { db()->commit(); fail('Este convite já foi respondido ou cancelado. Reabra a página.', 409); }
        if (!is_string($_POST['revision'] ?? null) || (string) $invite['revision'] !== $_POST['revision']) { db()->rollBack(); fail('Este convite foi alterado. Reabra a página.', 409); }
        $copy = null;
        if ($choice === 'accepted') {
            $source = query('SELECT id, revision FROM hc_portal_events WHERE id = ? AND user_id = ?' . lock_suffix(), [$invite['source_event_id'], $invite['sender_id']])->fetch();
            if (!$source || (int) $source['revision'] !== (int) $invite['source_revision'] || $invite['event_date'] < date('Y-m-d') || count($users) !== 2 || count(array_filter($users, function ($row) { return (int) $row['active'] === 1; })) !== 2) { db()->rollBack(); fail('Este convite não está mais disponível.', 409); }
            query('INSERT INTO hc_portal_events (user_id, subject_id, title, description, event_date, starts_at, ends_at, priority, category, notify_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$user['id'], $invite['subject_id'], $invite['title'], $invite['description'], $invite['event_date'], $invite['starts_at'], $invite['ends_at'], $invite['priority'], $invite['category'], $invite['event_date']]);
            $copy = (int) db()->lastInsertId();
        }
        query('UPDATE hc_portal_invitations SET state = ?, accepted_event_id = ?, read_at = COALESCE(read_at, CURRENT_TIMESTAMP), revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND recipient_id = ?', [$choice, $copy, $id, $user['id']]); db()->commit();
    } catch (Throwable $error) { if (db()->inTransaction()) { db()->rollBack(); } throw $error; }
    flash($choice === 'accepted' ? 'Convite aceito. O evento foi adicionado à sua agenda.' : 'Convite recusado.'); redirect_back_to_modal('view-invitation', ['id' => $id], 'abrir-convite-' . $id);
}

function read_invitation_notice(array $user): void {
    $id = numeric_id($_POST['id'] ?? null);
    $invite = invitation_record($id, (int) $user['id']);
    if ((int) $invite['recipient_id'] !== (int) $user['id']) { fail('Convite não encontrado.', 404); }
    query('UPDATE hc_portal_invitations SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ? AND recipient_id = ?', [$id, $user['id']]); redirect('notifications');
}

function render_invitation_row(array $invite, int $user): void { ?>
<article class="invitation-row note-card" data-invitation-row="<?= (int) $invite['id'] ?>"><h3 class="note-card-title"><a href="<?= e(url('view-invitation', ['id' => $invite['id']])) ?>" data-detail-link data-detail-key="abrir-convite-<?= (int) $invite['id'] ?>"><?= e($invite['title']) ?></a></h3><p class="note-card-meta"><?= e(event_day_label($invite['event_date'])) ?> · <?= e(event_time_label($invite)) ?></p><p class="note-card-excerpt"><?= (int) $invite['sender_id'] === $user ? 'Para: ' . e($invite['recipient_name']) : 'De: ' . e($invite['sender_name']) ?></p><p class="invitation-status"><strong data-invitation-state="<?= e($invite['state']) ?>"><?= e(invitation_states()[$invite['state']]) ?></strong></p></article>
<?php }

function render_event_invitations(array $event): void {
    $owner = (int) current_user()['id'];
    $rows = query('SELECT i.*, a.name AS sender_name, b.name AS recipient_name FROM hc_portal_invitations i JOIN hc_portal_users a ON a.id = i.sender_id JOIN hc_portal_users b ON b.id = i.recipient_id WHERE i.sender_id = ? AND i.source_event_id = ? ORDER BY i.id DESC LIMIT 20', [$owner, $event['id']])->fetchAll(); ?>
<section class="form-card event-invitations" aria-labelledby="event-invitations-heading"><div class="calendar-toolbar"><h2 id="event-invitations-heading">Convites deste evento</h2><?php if ($event['event_date'] >= date('Y-m-d')): ?><a class="button button-secondary" href="<?= e(url('invite-users', ['event_id' => $event['id']])) ?>"><?= icon('users') ?>Convidar usuários</a><?php endif; ?></div><p class="form-hint">O destinatário aceita ou recusa antes da inclusão em sua agenda. Alterar ou excluir o evento cancela convites pendentes. A cópia aceita é independente, sem tarefas nem conteúdos vinculados.</p><?php if (!$rows): ?><p class="muted">Nenhum convite enviado para esta ocorrência.</p><?php endif; ?><?php if ($rows): ?><div class="note-grid"><?php foreach ($rows as $invite): render_invitation_row($invite, $owner); endforeach; ?></div><?php endif; ?><a href="<?= e(url('invitations', ['direction' => 'sent'])) ?>">Ver meus convites enviados</a></section>
<?php }

function render_invite_users(array $event): void {
    if ($event['event_date'] < date('Y-m-d')) { fail('Não é possível convidar para um evento passado.'); }
    $search = $_GET['q'] ?? '';
    if (!is_string($search) || strlen($search) > 400 || !preg_match('//u', $search)) { fail('Informe uma busca válida.'); }
    $where = 'active = 1 AND id <> ?'; $params = [$event['user_id']];
    if (trim($search) !== '') { $where .= ' AND (name LIKE ? OR login LIKE ?)'; $params[] = '%' . trim($search) . '%'; $params[] = '%' . trim($search) . '%'; }
    $total = (int) query('SELECT COUNT(*) FROM hc_portal_users WHERE ' . $where, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / 20)); $page = min($pages, max(1, numeric_id($_GET['pagina'] ?? 1)));
    $users = query('SELECT id, name, login FROM hc_portal_users WHERE ' . $where . ' ORDER BY name, id LIMIT 20 OFFSET ' . (($page - 1) * 20), $params)->fetchAll();
    page_start('Convidar usuários', 'invitations'); ?>
<a class="back-link" href="<?= e(url('view-event', ['id' => $event['id']])) ?>"><?= icon('back') ?>Voltar ao evento</a><div class="page-heading"><div><h1>Convidar usuários</h1><p><?= e($event['title']) ?> · <?= e(event_day_label($event['event_date'])) ?></p></div></div><section class="form-card"><form method="get" action="<?= e(url('invite-users')) ?>"><input type="hidden" name="event_id" value="<?= (int) $event['id'] ?>"><label>Buscar por nome ou usuário<input name="q" value="<?= e($search) ?>" maxlength="100"></label><button class="button button-secondary" type="submit">Buscar usuários</button></form><?php if ($users): ?><form class="invitation-send-form" method="post" action="<?= e(url('send-invitations')) ?>"><?= csrf() ?><input type="hidden" name="event_id" value="<?= (int) $event['id'] ?>"><input type="hidden" name="revision" value="<?= (int) $event['revision'] ?>"><label>Destinatários<select name="recipient_ids[]" multiple required data-max-selections="10"><?php foreach ($users as $person): ?><option value="<?= (int) $person['id'] ?>"><?= e($person['name'] . ' · ' . $person['login']) ?></option><?php endforeach; ?></select></label><p class="form-hint">Até dez pessoas por envio e cinquenta convites em 24 horas. O convite inclui somente esta ocorrência, sem tarefas nem conteúdos. Os avisos são enviados pelo portal; o envio por e-mail ainda não está ativo.</p><button class="button button-primary" type="submit"><?= icon('users') ?>Enviar convites</button></form><?php else: ?><p class="muted">Nenhum usuário disponível nesta busca.</p><?php endif; ?><?php if ($pages > 1): ?><nav class="calendar-toolbar" aria-label="Paginação de destinatários"><?php if ($page > 1): ?><a href="<?= e(url('invite-users', ['event_id' => $event['id'], 'q' => $search, 'pagina' => $page - 1])) ?>">Anterior</a><?php endif; ?><span>Página <?= $page ?> de <?= $pages ?></span><?php if ($page < $pages): ?><a href="<?= e(url('invite-users', ['event_id' => $event['id'], 'q' => $search, 'pagina' => $page + 1])) ?>">Próxima</a><?php endif; ?></nav><?php endif; ?></section>
<?php page_end();
}

function render_invitations(array $user): void {
    $direction = $_GET['direction'] ?? 'received'; $state = $_GET['state'] ?? '';
    if (!in_array($direction, ['received', 'sent'], true) || !is_string($state) || ($state !== '' && !isset(invitation_states()[$state]))) { fail('Selecione filtros válidos.'); }
    $where = 'i.' . ($direction === 'sent' ? 'sender_id' : 'recipient_id') . ' = ?'; $params = [$user['id']];
    if ($state !== '') { $where .= ' AND i.state = ?'; $params[] = $state; }
    $total = (int) query('SELECT COUNT(*) FROM hc_portal_invitations i WHERE ' . $where, $params)->fetchColumn();
    $pages = max(1, (int) ceil($total / 20)); $page = min($pages, max(1, numeric_id($_GET['pagina'] ?? 1)));
    $rows = query('SELECT i.*, a.name AS sender_name, b.name AS recipient_name FROM hc_portal_invitations i JOIN hc_portal_users a ON a.id = i.sender_id JOIN hc_portal_users b ON b.id = i.recipient_id WHERE ' . $where . ' ORDER BY i.id DESC LIMIT 20 OFFSET ' . (($page - 1) * 20), $params)->fetchAll();
    page_start('Meus convites', 'invitations'); ?>
<div class="page-heading"><div><h1>Meus convites</h1><p>Aceite ou recuse os eventos antes de adicioná-los à sua agenda.</p></div></div><section class="form-card invitations-card"><form method="get" action="<?= e(url('invitations')) ?>" class="invitation-filter-form"><div class="invitation-filter-field"><label for="invitation-direction">Convites</label><select id="invitation-direction" name="direction" aria-label="Convites"><option value="received" <?= $direction === 'received' ? 'selected' : '' ?>>Recebidos</option><option value="sent" <?= $direction === 'sent' ? 'selected' : '' ?>>Enviados</option></select></div><div class="invitation-filter-field"><label for="invitation-state">Estado</label><div class="notes-filter-group"><select id="invitation-state" name="state" aria-label="Estado"><option value="">Todos</option><?php foreach (invitation_states() as $key => $label): ?><option value="<?= e($key) ?>" <?= $state === $key ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select><button class="button button-secondary" type="submit" title="Filtrar"><?= icon('search') ?><span>Filtrar</span></button></div></div></form><p class="muted" data-invitation-total="<?= $total ?>"><?= $total ?> convites</p><?php if (!$rows): ?><p>Nenhum convite encontrado.</p><?php endif; ?><?php if ($rows): ?><div class="note-grid"><?php foreach ($rows as $invite): render_invitation_row($invite, (int) $user['id']); endforeach; ?></div><?php endif; ?></section><?php if ($pages > 1): ?><nav class="calendar-toolbar" aria-label="Paginação de convites"><?php if ($page > 1): ?><a href="<?= e(url('invitations', ['direction' => $direction, 'state' => $state, 'pagina' => $page - 1])) ?>">Anterior</a><?php endif; ?><span>Página <?= $page ?> de <?= $pages ?></span><?php if ($page < $pages): ?><a href="<?= e(url('invitations', ['direction' => $direction, 'state' => $state, 'pagina' => $page + 1])) ?>">Próxima</a><?php endif; ?></nav><?php endif; ?>
<?php page_end();
}

function render_invitation(array $invite, array $user): void {
    $recipient = (int) $invite['recipient_id'] === (int) $user['id'];
    detail_start('Convite para evento', 'invitations'); ?>
<?php if (!modal_request()): ?><a class="back-link" href="<?= e(url('invitations', ['direction' => $recipient ? 'received' : 'sent'])) ?>"><?= icon('back') ?>Voltar aos convites</a><?php endif; ?><div class="page-heading"><div><span class="eyebrow">CONVITE PARA EVENTO</span><h1><?= e($invite['title']) ?></h1><p><?= e(event_day_label($invite['event_date'])) ?> · <?= e(event_time_label($invite)) ?></p></div><?php if (modal_request()): ?><div class="heading-actions"><button type="button" class="button button-primary note-edit-button" data-close title="Fechar"><?= icon('close') ?><span class="sr-only">Fechar</span></button></div><?php endif; ?></div><section class="form-card"><p><?= $recipient ? 'De: ' . e($invite['sender_name']) : 'Para: ' . e($invite['recipient_name']) ?></p><p><strong data-invitation-state="<?= e($invite['state']) ?>"><?= e(invitation_states()[$invite['state']]) ?></strong></p><p>Categoria: <?= e(event_category_label($invite)) ?></p><p>Matéria: <?= e($invite['subject_name'] ?? 'Sem matéria') ?></p><div class="invitation-body"><?= e($invite['description']) ?></div><?php if ($recipient && $invite['state'] === 'pending'): ?><p class="form-hint">Ao aceitar, uma cópia independente será adicionada à sua agenda, sem tarefas nem conteúdos. Alterações futuras no evento original não mudam sua cópia.</p><form class="invitation-answer" method="post" action="<?= e(url('answer-invitation')) ?>"><?= csrf() ?><input type="hidden" name="id" value="<?= (int) $invite['id'] ?>"><input type="hidden" name="revision" value="<?= (int) $invite['revision'] ?>"><?php if (modal_request()): ?><input type="hidden" name="return" value="modal" data-return-path><?php endif; ?><button class="button button-primary" name="choice" value="accepted" type="submit"><?= icon('check') ?>Aceitar convite</button><button class="button button-secondary" name="choice" value="declined" type="submit">Recusar convite</button></form><?php elseif ($recipient && $invite['state'] === 'accepted' && $invite['accepted_event_id'] !== null): ?><a class="button button-primary" data-accepted-event="<?= (int) $invite['accepted_event_id'] ?>" href="<?= e(url('view-event', ['id' => $invite['accepted_event_id']])) ?>">Abrir na minha agenda</a><?php endif; ?></section>
<?php detail_end();
}

