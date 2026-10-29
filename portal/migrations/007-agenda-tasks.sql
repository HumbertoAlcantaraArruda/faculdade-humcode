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
    notify_on DATE NULL,
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_task_day (user_id, task_date),
    KEY hc_portal_task_event (event_id),
    KEY hc_portal_task_due (user_id, notify_on),
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
