from pydantic import BaseModel, Field


class OwnershipReassign(BaseModel):
    """Register a tag re-wiring: from ``effective_from`` on, new samples belong
    to ``device_code``; earlier samples keep their original device."""

    device_code: str = Field(min_length=1, max_length=40)
    device_name: str = Field(default="", max_length=80)
    effective_from: str = Field(min_length=10, max_length=40)
    note: str = Field(default="", max_length=200)
