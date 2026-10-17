"""HTTP serialization that preserves exact decimal values."""

from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def wire(value):
    return JSONResponse(jsonable_encoder(value, custom_encoder={Decimal: lambda d: format(d, "f")}))
