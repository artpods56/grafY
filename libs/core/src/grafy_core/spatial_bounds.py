"""WGS84 bounds aliases and the shared validated-bounds helper."""

import math
from typing import Annotated

from pydantic import Field

type GeoBounds = tuple[float, float, float, float]

Bounds = Annotated[
    tuple[
        Annotated[
            float,
            Field(
                title="West longitude",
                json_schema_extra={"minimum": -180.0, "maximum": 180.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="South latitude",
                json_schema_extra={"minimum": -90.0, "maximum": 90.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="East longitude",
                json_schema_extra={"minimum": -180.0, "maximum": 180.0},
            ),
        ],
        Annotated[
            float,
            Field(
                title="North latitude",
                json_schema_extra={"minimum": -90.0, "maximum": 90.0},
            ),
        ],
    ],
    Field(
        description=(
            "WGS84 bounds ordered as west longitude, south latitude, east "
            "longitude, north latitude."
        )
    ),
]


def validated_bounds(value: Bounds | None, *, field_name: str) -> Bounds | None:
    if value is None:
        return None
    if not all(math.isfinite(coordinate) for coordinate in value):
        raise ValueError(f"{field_name} coordinates must be finite")
    west, south, east, north = value
    if not -180 <= west <= 180 or not -180 <= east <= 180:
        raise ValueError(f"{field_name} longitudes must be within [-180, 180]")
    if not -90 <= south <= 90 or not -90 <= north <= 90:
        raise ValueError(f"{field_name} latitudes must be within [-90, 90]")
    if west > east or south > north:
        raise ValueError(f"{field_name} must be ordered west, south, east, north")
    return value
