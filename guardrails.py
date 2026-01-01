from typing import Type, TypeVar, Any
from pydantic import BaseModel, ValidationError
import re

T = TypeVar("T", bound=BaseModel)

INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"system\s+prompt",
    r"developer\s+message",
    r"reveal\s+chain\s+of\s+thought",
]

def basic_input_guardrails(text: str) -> None:
    lowered = text.lower()
    for p in INJECTION_PATTERNS:
        if re.search(p, lowered):
            raise ValueError(
                "Potential prompt-injection detected. "
                "Please remove instruction-like text from the email and resend."
            )

def safe_parse(model: Type[T], data: Any) -> T:
    if isinstance(data, model):
        return data
    return model.model_validate(data)

def validate_or_raise(model: Type[T], data: Any) -> T:
    try:
        return safe_parse(model, data)
    except ValidationError as e:
        raise ValueError(f"Output validation failed: {e}")

def clamp_confidence(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    return max(0.0, min(1.0, v))
