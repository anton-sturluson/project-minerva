CREATE TABLE {schema}.companies (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    issuer_key text NOT NULL UNIQUE,
    name text NOT NULL
);
CREATE TABLE {schema}.periods (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES {schema}.companies,
    fiscal_year integer NOT NULL,
    fiscal_label text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    UNIQUE (company_id, period_start, period_end)
);
CREATE TABLE {schema}.metrics (
    metric_key text PRIMARY KEY,
    unit text NOT NULL,
    entity_scope text NOT NULL,
    measurement_basis text NOT NULL
);
CREATE TABLE {schema}.sources (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id bigint NOT NULL REFERENCES {schema}.companies,
    document_id text NOT NULL,
    url text NOT NULL,
    published_on date NOT NULL,
    retrieved_at timestamptz NOT NULL,
    content_sha256 text NOT NULL,
    UNIQUE (company_id, document_id, content_sha256, retrieved_at)
);
CREATE TABLE {schema}.publications (
    bundle_id uuid PRIMARY KEY,
    period_id bigint NOT NULL REFERENCES {schema}.periods,
    bundle_sha256 text NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('candidate','reviewed')),
    imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    issuer jsonb NOT NULL,
    capital_spending jsonb,
    CHECK (length(bundle_sha256) = 64)
);
CREATE TABLE {schema}.publication_sources (
    bundle_id uuid NOT NULL REFERENCES {schema}.publications,
    source_id text NOT NULL,
    document_source_id bigint NOT NULL REFERENCES {schema}.sources,
    PRIMARY KEY (bundle_id, source_id)
);
CREATE TABLE {schema}.observations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bundle_id uuid NOT NULL REFERENCES {schema}.publications,
    metric_key text NOT NULL REFERENCES {schema}.metrics,
    value numeric CHECK (value::text NOT IN ('NaN','Infinity','-Infinity')),
    status text NOT NULL CHECK
        (status IN ('reported','not_disclosed','not_applicable','unavailable')),
    source_id text,
    locator jsonb,
    reason text,
    share_basis jsonb,
    UNIQUE (bundle_id, metric_key),
    FOREIGN KEY (bundle_id, source_id) REFERENCES {schema}.publication_sources,
    CHECK ((status = 'reported' AND value IS NOT NULL AND source_id IS NOT NULL
        AND locator IS NOT NULL) OR (status != 'reported' AND value IS NULL AND reason IS NOT NULL))
);
CREATE INDEX latest_publication ON {schema}.publications (period_id, imported_at DESC);
CREATE FUNCTION {schema}.reject_observation_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Financial evidence is append-only; import a new publication UUID';
END;
$$;
CREATE TRIGGER immutable_publications BEFORE UPDATE OR DELETE ON {schema}.publications
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_observations BEFORE UPDATE OR DELETE ON {schema}.observations
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_sources BEFORE UPDATE OR DELETE ON {schema}.sources
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_publication_sources BEFORE UPDATE OR DELETE ON {schema}.publication_sources
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_metrics BEFORE UPDATE OR DELETE ON {schema}.metrics
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_periods BEFORE UPDATE OR DELETE ON {schema}.periods
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
CREATE TRIGGER immutable_companies BEFORE UPDATE OR DELETE ON {schema}.companies
FOR EACH ROW EXECUTE FUNCTION {schema}.reject_observation_change();
