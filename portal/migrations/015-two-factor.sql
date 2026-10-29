ALTER TABLE hc_portal_users ADD COLUMN two_factor_enabled TINYINT NOT NULL DEFAULT 0;

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
