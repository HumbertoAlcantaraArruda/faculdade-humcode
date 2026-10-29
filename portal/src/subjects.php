<?php
declare(strict_types=1);

function subject_record(int $id): array {
    $subject = query('SELECT * FROM hc_portal_subjects WHERE id = ?', [$id])->fetch();
    if (!$subject) { fail('Matéria não encontrada.', 404); }
    return $subject;
}
function subject_url($id): string { return $id === null ? url('unassigned') : url('subject', ['id' => (int) $id]); }

function lock_material_subject(int $id): void {
    $lock = db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : '';
    if (!query('SELECT id FROM hc_portal_subjects WHERE id = ?' . $lock, [$id])->fetch()) {
        db()->rollBack();
        fail('A matéria selecionada não está mais disponível. Escolha outra matéria.');
    }
}

function change_subject(bool $delete): void {
    $id = numeric_id($_POST['id'] ?? null);
    $revision = $_POST['revision'] ?? null;
    if (!is_string($revision) || !ctype_digit($revision)) { fail('Reabra a matéria antes de continuar.', 409); }
    if ($delete) {
        if (($_POST['confirm'] ?? '') !== '1') { fail('Confirme a exclusão da matéria.'); }
    } else {
        $name = field('name', 120);
        $description = field('description', 255, false);
        $color = $_POST['color'] ?? '';
        if (!in_array($color, ['teal', 'blue', 'violet', 'orange', 'rose'], true)) { fail('Selecione uma cor válida.'); }
    }
    db()->beginTransaction();
    try {
        $lock = db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql' ? ' FOR UPDATE' : '';
        $subject = query('SELECT * FROM hc_portal_subjects WHERE id = ?' . $lock, [$id])->fetch();
        if (!$subject) { db()->rollBack(); fail('Matéria não encontrada.', 404); }
        if (!hash_equals((string) $subject['revision'], $revision)) {
            db()->rollBack(); fail('Esta matéria foi alterada. Reabra a página antes de continuar.', 409);
        }
        if ($delete) {
            query("UPDATE hc_portal_invitations SET state = 'canceled', revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE state = 'pending' AND source_event_id IN (SELECT id FROM hc_portal_events WHERE subject_id = ?)", [$id]);
            $importantOwners = query('SELECT DISTINCT user_id FROM hc_portal_notes WHERE subject_id = ? AND important = 1', [$id])->fetchAll(PDO::FETCH_COLUMN);
            query('UPDATE hc_portal_notes SET subject_id = NULL, revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE subject_id = ?', [$id]);
            foreach ($importantOwners as $importantOwner) { trim_important_notes((int) $importantOwner, null); }
            query('UPDATE hc_portal_events SET subject_id = NULL, revision = revision + 1 WHERE subject_id = ?', [$id]);
            query('UPDATE hc_portal_tasks SET subject_id = NULL, revision = revision + 1 WHERE subject_id = ?', [$id]);
            query('UPDATE hc_portal_files SET subject_id = NULL, folder_id = NULL, revision = revision + 1 WHERE subject_id = ?', [$id]);
            query('UPDATE hc_portal_folders SET parent_id = NULL WHERE subject_id = ?', [$id]);
            query('DELETE FROM hc_portal_folders WHERE subject_id = ?', [$id]);
            query('DELETE FROM hc_portal_videos WHERE subject_id = ?', [$id]);
            query('DELETE FROM hc_portal_subjects WHERE id = ?', [$id]);
        } else {
            query('UPDATE hc_portal_subjects SET name = ?, description = ?, color = ?, revision = revision + 1 WHERE id = ?', [$name, $description, $color, $id]);
        }
        db()->commit();
    } catch (Throwable $exception) {
        if (db()->inTransaction()) { db()->rollBack(); }
        if (!$delete && $exception instanceof PDOException && in_array((string) $exception->getCode(), ['23000', '23505'], true)) {
            flash('Já existe uma matéria com esse nome.', 'error'); redirect('edit-subject', ['id' => $id]);
        }
        throw $exception;
    }
    flash($delete ? 'Matéria excluída. Os materiais foram preservados em Sem matéria.' : 'Matéria atualizada.');
    redirect($delete ? 'unassigned' : 'subject', $delete ? [] : ['id' => $id]);
}
