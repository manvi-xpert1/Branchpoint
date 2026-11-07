"""Decision layer: objectives, constraints, scoring, Pareto sets, sensitivity and insights.

Works on the output of any domain (its metrics and catalog), never on one
domain's internals. Pure Python: no database or web framework.
"""

from .evaluate import Evaluation, Future, FutureEvaluation, evaluate, pareto_front
from .insights import Insight, insights
from .model import Constraint, DecisionModel, Objective, default_model
from .sensitivity import SensitivityResult, find_inputs, sensitivity

__all__ = [
    "Constraint", "DecisionModel", "Evaluation", "Future", "FutureEvaluation", "Insight", "Objective",
    "SensitivityResult", "default_model", "evaluate", "find_inputs", "insights", "pareto_front", "sensitivity",
]
