"""Single source of truth for the local timezone constant.

`LOCAL_TZ` lives here (UTC+8, Taiwan). It is also re-exported from
`blackswan._sleep` for backward compatibility — existing call sites that
import `from blackswan._sleep import LOCAL_TZ` keep working unchanged.

New code should import from this module:

    from blackswan._time import LOCAL_TZ

This split exists so that strength modules (which have nothing to do with
sleep) do not pull `_sleep`'s sleep-staging helpers transitively.
"""

from __future__ import annotations

from datetime import timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=8))
