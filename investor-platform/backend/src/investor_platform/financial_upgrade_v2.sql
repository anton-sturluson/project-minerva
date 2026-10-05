DROP VIEW {schema}.metric_values_flat;
ALTER TABLE {schema}.companies DROP CONSTRAINT companies_ticker_key;
ALTER TABLE {schema}.metrics
    ADD COLUMN unit_convention text CHECK (unit_convention IN
        ('base_currency','base_currency_per_share','fraction','ratio','count','days','multiple','defined_unit')),
    ADD COLUMN entity_scope text CHECK (length(trim(entity_scope)) > 0);
DROP INDEX {schema}.fiscal_identity;
ALTER TABLE {schema}.company_periods
    DROP CONSTRAINT company_periods_company_id_period_kind_period_end_key,
    ADD CONSTRAINT period_identity UNIQUE NULLS NOT DISTINCT
        (company_id, period_kind, period_start, period_end);
ALTER TABLE {schema}.sources
    DROP CONSTRAINT sources_reference_key,
    ADD COLUMN company_id bigint REFERENCES {schema}.companies(id);
