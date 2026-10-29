-- Referência documental. O migrador PHP verifica metadados antes de aplicar.
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
ALTER TABLE hc_portal_files ADD COLUMN folder_id BIGINT UNSIGNED NULL,
    ADD KEY hc_portal_file_folder (folder_id),
    ADD CONSTRAINT hc_portal_file_folder_fk FOREIGN KEY (folder_id) REFERENCES hc_portal_folders(id);
ALTER TABLE hc_portal_files ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'material';
