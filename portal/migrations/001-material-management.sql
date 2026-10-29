ALTER TABLE hc_portal_files
    ADD COLUMN legacy_path VARCHAR(512) NULL,
    ADD COLUMN deleted_at TIMESTAMP NULL DEFAULT NULL,
    ADD COLUMN revision INT NOT NULL DEFAULT 1,
    ADD UNIQUE KEY hc_portal_legacy_path (legacy_path);

UPDATE hc_portal_files SET legacy_path = stored_path WHERE source = 'legacy' AND legacy_path IS NULL;
