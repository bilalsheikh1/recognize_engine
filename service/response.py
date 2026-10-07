from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class ServiceResponse:
    success: bool
    message: str
    data: Optional[Any] = None
    errors: Optional[Any] = None
    status_code: int = 200

    def to_dict(self):
        return {"success": self.success, "message": self.message,
                "data": self.data, "errors": self.errors}

def success(message="OK", data=None, status_code=200):
    return ServiceResponse(True, message, data, None, status_code)

def failure(message="Failed", errors=None, status_code=400):
    return ServiceResponse(False, message, None, errors, status_code)