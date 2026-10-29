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
