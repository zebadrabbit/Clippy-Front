-- Create help system tables manually
-- Run with: psql -h 10.8.0.1 -U clippy_user -d clippy_front -f scripts/create_help_tables.sql

CREATE TABLE IF NOT EXISTS dev_help_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_dev_help_categories_slug ON dev_help_categories(slug);

CREATE TABLE IF NOT EXISTS dev_help_sections (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES dev_help_categories(id),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    CONSTRAINT dev_uq_help_section_slug UNIQUE (category_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_dev_help_sections_slug ON dev_help_sections(slug);

CREATE TABLE IF NOT EXISTS dev_help_articles (
    id SERIAL PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES dev_help_sections(id),
    title VARCHAR(200) NOT NULL,
    slug VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    summary VARCHAR(500),
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    meta_description VARCHAR(160),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    published_at TIMESTAMP,
    author_id INTEGER REFERENCES dev_users(id),
    CONSTRAINT dev_uq_help_article_slug UNIQUE (section_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_dev_help_articles_slug ON dev_help_articles(slug);
