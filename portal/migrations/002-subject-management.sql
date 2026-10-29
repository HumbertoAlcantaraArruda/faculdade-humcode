-- Aplicar uma única vez antes de publicar a edição/exclusão de matérias.
-- Nenhum arquivo ou registro de material é excluído nesta migração.
ALTER TABLE hc_portal_subjects
    ADD COLUMN revision INT NOT NULL DEFAULT 1;

ALTER TABLE hc_portal_files
    MODIFY COLUMN subject_id BIGINT UNSIGNED NULL;
