# PS_SCANNER_V645_GROWW_GUARD_INIT
try:
    from . import groww_guard as _ps_v645_groww_guard
    _ps_v645_groww_guard.install()
except Exception:
    _ps_v645_groww_guard = None

