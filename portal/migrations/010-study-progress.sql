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
