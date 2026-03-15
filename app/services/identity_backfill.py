_MEMBER_IDENTITY_CTE = """
WITH member_tokens AS (
    SELECT user_id, LOWER(LTRIM(BTRIM(username), '@')) AS token
    FROM club_members
    WHERE username IS NOT NULL AND BTRIM(username) <> ''
    UNION ALL
    SELECT user_id, LOWER(LTRIM(BTRIM(first_name), '@')) AS token
    FROM club_members
    WHERE first_name IS NOT NULL AND BTRIM(first_name) <> ''
    UNION ALL
    SELECT user_id, CAST(user_id AS TEXT) AS token
    FROM club_members
),
unique_tokens AS (
    SELECT token, MIN(user_id) AS user_id
    FROM member_tokens
    WHERE token IS NOT NULL AND token <> ''
    GROUP BY token
    HAVING COUNT(DISTINCT user_id) = 1
)
"""


def identity_token_expr(column_sql):
    return f"LOWER(LTRIM(BTRIM(COALESCE({column_sql}, '')), '@'))"


def backfill_identity_column(cur, *, table_name, name_column, user_id_column):
    token_expr = identity_token_expr(f"src.{name_column}")
    cur.execute(
        f"""
        {_MEMBER_IDENTITY_CTE}
        UPDATE {table_name} src
        SET {user_id_column} = matched.user_id
        FROM unique_tokens matched
        WHERE src.{user_id_column} IS NULL
          AND {token_expr} = matched.token
        """
    )
    return cur.rowcount or 0


def dedupe_and_backfill_identity_column(
    cur,
    *,
    table_name,
    name_column,
    user_id_column,
    partition_columns,
    order_by_sql,
):
    token_expr = identity_token_expr(f"src.{name_column}")
    effective_user_expr = f"COALESCE(src.{user_id_column}, matched.user_id)"
    partition_expr = ", ".join([f"src.{column}" for column in partition_columns] + [effective_user_expr])

    cur.execute(
        f"""
        {_MEMBER_IDENTITY_CTE},
        ranked AS (
            SELECT
                src.id AS row_id,
                {effective_user_expr} AS effective_user_id,
                ROW_NUMBER() OVER (
                    PARTITION BY {partition_expr}
                    ORDER BY
                        CASE WHEN src.{user_id_column} IS NOT NULL THEN 0 ELSE 1 END,
                        {order_by_sql}
                ) AS rn
            FROM {table_name} src
            LEFT JOIN unique_tokens matched
                ON src.{user_id_column} IS NULL
               AND {token_expr} = matched.token
            WHERE src.{user_id_column} IS NOT NULL
               OR matched.user_id IS NOT NULL
        )
        DELETE FROM {table_name} target
        USING ranked
        WHERE target.id = ranked.row_id
          AND ranked.effective_user_id IS NOT NULL
          AND ranked.rn > 1
        """
    )
    deleted = cur.rowcount or 0

    cur.execute(
        f"""
        {_MEMBER_IDENTITY_CTE}
        UPDATE {table_name} src
        SET {user_id_column} = matched.user_id
        FROM unique_tokens matched
        WHERE src.{user_id_column} IS NULL
          AND {token_expr} = matched.token
        """
    )
    updated = cur.rowcount or 0
    return {"updated": updated, "deleted": deleted}


def backfill_historical_user_identity(cur):
    summary = {
        "book_proposals_updated": backfill_identity_column(
            cur,
            table_name="book_proposals",
            name_column="proposed_by",
            user_id_column="proposed_by_user_id",
        ),
    }

    for table_name, name_column, partition_columns, order_by_sql in (
        ("book_votes", "user_name", ("proposal_id",), "src.created_at ASC, src.id ASC"),
        ("theme_votes", "user_name", ("theme_id",), "src.created_at ASC, src.id ASC"),
        ("meeting_attendance", "user_name", ("meeting_id",), "src.created_at ASC, src.id ASC"),
        ("book_ratings", "user_name", ("book_id",), "src.created_at DESC, src.id DESC"),
        ("reading_progress", "user_name", ("book_id",), "src.pages_read DESC, src.updated_at DESC, src.id DESC"),
    ):
        stats = dedupe_and_backfill_identity_column(
            cur,
            table_name=table_name,
            name_column=name_column,
            user_id_column="user_id",
            partition_columns=partition_columns,
            order_by_sql=order_by_sql,
        )
        summary[f"{table_name}_updated"] = stats["updated"]
        summary[f"{table_name}_deleted"] = stats["deleted"]

    return summary
