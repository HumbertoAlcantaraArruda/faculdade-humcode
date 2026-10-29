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
    revision INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY hc_portal_event_day (user_id, event_date),
    KEY hc_portal_event_due (user_id, notify_on),
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
