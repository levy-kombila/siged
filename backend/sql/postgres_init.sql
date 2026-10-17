-- Objets spécifiques PostgreSQL, appliqués au démarrage (idempotent).

-- 1) Recherche plein texte (français) sur le texte extrait / OCR
CREATE INDEX IF NOT EXISTS ix_versions_fts
    ON document_versions USING GIN (to_tsvector('french', coalesce(extracted_text, '')));

-- 2) Recherche floue sur le titre et l'auteur (trigrammes)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS ix_documents_title_trgm ON documents USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_documents_author_trgm ON documents USING GIN (author gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_metadata_kv ON document_metadata (meta_key, meta_value);

-- 3) Journal d'audit inaltérable : aucune modification ni suppression possible
CREATE OR REPLACE FUNCTION siged_audit_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs est en ajout seul (ISO 15489) : % interdit', TG_OP;
END;
$$ LANGUAGE plpgsql;

-- Création seulement si absents : aucun verrou exclusif lors des démarrages suivants
-- (important en serverless, où chaque nouvelle instance exécute ce script).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_no_update') THEN
        CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION siged_audit_immutable();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_no_truncate') THEN
        CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_logs
            FOR EACH STATEMENT EXECUTE FUNCTION siged_audit_immutable();
    END IF;
END
$$;

-- 4) Recommandation production : l'application se connecte avec un rôle
--    qui n'a que INSERT/SELECT sur audit_logs :
--    REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM siged_app;

-- 5) Évolutions GEDarchive sur une base existante (create_all n'ajoute pas de colonnes)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS valid_until DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS shelf_location_id INTEGER REFERENCES shelf_locations(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS physical_ref VARCHAR(100) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_documents_valid_until ON documents (valid_until);
CREATE INDEX IF NOT EXISTS ix_documents_shelf_location_id ON documents (shelf_location_id);
