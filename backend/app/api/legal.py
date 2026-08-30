"""
Licence and source disclosure.

AGPL-3.0 section 13 requires that anyone interacting with this software over a
network be offered its Corresponding Source, free of charge. A hosted
deployment that does not do this is in breach, so the offer is served by the
application itself rather than left to a README nobody reads.

Public and unauthenticated on purpose: the obligation is to every user, not to
paying ones.
"""

import os
import subprocess

from flask import jsonify

from . import legal_bp
from ..utils.logger import get_logger

logger = get_logger('spidernet.api.legal')

UPSTREAM_URL = "https://github.com/666ghj/MiroFish"
DEFAULT_SOURCE_URL = "https://github.com/BiGSaSsY420/SpiderNet-"


def _revision() -> str:
    """
    The exact commit being run, so the offer points at *this* version.

    Baked in at build time where possible; falls back to asking git, which
    works in development and not in a container built from a tarball.
    """
    for var in ("SPIDERNET_REVISION", "GIT_COMMIT", "SOURCE_COMMIT"):
        value = os.environ.get(var)
        if value:
            return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
    except Exception:
        return "unknown"


@legal_bp.route('/source', methods=['GET'])
def source():
    """Where to get the source of the version you are talking to."""
    source_url = os.environ.get("SOURCE_URL", DEFAULT_SOURCE_URL)
    revision = _revision()

    return jsonify({
        "success": True,
        "data": {
            "licence": "AGPL-3.0-or-later",
            "source_url": source_url,
            "revision": revision,
            "revision_url": (
                f"{source_url.rstrip('/')}/tree/{revision}"
                if revision != "unknown" else source_url
            ),
            "upstream_url": UPSTREAM_URL,
            "notice": (
                "SpiderNet is a modified version of MiroFish, distributed under "
                "the AGPL-3.0. You are entitled to the complete source of the "
                "version running here, including local modifications, at no "
                "charge."
            ),
        },
    })
