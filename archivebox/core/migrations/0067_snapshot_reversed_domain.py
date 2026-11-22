from django.db import migrations, models

from archivebox.core.domain_grouping import ReversedDomain, ReversedDomainField


def create_postgres_functions(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        r"""
        CREATE FUNCTION archivebox_reversed_domain(url text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
            WITH parsed AS (
                SELECT regexp_match(
                    translate(url, E'\t\r\n', '') COLLATE "C",
                    '^[\x01-\x20]*https?://(?:[^/?#]*@)?(\[[^]]+\]|[^/?#:@]+)(?::([0-9]*))?(?:[/?#]|$)',
                    'i'
                ) AS parts
            ), normalized AS (
                SELECT rtrim(lower(translate(
                    parts[1], 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'
                ) COLLATE "default"), '.') AS host,
                CASE
                    WHEN parts[2] IS NULL OR parts[2] = '' THEN NULL
                    WHEN length(ltrim(parts[2], '0')) <= 5
                        THEN coalesce(nullif(ltrim(parts[2], '0'), ''), '0')::integer
                    ELSE 65536
                END AS port
                FROM parsed
            )
            SELECT CASE WHEN host IS NULL OR host = '' OR port > 65535 THEN ''
                ELSE CASE WHEN port NOT IN (80, 443) THEN port::text || ':' ELSE '' END
                    || CASE WHEN left(host, 1) = '[' THEN host ELSE (
                        SELECT string_agg(label, '.' ORDER BY position DESC)
                        FROM unnest(string_to_array(host, '.')) WITH ORDINALITY AS labels(label, position)
                    ) END
                END
            FROM normalized
        $$
        """,
    )
    schema_editor.execute(
        """
        CREATE FUNCTION archivebox_domain_authority(domain_key text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
            SELECT CASE WHEN left(parts[2], 1) = '[' THEN parts[2] ELSE coalesce((
                SELECT string_agg(label, '.' ORDER BY position DESC)
                FROM unnest(string_to_array(parts[2], '.')) WITH ORDINALITY AS labels(label, position)
            ), '') END || coalesce(':' || parts[1], '')
            FROM regexp_match(domain_key, '^(?:([0-9]+):)?(.*)$') AS parts
        $$
        """,
    )


def drop_postgres_functions(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP FUNCTION archivebox_domain_authority(text)")
        schema_editor.execute("DROP FUNCTION archivebox_reversed_domain(text)")


class Migration(migrations.Migration):
    dependencies = [("core", "0066_remove_snapshot_public_page_idx")]

    # SQLite rebuilds the snapshot table once to populate the stored column.
    # Both backends derive it on URL writes without a separate backfill job.
    operations = [
        migrations.RunPython(create_postgres_functions, drop_postgres_functions),
        migrations.AddField(
            model_name="snapshot",
            name="reversed_domain",
            field=models.GeneratedField(
                expression=ReversedDomain("url"),
                output_field=ReversedDomainField(),
                db_persist=True,
            ),
        ),
        migrations.AddIndex(
            model_name="snapshot",
            index=models.Index(fields=["reversed_domain"], name="snapshot_reversed_domain_idx"),
        ),
    ]
