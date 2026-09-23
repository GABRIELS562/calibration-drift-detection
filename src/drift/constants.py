"""Approval statuses and registry names shared by training and the gate."""

from typing import Final

MODEL_NAME: Final = "calibration-drift-classifier"
PENDING: Final = "pending-approval"
APPROVED: Final = "approved"
REJECTED: Final = "rejected"
ROLLED_BACK: Final = "rolled-back"
PRODUCTION_ALIAS: Final = "production"
