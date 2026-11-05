"""proxy2model — turn captured proxy traffic into an evidence-backed web-app model."""
__version__ = "2.1.0"

import os as _os

# the tool was called burp2model: its environment variables keep working
for _k, _v in list(_os.environ.items()):
    if _k.startswith("BURP2MODEL_"):
        _os.environ.setdefault("PROXY2MODEL_" + _k[len("BURP2MODEL_"):], _v)

from .ingest.parse import parse_items, Exchange          # noqa: F401
from .core.model import build, to_dict, from_dict, cross_role, Model  # noqa: F401
from .core.context import query, context_package       # noqa: F401
from .core.graph import ReasonGraph, reason_graph, to_graphml, to_cypher, to_graph_json  # noqa: F401
from .core.methodology import investigation_plan, methodology_package, rank_gaps  # noqa: F401
from .core.changes import diff_models  # noqa: F401
from .report.animate import render_terminal, render_svg  # noqa: F401
from .core.domains import registrable_domain, public_suffix  # noqa: F401
from .recon import osint  # noqa: F401
