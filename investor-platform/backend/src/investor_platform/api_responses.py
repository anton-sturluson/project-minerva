"""HTTP serialization that preserves exact decimal values."""

from collections.abc import Mapping
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def decimal_json_response(value: Mapping[str, object]) -> JSONResponse:
    """Encode report fields with decimal strings instead of lossy JSON numbers."""
    return JSONResponse(jsonable_encoder(value, custom_encoder={Decimal: lambda d: format(d, "f")}))
