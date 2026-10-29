-- Vídeo aulas do YouTube por matéria. Somente cria uma tabela nova; nenhum registro existente é alterado.
-- portal/bin/migrate.php aplica esta definição de forma idempotente.
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
