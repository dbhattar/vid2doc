"""Runtime overrides for the settings in tunables.py, stored in the database
(app_settings, key "setting:<NAME>") so an admin can tune them from the admin
Settings page without touching environment variables.

config.Settings resolves every tunable name through get() below, so existing
`settings.X` call sites pick overrides up with no changes. Overrides are read
from the DB at most every _TTL_SECONDS per process (api, worker and each job
subprocess keep their own copy), so a change takes effect everywhere within
about that long -- immediately in the process that made it. If the database
can't be read, the last known values (or the env defaults) keep being used:
a config lookup must never break a request or a job."""

import logging
import threading
import time
from datetime import datetime, timezone

from . import tunables

logger = logging.getLogger(__name__)

_TTL_SECONDS = 10.0
_KEY_PREFIX = "setting:"

_lock = threading.Lock()
_cache: dict[str, object] | None = None
_loaded_at = 0.0


def _load() -> dict[str, object]:
    from .db import get_session
    from .models import AppSetting

    session = get_session()
    try:
        # Only key/value: those columns exist even before the audit-columns
        # migration has run.
        rows = session.query(AppSetting.key, AppSetting.value).filter(AppSetting.key.like(f"{_KEY_PREFIX}%")).all()
    finally:
        session.close()
    values: dict[str, object] = {}
    for key, raw in rows:
        param = tunables.BY_NAME.get(key[len(_KEY_PREFIX):])
        if param is None:
            continue
        try:
            values[param.name] = tunables.deserialize(param, raw)
        except tunables.InvalidValue:
            # Stored value no longer fits (bounds tightened, hand-edited row):
            # fall back to the default rather than apply something unvalidated.
            logger.warning("Ignoring invalid stored value for %s: %r", param.name, raw)
    return values


def _overrides() -> dict[str, object]:
    global _cache, _loaded_at
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _loaded_at < _TTL_SECONDS:
            return _cache
    try:
        fresh = _load()
    except Exception:
        logger.exception("Couldn't read runtime settings; using the last known values")
        with _lock:
            _loaded_at = now  # back off for a TTL instead of retrying every access
            return _cache if _cache is not None else {}
    with _lock:
        _cache, _loaded_at = fresh, now
    return fresh


def _invalidate() -> None:
    global _loaded_at
    with _lock:
        _loaded_at = 0.0


def get(name: str, default):
    """The admin-set value for `name`, else `default` (the env/code value)."""
    value = _overrides().get(name)
    return default if value is None else value


# --- admin page -------------------------------------------------------------


def describe() -> list[dict]:
    """Every tunable with its effective value, the env default, and who last
    changed it -- read fresh (not from the cache) so the page is never stale."""
    from .config import settings
    from .db import get_session
    from .models import AppSetting, User

    session = get_session()
    try:
        rows = (
            session.query(AppSetting, User.email)
            .outerjoin(User, AppSetting.updated_by == User.id)
            .filter(AppSetting.key.like(f"{_KEY_PREFIX}%"))
            .all()
        )
    finally:
        session.close()
    stored = {row.key[len(_KEY_PREFIX):]: (row, email) for row, email in rows}

    out = []
    for param in tunables.PARAMS:
        default = object.__getattribute__(settings, param.name)
        value, overridden, updated_at, updated_by = default, False, None, None
        if param.name in stored:
            row, email = stored[param.name]
            try:
                value = tunables.deserialize(param, row.value)
                overridden = True
            except tunables.InvalidValue:
                pass
            updated_at, updated_by = row.updated_at, email
        out.append(
            {
                "name": param.name,
                "group": param.group,
                "label": param.label,
                "description": param.description,
                "type": param.type,
                "min": param.min,
                "max": param.max,
                "choices": list(param.choices),
                "max_length": param.max_length,
                "unit": param.unit,
                "value": value,
                "default": default,
                "overridden": overridden,
                "updated_at": updated_at,
                "updated_by": updated_by,
            }
        )
    return out


def set_value(name: str, value, user_id: str) -> None:
    """Validates and stores an override. Raises KeyError for an unknown name
    and tunables.InvalidValue for a bad value."""
    from .db import get_session
    from .models import AppSetting

    param = tunables.BY_NAME[name]
    clean = tunables.validate(param, value)
    session = get_session()
    try:
        row = session.get(AppSetting, _KEY_PREFIX + name)
        now = datetime.now(timezone.utc)
        if row:
            row.value, row.updated_at, row.updated_by = tunables.serialize(param, clean), now, user_id
        else:
            session.add(
                AppSetting(key=_KEY_PREFIX + name, value=tunables.serialize(param, clean), updated_at=now, updated_by=user_id)
            )
        session.commit()
    finally:
        session.close()
    logger.info("Setting %s changed to %r by user %s", name, clean, user_id)
    _invalidate()


def reset(name: str, user_id: str) -> None:
    """Drops the override so the env/code default applies again."""
    from .db import get_session
    from .models import AppSetting

    tunables.BY_NAME[name]
    session = get_session()
    try:
        row = session.get(AppSetting, _KEY_PREFIX + name)
        if row:
            session.delete(row)
            session.commit()
    finally:
        session.close()
    logger.info("Setting %s reset to default by user %s", name, user_id)
    _invalidate()
