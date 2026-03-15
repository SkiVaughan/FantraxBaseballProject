"""
Fantrax auth via hardcoded browser cookie string.
No Selenium required.
"""
from fantraxapi import api
from fantraxapi.api import Method

COOKIE_STRING = (
    "uig=17xz6q73mmpgwxum; "
    "FX_RM=_qpxzCwQSEA4ZEx4JAxNSA1BaVkBcEwZVFRwIBxoVGlVQUAE=; "
    "ui=llvveuyilqvf1ci0; "
    "__cf_bm=jktQi65oHKnVdnwazQ1guvX4v.iOAaotkS_yLzzGgpw-1773460593-1.0.1.1-e8AypqE3YJmw.1Q6F2ZozbeliGwo7R0TyUN_vwyuRA0A5P7iyau7cVAxf..5ebHqtBfj.6wyB0cDkcphD_FcPIJg31vMHjU2jW_CSfGnEM0; "
    "cf_clearance=VQTKhBYAEV1w5D.lveprnxj84sjr6sO3mrBgtzz5rEI-1773452671-1.2.1.1-TVsTk5Hd0HTyhP142PeVjntbCIUmiGoFvRnLtgwS4ZToELY2a1vn0sLZ7HQc9.6s7kgpyTaVJsMYq6Gsld4gwfyhqOppwmGYGb8R1bYu0lgGrs0.ixLRBKz35U5DKvPczC8lPk_nIU1VvJf9yTzxdITylb_YRpRVrLyANf0CrvPAI9hOCnm2H_R7_aSglVJltqwZ8DdBEmiftujmoFR5m9A6ozB8GsUYyVoszKA5Vdg"
)

_old_request = api.request


def _new_request(league, methods):
    # Inject cookies into every request
    for pair in COOKIE_STRING.split("; "):
        if "=" in pair:
            name, _, value = pair.partition("=")
            league.session.cookies.set(name.strip(), value.strip())
    return _old_request(league, methods)


api.request = _new_request
