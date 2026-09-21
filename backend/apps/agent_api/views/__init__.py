"""Domain-oriented DRF view exports.

Import views from their domain module in new code. These exports preserve the
existing public import path while the application is progressively decomposed.
"""

from .agent import *
from .auth import *
from .blog import *
from .governance import *
from .knowledge import *
