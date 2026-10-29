-- As colunas e índices são aplicados por metadados em migrate_portal().
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

-- hc_portal_events: recurrence_id, occurrence_date, recurrence_exception
-- UNIQUE (recurrence_id, occurrence_date), FK para hc_portal_recurrences
-- hc_portal_tasks: recurrence_id, occurrence_date, recurrence_exception, recurrence_slot
-- UNIQUE (recurrence_id, occurrence_date, recurrence_slot), mesma FK
