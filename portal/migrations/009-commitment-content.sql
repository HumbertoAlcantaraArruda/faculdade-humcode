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
