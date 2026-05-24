-- Enable UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pg_trgm for fast LIKE/ILIKE queries
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Enable unaccent for better text search
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Seed default prompt templates (used by AI engine on first run)
-- These are inserted at DB init time so the system works before any user action.

-- Note: The application tables are created by Alembic migrations.
-- This file only sets up extensions and seeds static reference data.

-- The actual table inserts below run AFTER Alembic creates the schema.
-- Wrap in DO block to handle the case where tables don't exist yet.
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'prompt_templates'
  ) THEN
    INSERT INTO prompt_templates (id, name, category, template, version, is_active, usage_count)
    VALUES
      (
        uuid_generate_v4(),
        'nl_to_sql',
        'sql_gen',
        'Convert the following natural language question to SQL: $question\n\nSchema: $schema',
        '2.1.0',
        true,
        0
      ),
      (
        uuid_generate_v4(),
        'data_summary',
        'summary',
        'Summarize the following dataset: $dataset_name with $row_count rows',
        '1.2.0',
        true,
        0
      )
    ON CONFLICT (name) DO NOTHING;
  END IF;
END $$;
