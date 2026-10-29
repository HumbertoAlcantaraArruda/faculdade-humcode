CREATE TABLE IF NOT EXISTS hc_portal_notes (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
