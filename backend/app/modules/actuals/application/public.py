"""actuals' public API. Other modules import actuals only from here.

Story 10.1: the Actuals tab (`get_actuals`), **Save Actuals** (`save_actuals`), corrections
(`correct_actual`) and **Close delivery** (`close_delivery`).

Story 10.3: the variance rule (`variance`, `Variance`, `VarianceDirection`) and the cause
labels, so Reports compute variance exactly as the Actuals tab does."""

from app.modules.actuals.application.deliveries import close_delivery
from app.modules.actuals.application.models import (
    ActualCorrection,
    ActualFields,
    ActualInput,
    ActualsSave,
    ActualsView,
    ActualView,
    SavedActuals,
)
from app.modules.actuals.application.record import correct_actual, save_actuals
from app.modules.actuals.application.view import get_actuals
from app.modules.actuals.domain.actuals import (
    CAUSE_LABELS,
    MINUS,
    ActualKind,
    Variance,
    VarianceCause,
    VarianceDirection,
    variance,
)

__all__ = [
    "CAUSE_LABELS",
    "MINUS",
    "ActualCorrection",
    "ActualFields",
    "ActualInput",
    "ActualKind",
    "ActualView",
    "ActualsSave",
    "ActualsView",
    "SavedActuals",
    "Variance",
    "VarianceCause",
    "VarianceDirection",
    "close_delivery",
    "correct_actual",
    "get_actuals",
    "save_actuals",
    "variance",
]
