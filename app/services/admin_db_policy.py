from __future__ import annotations

import os
import re

# Palabras clave DML/DDL que no deben aparecer en modo solo lectura.
_DML_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|grant|revoke|copy|call|do)\b",
    re.IGNORECASE,
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_admin_db_policy():
    read_only = _env_flag("ADMIN_DB_READ_ONLY", default=True)
    allow_raw_sql = _env_flag("ADMIN_DB_ALLOW_RAW_SQL", default=False)
    return {
        "read_only": read_only,
        "allow_raw_sql": allow_raw_sql,
        "mode_label": "solo lectura" if read_only else "edición habilitada",
    }


def ensure_admin_db_write_allowed():
    policy = get_admin_db_policy()
    if policy["read_only"]:
        raise PermissionError("El modo lectura del panel impide modificar tablas desde /admin/db.")
    return policy


def validate_admin_sql(sql: str):
    policy = get_admin_db_policy()
    if not policy["allow_raw_sql"]:
        raise PermissionError("La consola SQL está desactivada. Activa ADMIN_DB_ALLOW_RAW_SQL=1 para usarla.")
    normalized = (sql or "").strip()
    if not normalized:
        raise ValueError("SQL vacío")
    if policy["read_only"]:
        head = normalized.lstrip("(").casefold()
        if not (head.startswith("select") or head.startswith("with") or head.startswith("explain")):
            raise PermissionError(
                "La consola SQL está en modo solo lectura. Solo se permiten SELECT, WITH o EXPLAIN."
            )
        # Evita el bypass via CTEs que modifican datos (WITH ... DELETE/INSERT/UPDATE ...)
        if _DML_PATTERN.search(normalized):
            raise PermissionError(
                "La consola SQL está en modo solo lectura. La consulta contiene operaciones de escritura no permitidas."
            )
    return policy
