<?php
declare(strict_types=1);

function portal_schema_columns(): array {
    $columns = [];
    if (db()->getAttribute(PDO::ATTR_DRIVER_NAME) === 'mysql') {
        foreach (query("SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('hc_portal_subjects', 'hc_portal_files', 'hc_portal_videos', 'hc_portal_folders', 'hc_portal_events', 'hc_portal_event_notifications', 'hc_portal_tasks', 'hc_portal_task_notifications', 'hc_portal_recurrences', 'hc_portal_event_files', 'hc_portal_event_videos', 'hc_portal_event_folders', 'hc_portal_task_files', 'hc_portal_task_videos', 'hc_portal_task_folders', 'hc_portal_file_study', 'hc_portal_video_study', 'hc_portal_notes', 'hc_portal_note_files', 'hc_portal_invitations', 'hc_portal_users', 'hc_portal_two_factor_codes', 'hc_portal_trusted_devices')")->fetchAll() as $row) {
            $columns[$row['TABLE_NAME']][$row['COLUMN_NAME']] = $row['IS_NULLABLE'] === 'YES';
        }
    } else {
        foreach (['hc_portal_subjects', 'hc_portal_files', 'hc_portal_videos', 'hc_portal_folders', 'hc_portal_events', 'hc_portal_event_notifications', 'hc_portal_tasks', 'hc_portal_task_notifications', 'hc_portal_recurrences', 'hc_portal_event_files', 'hc_portal_event_videos', 'hc_portal_event_folders', 'hc_portal_task_files', 'hc_portal_task_videos', 'hc_portal_task_folders', 'hc_portal_file_study', 'hc_portal_video_study', 'hc_portal_notes', 'hc_portal_note_files', 'hc_portal_invitations', 'hc_portal_users', 'hc_portal_two_factor_codes', 'hc_portal_trusted_devices'] as $table) {
            foreach (query('PRAGMA table_info(' . $table . ')')->fetchAll() as $row) { $columns[$table][$row['name']] = !(int) $row['notnull']; }
        }
    }
    return $columns;
}

function portal_schema_ready(): bool {
    $columns = portal_schema_columns();
    return isset($columns['hc_portal_subjects']['revision'], $columns['hc_portal_files']['legacy_path'], $columns['hc_portal_files']['deleted_at'], $columns['hc_portal_files']['revision']) && ($columns['hc_portal_files']['subject_id'] ?? false)
        && isset($columns['hc_portal_videos']['youtube_id'], $columns['hc_portal_videos']['sort_order'], $columns['hc_portal_videos']['revision'])
        && isset($columns['hc_portal_files']['folder_id'], $columns['hc_portal_files']['kind'], $columns['hc_portal_folders']['revision'], $columns['hc_portal_folders']['parent_id'])
        && isset($columns['hc_portal_events']['notify_on'], $columns['hc_portal_events']['revision'], $columns['hc_portal_events']['category'], $columns['hc_portal_event_notifications']['event_date'], $columns['hc_portal_event_notifications']['read_at'])
        && isset($columns['hc_portal_tasks']['completed_at'], $columns['hc_portal_tasks']['event_id'], $columns['hc_portal_tasks']['revision'], $columns['hc_portal_task_notifications']['read_at'])
        && isset($columns['hc_portal_recurrences']['request_key'], $columns['hc_portal_recurrences']['revision'], $columns['hc_portal_events']['recurrence_id'], $columns['hc_portal_events']['occurrence_date'], $columns['hc_portal_events']['recurrence_exception'], $columns['hc_portal_tasks']['recurrence_id'], $columns['hc_portal_tasks']['occurrence_date'], $columns['hc_portal_tasks']['recurrence_exception'], $columns['hc_portal_tasks']['recurrence_slot'])
        && isset($columns['hc_portal_event_files']['event_id'], $columns['hc_portal_event_files']['file_id'])
        && isset($columns['hc_portal_event_videos']['event_id'], $columns['hc_portal_event_videos']['video_id'])
        && isset($columns['hc_portal_event_folders']['event_id'], $columns['hc_portal_event_folders']['folder_id'])
        && isset($columns['hc_portal_task_files']['task_id'], $columns['hc_portal_task_files']['file_id'])
        && isset($columns['hc_portal_task_videos']['task_id'], $columns['hc_portal_task_videos']['video_id'])
        && isset($columns['hc_portal_task_folders']['task_id'], $columns['hc_portal_task_folders']['folder_id'])
        && isset($columns['hc_portal_file_study']['marked_at'], $columns['hc_portal_file_study']['user_id'], $columns['hc_portal_file_study']['file_id'])
        && isset($columns['hc_portal_video_study']['marked_at'], $columns['hc_portal_video_study']['user_id'], $columns['hc_portal_video_study']['video_id'])
        && isset($columns['hc_portal_notes']['user_id'], $columns['hc_portal_notes']['subject_id'], $columns['hc_portal_notes']['body'], $columns['hc_portal_notes']['revision'], $columns['hc_portal_notes']['important'])
        && isset($columns['hc_portal_note_files']['note_id'], $columns['hc_portal_note_files']['user_id'], $columns['hc_portal_note_files']['stored_path'], $columns['hc_portal_note_files']['size'])
        && isset($columns['hc_portal_users']['email'], $columns['hc_portal_invitations']['recipient_id'], $columns['hc_portal_invitations']['state'], $columns['hc_portal_invitations']['source_revision'], $columns['hc_portal_invitations']['revision'])
        && isset($columns['hc_portal_users']['two_factor_enabled'], $columns['hc_portal_two_factor_codes']['code_hash'], $columns['hc_portal_two_factor_codes']['purpose'], $columns['hc_portal_trusted_devices']['token_hash']);
}

