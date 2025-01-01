"""Custom JSON encoder encoding numpy objects and custom objects."""
from collections import OrderedDict
from dataclasses import asdict, is_dataclass
from json import JSONEncoder

# from bson import json_util
import numpy as np
from pydantic import BaseModel


class FileJSONEncoder(JSONEncoder):
    """
    Custom JSON encoder for encoding various data types
    """
    def default(self, o):
        # try bson encoding first
        # try:
        #     return json_util.default(o)
        # except TypeError:
        #     pass

        # Handle all NumPy scalar types
        if isinstance(o, np.generic):
            return o.item()

        if isinstance(o, np.ndarray):
            return o.tolist()

        if isinstance(o, BaseModel):
            return o.model_dump()

        if is_dataclass(o):
            return asdict(o, dict_factory=OrderedDict)

        # CAUTION: hard to de-serialize back into a set
        if isinstance(o, set):
            return list(o)

        return JSONEncoder.default(self, o)
