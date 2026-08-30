"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
account_bp = Blueprint('account', __name__)
crowd_bp = Blueprint('crowd', __name__)
calibration_bp = Blueprint('calibration', __name__)
admin_bp = Blueprint('admin', __name__)
legal_bp = Blueprint('legal', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import account  # noqa: E402, F401
from . import crowd  # noqa: E402, F401
from . import calibration  # noqa: E402, F401
from . import admin  # noqa: E402, F401
from . import legal  # noqa: E402, F401