function migrate_portal(): array {
    if (db()->getAttribute(PDO::ATTR_DRIVER_NAME) !== 'mysql') { throw new RuntimeException('As migrações de produção requerem MySQL/MariaDB.'); }
    $locked = (int) query("SELECT GET_LOCK('hc_portal_migrations', 10)")->fetchColumn();
    if ($locked !== 1) { throw new RuntimeException('Outra atualização está em andamento.'); }
    $applied = [];
    try {
        $columns = portal_schema_columns();
        if (empty($columns['hc_portal_files']) || empty($columns['hc_portal_subjects'])) { throw new RuntimeException('Instale o portal antes de executar migrações.'); }
        foreach (['legacy_path' => 'VARCHAR(512) NULL', 'deleted_at' => 'TIMESTAMP NULL DEFAULT NULL', 'revision' => 'INT NOT NULL DEFAULT 1'] as $name => $definition) {
            if (!array_key_exists($name, $columns['hc_portal_files'])) {
                query('ALTER TABLE hc_portal_files ADD COLUMN ' . $name . ' ' . $definition);
                $applied[] = 'hc_portal_files.' . $name;
            }
        }
        $indexed = query("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hc_portal_files' AND INDEX_NAME = 'hc_portal_legacy_path'")->fetch();
        if (!$indexed) { query('ALTER TABLE hc_portal_files ADD UNIQUE KEY hc_portal_legacy_path (legacy_path)'); $applied[] = 'hc_portal_legacy_path'; }
        query("UPDATE hc_portal_files SET legacy_path = stored_path WHERE source = 'legacy' AND legacy_path IS NULL");
        if (!array_key_exists('revision', $columns['hc_portal_subjects'])) { query('ALTER TABLE hc_portal_subjects ADD COLUMN revision INT NOT NULL DEFAULT 1'); $applied[] = 'hc_portal_subjects.revision'; }
        if (!$columns['hc_portal_files']['subject_id']) { query('ALTER TABLE hc_portal_files MODIFY COLUMN subject_id BIGINT UNSIGNED NULL'); $applied[] = 'hc_portal_files.subject_id nullable'; }
        if (empty($columns['hc_portal_videos'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_videos (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, subject_id BIGINT UNSIGNED NOT NULL, title VARCHAR(180) NOT NULL, youtube_id CHAR(11) NOT NULL, sort_order INT NOT NULL DEFAULT 1, revision INT NOT NULL DEFAULT 1, created_by BIGINT UNSIGNED NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, KEY hc_portal_video_subject (subject_id, sort_order), FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id), FOREIGN KEY (created_by) REFERENCES hc_portal_users(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_videos';
        }
        if (empty($columns['hc_portal_folders'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_folders (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, subject_id BIGINT UNSIGNED NOT NULL, parent_id BIGINT UNSIGNED NULL, name VARCHAR(120) NOT NULL, revision INT NOT NULL DEFAULT 1, created_by BIGINT UNSIGNED NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, KEY hc_portal_folder_parent (subject_id, parent_id), FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id), FOREIGN KEY (parent_id) REFERENCES hc_portal_folders(id), FOREIGN KEY (created_by) REFERENCES hc_portal_users(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_folders';
        }
        foreach (['folder_id' => 'BIGINT UNSIGNED NULL', 'kind' => "VARCHAR(16) NOT NULL DEFAULT 'material'"] as $name => $definition) {
            if (!array_key_exists($name, $columns['hc_portal_files'])) {
                query('ALTER TABLE hc_portal_files ADD COLUMN ' . $name . ' ' . $definition);
                $applied[] = 'hc_portal_files.' . $name;
            }
        }
        if (!query("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hc_portal_files' AND COLUMN_NAME = 'folder_id' AND SEQ_IN_INDEX = 1")->fetch()) {
            query('ALTER TABLE hc_portal_files ADD KEY hc_portal_file_folder (folder_id)'); $applied[] = 'hc_portal_file_folder';
        }
        if (!query("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hc_portal_files' AND COLUMN_NAME = 'folder_id' AND REFERENCED_TABLE_NAME = 'hc_portal_folders'")->fetch()) {
            query('ALTER TABLE hc_portal_files ADD CONSTRAINT hc_portal_file_folder_fk FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id)'); $applied[] = 'hc_portal_file_folder_fk';
        }
        if (empty($columns['hc_portal_events'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_events ( id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL, subject_id BIGINT UNSIGNED NULL, title VARCHAR(180) NOT NULL, description TEXT NOT NULL, event_date DATE NOT NULL, starts_at TIME NULL, ends_at TIME NULL, priority VARCHAR(16) NOT NULL DEFAULT \'media\', notify_on DATE NULL, revision INT NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, KEY hc_portal_event_day (user_id, event_date), KEY hc_portal_event_due (user_id, notify_on), FOREIGN KEY (user_id) REFERENCES hc_portal_users(id), FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_events';
        }
        if (empty($columns['hc_portal_event_notifications'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_event_notifications ( id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, event_id BIGINT UNSIGNED NOT NULL, event_date DATE NOT NULL, read_at TIMESTAMP NULL DEFAULT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY hc_portal_notification_event (event_id), FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_event_notifications';
        }
        if (!isset($columns['hc_portal_events']['category'])) {
            query('ALTER TABLE hc_portal_events ADD COLUMN category VARCHAR(32) NULL DEFAULT NULL');
            $applied[] = 'hc_portal_events.category';
        }
        if (empty($columns['hc_portal_tasks'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_tasks ( id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL, event_id BIGINT UNSIGNED NULL, subject_id BIGINT UNSIGNED NULL, title VARCHAR(180) NOT NULL, description TEXT NOT NULL, task_date DATE NOT NULL, starts_at TIME NULL, ends_at TIME NULL, priority VARCHAR(16) NOT NULL DEFAULT \'media\', category VARCHAR(32) NOT NULL, completed_at TIMESTAMP NULL DEFAULT NULL, notify_on DATE NULL, revision INT NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, KEY hc_portal_task_day (user_id, task_date), KEY hc_portal_task_event (event_id), KEY hc_portal_task_due (user_id, notify_on), FOREIGN KEY (user_id) REFERENCES hc_portal_users(id), FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE SET NULL, FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_tasks';
        }
        if (empty($columns['hc_portal_task_notifications'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_task_notifications ( id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, task_id BIGINT UNSIGNED NOT NULL, task_date DATE NOT NULL, read_at TIMESTAMP NULL DEFAULT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY hc_portal_notification_task (task_id), FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_task_notifications';
        }

        if (empty($columns['hc_portal_recurrences'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_recurrences (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    item_kind VARCHAR(16) NOT NULL,
    frequency VARCHAR(16) NOT NULL,
    interval_count INT NOT NULL,
    occurrence_count INT NOT NULL,
    weekdays VARCHAR(13) NOT NULL DEFAULT \'\',
    anchor_date DATE NOT NULL,
    request_key CHAR(32) NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_recurrence_request (user_id, request_key),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_recurrences';
        }
        foreach (['hc_portal_events', 'hc_portal_tasks'] as $table) {
            $fields = ['recurrence_id' => 'BIGINT UNSIGNED NULL', 'occurrence_date' => 'DATE NULL', 'recurrence_exception' => 'TINYINT NOT NULL DEFAULT 0'];
            if ($table === 'hc_portal_tasks') { $fields['recurrence_slot'] = 'INT NOT NULL DEFAULT 0'; }
            foreach ($fields as $name => $definition) {
                if (!array_key_exists($name, $columns[$table] ?? [])) {
                    query('ALTER TABLE ' . $table . ' ADD COLUMN ' . $name . ' ' . $definition);
                    $applied[] = $table . '.' . $name;
                }
            }
            $index = $table === 'hc_portal_events' ? 'hc_portal_event_occurrence' : 'hc_portal_task_occurrence';
            if (!query('SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ?', [$table, $index])->fetch()) {
                query('ALTER TABLE ' . $table . ' ADD UNIQUE KEY ' . $index . ' (recurrence_id, occurrence_date' . ($table === 'hc_portal_tasks' ? ', recurrence_slot' : '') . ')');
                $applied[] = $index;
            }
            if (!query("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = 'recurrence_id' AND REFERENCED_TABLE_NAME = 'hc_portal_recurrences'", [$table])->fetch()) {
                query('ALTER TABLE ' . $table . ' ADD CONSTRAINT ' . $table . '_recurrence_fk FOREIGN KEY (recurrence_id) REFERENCES hc_portal_recurrences(id)');
                $applied[] = $table . '.recurrence_fk';
            }
        }
        if (empty($columns['hc_portal_event_files'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_event_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_files_unique (event_id, file_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_event_files';
        }
        if (empty($columns['hc_portal_event_videos'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_event_videos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_videos_unique (event_id, video_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_event_videos';
        }
        if (empty($columns['hc_portal_event_folders'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_event_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    folder_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_folders_unique (event_id, folder_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_event_folders';
        }
        if (empty($columns['hc_portal_task_files'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_task_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_files_unique (task_id, file_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_task_files';
        }
        if (empty($columns['hc_portal_task_videos'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_task_videos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_videos_unique (task_id, video_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_task_videos';
        }
        if (empty($columns['hc_portal_task_folders'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_task_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    folder_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_folders_unique (task_id, folder_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_task_folders';
        }
        if (empty($columns['hc_portal_file_study'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_file_study (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    marked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_file_study_unique (user_id, file_id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_file_study';
        }
        if (empty($columns['hc_portal_video_study'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_video_study (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    marked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_video_study_unique (user_id, video_id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_video_study';
        }
        if (empty($columns['hc_portal_notes'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_notes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    subject_id BIGINT UNSIGNED NULL,
    title VARCHAR(180) NOT NULL,
    body MEDIUMTEXT NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_notes_owner (user_id, subject_id, updated_at),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_notes';
        }
        if (empty($columns['hc_portal_note_files'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_note_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    note_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_path VARCHAR(64) NOT NULL,
    extension VARCHAR(12) NOT NULL,
    mime VARCHAR(128) NOT NULL,
    size BIGINT UNSIGNED NOT NULL,
    sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_note_file_path (stored_path),
    KEY hc_portal_note_files_note (note_id, id),
    FOREIGN KEY (note_id) REFERENCES hc_portal_notes(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_note_files';
        }
        if (!array_key_exists('important', $columns['hc_portal_notes'] ?? [])) { query('ALTER TABLE hc_portal_notes ADD COLUMN important TINYINT(1) NOT NULL DEFAULT 0'); $applied[] = 'hc_portal_notes.important'; }
        if (!array_key_exists('email', $columns['hc_portal_users'] ?? [])) { query('ALTER TABLE hc_portal_users ADD COLUMN email VARCHAR(254) NULL'); $applied[] = 'hc_portal_users.email'; }
        if (empty($columns['hc_portal_invitations'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_invitations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source_event_id BIGINT UNSIGNED NULL,
    sender_id BIGINT UNSIGNED NOT NULL,
    recipient_id BIGINT UNSIGNED NOT NULL,
    source_revision INT NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT \'pending\',
    title VARCHAR(180) NOT NULL,
    description TEXT NOT NULL,
    event_date DATE NOT NULL,
    starts_at TIME NULL,
    ends_at TIME NULL,
    category VARCHAR(32) NULL,
    priority VARCHAR(16) NOT NULL,
    subject_id BIGINT UNSIGNED NULL,
    accepted_event_id BIGINT UNSIGNED NULL,
    read_at TIMESTAMP NULL DEFAULT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_invitation_version (source_event_id, recipient_id, source_revision),
    KEY hc_portal_invitation_recipient (recipient_id, read_at),
    KEY hc_portal_invitation_sender (sender_id, created_at),
    FOREIGN KEY (source_event_id) REFERENCES hc_portal_events(id) ON DELETE SET NULL,
    FOREIGN KEY (accepted_event_id) REFERENCES hc_portal_events(id) ON DELETE SET NULL,
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL,
    FOREIGN KEY (sender_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_invitations';
        }
        if (!array_key_exists('two_factor_enabled', $columns['hc_portal_users'] ?? [])) { query('ALTER TABLE hc_portal_users ADD COLUMN two_factor_enabled TINYINT NOT NULL DEFAULT 0'); $applied[] = 'hc_portal_users.two_factor_enabled'; }
        if (empty($columns['hc_portal_two_factor_codes'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_two_factor_codes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    purpose VARCHAR(16) NOT NULL,
    email VARCHAR(254) NOT NULL,
    code_hash VARCHAR(255) NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    expires_at BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    consumed_at BIGINT NULL,
    KEY hc_portal_two_factor_user (user_id, purpose, created_at),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_two_factor_codes';
        }
        if (empty($columns['hc_portal_trusted_devices'])) {
            query('CREATE TABLE IF NOT EXISTS hc_portal_trusted_devices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    UNIQUE KEY hc_portal_trusted_token (token_hash),
    KEY hc_portal_trusted_user (user_id, expires_at),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci');
            $applied[] = 'hc_portal_trusted_devices';
        }
        if (!portal_schema_ready()) { throw new RuntimeException('O esquema não ficou compatível após a migração.'); }
        return $applied;
    } finally { query("SELECT RELEASE_LOCK('hc_portal_migrations')"); }
}
