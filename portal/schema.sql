CREATE TABLE IF NOT EXISTS hc_portal_users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    login VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(254) NULL,
    two_factor_enabled TINYINT NOT NULL DEFAULT 0,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'member',
    active TINYINT NOT NULL DEFAULT 1,
    must_change_password TINYINT NOT NULL DEFAULT 1,
    session_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_subjects (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    description VARCHAR(255) NOT NULL DEFAULT '',
    color VARCHAR(16) NOT NULL DEFAULT 'teal',
    revision INT NOT NULL DEFAULT 1,
    created_by BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    subject_id BIGINT UNSIGNED NOT NULL,
    parent_id BIGINT UNSIGNED NULL,
    name VARCHAR(120) NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_by BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_folder_parent (subject_id, parent_id),
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id),
    FOREIGN KEY (parent_id) REFERENCES hc_portal_folders(id),
    FOREIGN KEY (created_by) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    subject_id BIGINT UNSIGNED NULL,
    folder_id BIGINT UNSIGNED NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'material',
    title VARCHAR(180) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_path VARCHAR(512) NOT NULL,
    source VARCHAR(16) NOT NULL,
    extension VARCHAR(12) NOT NULL,
    mime VARCHAR(128) NOT NULL,
    size BIGINT UNSIGNED NOT NULL,
    sha256 CHAR(64) NOT NULL,
    trusted_app TINYINT NOT NULL DEFAULT 0,
    uploaded_by BIGINT UNSIGNED NULL,
    legacy_path VARCHAR(512) NULL,
    deleted_at TIMESTAMP NULL DEFAULT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_file_path (source, stored_path),
    UNIQUE KEY hc_portal_legacy_path (legacy_path),
    KEY hc_portal_file_subject (subject_id, created_at),
    KEY hc_portal_file_folder (folder_id),
    FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id),
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id),
    FOREIGN KEY (uploaded_by) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_videos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    subject_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(180) NOT NULL,
    youtube_id CHAR(11) NOT NULL,
    sort_order INT NOT NULL DEFAULT 1,
    revision INT NOT NULL DEFAULT 1,
    created_by BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_video_subject (subject_id, sort_order),
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id),
    FOREIGN KEY (created_by) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_login_attempts (
    attempt_key CHAR(64) NOT NULL PRIMARY KEY,
    failures INT NOT NULL DEFAULT 0,
    first_at BIGINT NOT NULL,
    blocked_until BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_recurrences (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    item_kind VARCHAR(16) NOT NULL,
    frequency VARCHAR(16) NOT NULL,
    interval_count INT NOT NULL,
    occurrence_count INT NOT NULL,
    weekdays VARCHAR(13) NOT NULL DEFAULT '',
    anchor_date DATE NOT NULL,
    request_key CHAR(32) NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_recurrence_request (user_id, request_key),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    subject_id BIGINT UNSIGNED NULL,
    title VARCHAR(180) NOT NULL,
    description TEXT NOT NULL,
    event_date DATE NOT NULL,
    starts_at TIME NULL,
    ends_at TIME NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'media',
    notify_on DATE NULL,
    category VARCHAR(32) NULL DEFAULT NULL,
    recurrence_id BIGINT UNSIGNED NULL,
    occurrence_date DATE NULL,
    recurrence_exception TINYINT NOT NULL DEFAULT 0,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_event_day (user_id, event_date),
    KEY hc_portal_event_due (user_id, notify_on),
    UNIQUE KEY hc_portal_event_occurrence (recurrence_id, occurrence_date),
    FOREIGN KEY (recurrence_id) REFERENCES hc_portal_recurrences(id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id),
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_event_notifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    event_date DATE NOT NULL,
    read_at TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_notification_event (event_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_tasks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    event_id BIGINT UNSIGNED NULL,
    subject_id BIGINT UNSIGNED NULL,
    title VARCHAR(180) NOT NULL,
    description TEXT NOT NULL,
    task_date DATE NOT NULL,
    starts_at TIME NULL,
    ends_at TIME NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'media',
    category VARCHAR(32) NOT NULL,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    recurrence_id BIGINT UNSIGNED NULL,
    occurrence_date DATE NULL,
    recurrence_exception TINYINT NOT NULL DEFAULT 0,
    recurrence_slot INT NOT NULL DEFAULT 0,
    notify_on DATE NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_task_day (user_id, task_date),
    KEY hc_portal_task_event (event_id),
    KEY hc_portal_task_due (user_id, notify_on),
    UNIQUE KEY hc_portal_task_occurrence (recurrence_id, occurrence_date, recurrence_slot),
    FOREIGN KEY (recurrence_id) REFERENCES hc_portal_recurrences(id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE SET NULL,
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_task_notifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    task_date DATE NOT NULL,
    read_at TIMESTAMP NULL DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_notification_task (task_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_event_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_files_unique (event_id, file_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_event_videos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_videos_unique (event_id, video_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_event_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL,
    folder_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_event_folders_unique (event_id, folder_id),
    FOREIGN KEY (event_id) REFERENCES hc_portal_events(id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_task_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_files_unique (task_id, file_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_task_videos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_videos_unique (task_id, video_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_task_folders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    task_id BIGINT UNSIGNED NOT NULL,
    folder_id BIGINT UNSIGNED NOT NULL,
    UNIQUE KEY hc_portal_task_folders_unique (task_id, folder_id),
    FOREIGN KEY (task_id) REFERENCES hc_portal_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_file_study (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    marked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_file_study_unique (user_id, file_id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES hc_portal_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_video_study (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    video_id BIGINT UNSIGNED NOT NULL,
    marked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY hc_portal_video_study_unique (user_id, video_id),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES hc_portal_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_notes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    subject_id BIGINT UNSIGNED NULL,
    title VARCHAR(180) NOT NULL,
    body MEDIUMTEXT NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    important TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_notes_owner (user_id, subject_id, updated_at),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES hc_portal_subjects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_note_files (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_invitations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source_event_id BIGINT UNSIGNED NULL,
    sender_id BIGINT UNSIGNED NOT NULL,
    recipient_id BIGINT UNSIGNED NOT NULL,
    source_revision INT NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'pending',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_two_factor_codes (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hc_portal_trusted_devices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    UNIQUE KEY hc_portal_trusted_token (token_hash),
    KEY hc_portal_trusted_user (user_id, expires_at),
    FOREIGN KEY (user_id) REFERENCES hc_portal_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
