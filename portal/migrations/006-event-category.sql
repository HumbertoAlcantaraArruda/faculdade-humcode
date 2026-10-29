-- Eventos anteriores permanecem sem categoria. Novos cadastros e edições
-- exigem uma das sete categorias educacionais na validação da aplicação.
ALTER TABLE hc_portal_events ADD COLUMN category VARCHAR(32) NULL DEFAULT NULL;
