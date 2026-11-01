"""Pure in-memory pipe geometry calculations."""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from gemini import ops, units
from gemini.errors import PhysicsError


@ops.physics
def circle_area(diameter: float) -> float:
    """Return the area [m2] of a circle, ``A = pi * d**2 / 4``.

    Parameters
    ----------
    diameter : float
        Circle diameter [m]; the flow cross-section of a pipe is its internal diameter.

    Returns
    -------
    float
        Area [m2].

    Notes
    -----
    Valid for any real diameter; the area of a diameter of zero is zero. Reference: the
    elementary area of a circle, as in any geometry text.
    """
    return math.pi * diameter**2 / 4


@ops.physics
def lateral_area(diameter: float, length: float) -> float:
    """Return the lateral area [m2] of a cylinder, ``A = pi d L``.

    Parameters
    ----------
    diameter, length : float
        Cylinder diameter and length [m]; the inner wall of a pipe uses its internal diameter.

    Returns
    -------
    float
        Wall area [m2].

    Notes
    -----
    Valid for any real inputs. Reference: the elementary lateral area of a cylinder.
    """
    return math.pi * diameter * length


@ops.physics
def mean_velocity(mass_flow: float, density: float, diameter: float) -> float:
    """Return the mean velocity [m/s] of a flow through a circular section, ``m / rho / A``.

    Parameters
    ----------
    mass_flow : float
        Signed mass flow [kg/s]; the velocity takes its sign.
    density : float
        Fluid density [kg/m3], nonzero.
    diameter : float
        Internal diameter of the section [m], nonzero.

    Returns
    -------
    float
        Mean velocity [m/s] over ``circle_area(diameter)``.

    Notes
    -----
    Continuity for a uniform velocity profile, ``m = rho u A``. For a phase of a mixture pass
    the flow and the density of that phase to get its superficial velocity. Reference: the
    continuity equation, e.g. White, Fluid Mechanics, 8th ed., section 3.3.
    """
    return mass_flow / density / circle_area(diameter)


VERTICAL = math.pi / 2
"""The inclination of a vertical well [rad]."""


class PipeSection(BaseModel):
    """A constant-diameter pipe interval, ordered from surface to bottom."""

    model_config = ConfigDict(frozen=True)
    length: float = Field(
        ...,
        ge=0,
        description="Measured interval length [m]",
        json_schema_extra={"quantity": "length", "unit": "m"},
    )
    inclination: float = Field(
        ...,
        ge=-math.pi / 2,
        le=math.pi / 2,
        description="Inclination [rad]",
        json_schema_extra={"quantity": "angle", "unit": "rad"},
    )
    inner_diameter: float = Field(
        ...,
        gt=0,
        description="Internal diameter [m]",
        json_schema_extra={"quantity": "length", "unit": "m"},
    )
    roughness: float = Field(
        ...,
        ge=0,
        description="Absolute roughness [m]",
        json_schema_extra={"quantity": "length", "unit": "m"},
    )


class PipePath(BaseModel):
    """Ordered pipe sections in increasing measured depth."""

    sections: list[PipeSection] = Field(default_factory=list, description="Pipe intervals [-]")

    @property
    def total_length(self) -> float:
        """Return measured path length [m]."""
        return sum(s.length for s in self.sections)

    def index_at_measured_depth(self, md: float) -> int:
        """Return the interval containing depth [m], choosing the deeper interval at a joint."""
        if not 0 <= md <= self.total_length or not self.sections:
            raise PhysicsError(
                f"PipePath: measured depth = {md} m; expected a depth in [0, {self.total_length}]"
            )
        depth = 0.0
        for i, section in enumerate(self.sections):
            depth += section.length
            if md < depth:
                return i
        return len(self.sections) - 1


def path_of(lengths, inclinations, diameters, roughnesses) -> PipePath:
    """Return the validated path of sections given by parallel lists, surface to bottom [m, rad]."""
    return PipePath(sections=[
        PipeSection(length=length, inclination=angle, inner_diameter=diameter, roughness=rough)
        for length, angle, diameter, rough in zip(lengths, inclinations, diameters, roughnesses)
    ])


def section_values(path) -> dict:
    """Return the section lists of a well, ``section_<field>`` of each parameter, from a path."""
    return {
        "section_length": [section.length for section in path.sections],
        "section_inclination": [section.inclination for section in path.sections],
        "section_diameter": [section.inner_diameter for section in path.sections],
        "section_roughness": [section.roughness for section in path.sections],
    }


def path_between(lengths, inclinations, diameters, roughnesses, start_md, end_md) -> PipePath:
    """Return the sections cut to the interval between two measured depths [m], in either order.

    Every section is kept, with the length of its overlap with the interval (zero outside it), so
    the path has the shape of the whole one whatever the depths, and the lengths, depths and the
    other values may all be traced numbers. A depth outside the path raises ``PhysicsError``; the
    sections are not validated models, because their values may be traced.
    """
    low, high = ops.minimum(start_md, end_md), ops.maximum(start_md, end_md)
    total = sum(lengths)
    ops.check(
        ops.logical_and(low >= 0, high <= total),
        PhysicsError,
        "PipePath: depth interval = [{low}, {high}] m; expected an interval inside [0, {total}]",
        low=low,
        high=high,
        total=total,
    )
    sections, depth = [], 0.0
    for length, angle, diameter, rough in zip(lengths, inclinations, diameters, roughnesses):
        end = depth + length
        overlap = ops.maximum(ops.minimum(high, end) - ops.maximum(low, depth), 0.0)
        sections.append(
            PipeSection.model_construct(
                length=overlap, inclination=angle, inner_diameter=diameter, roughness=rough
            )
        )
        depth = end
    return PipePath.model_construct(sections=sections)


def vertical_path(depth: float, diameter: float, roughness: float) -> PipePath:
    """Return the vertical pipe path of a well: one section from the surface to ``depth``.

    Parameters
    ----------
    depth : float
        Well depth [m], nonnegative.
    diameter : float
        Internal diameter [m], positive.
    roughness : float
        Absolute roughness [m], nonnegative.

    Returns
    -------
    PipePath
        One section at the inclination of a vertical well, ``pi / 2``.

    Notes
    -----
    Validity: Any vertical well of one diameter.
    Source: Geometry; no published source is needed.
    """
    section = PipeSection(
        length=depth, inclination=VERTICAL, inner_diameter=diameter, roughness=roughness
    )
    return PipePath(sections=[section])


def build_path(trajectory_table: list[dict], tally_table: list[dict] | None = None) -> PipePath:
    """Build a path from SI trajectory and optional SI tally intervals.

    Parameters
    ----------
    trajectory_table : list of dict
        MD, TVD, ID and roughness [m]. Endpoint geometry applies to the preceding interval.
    tally_table : list of dict, optional
        TopMD, BottomMD, ID and roughness [m]. Tally diameters override trajectory geometry.

    Returns
    -------
    PipePath
        Sections retaining WIMS' inclination rounding to 0.01 degree.

    Notes
    -----
    Valid for a trajectory of at least two points with increasing MD and
    ``|delta TVD| <= delta MD``; a violation raises ``PhysicsError``. The value tests
    validate plain configuration numbers at build time, so the function is not
    ``@ops.physics``. Reference: GEMINI WIMS build_trajectory_geometry, extended with SI tally
    interval intersections; the angle is the elementary relation of a straight interval.
    Inclination follows sin(angle) = delta_TVD / delta_MD and is
    rounded to 0.01 degree, as in WIMS, so paths match the original section angles.

    NOTE(refactor): example roughness 2e-5 is metres, despite DPDT's old mm comment.
    """
    if not trajectory_table or len(trajectory_table) < 2:
        raise PhysicsError(
            f"build_path: trajectory points = {len(trajectory_table or [])}; expected at least 2"
        )
    sections = []
    for index, (first, last) in enumerate(zip(trajectory_table, trajectory_table[1:]), 1):
        length = last["MD"] - first["MD"]
        vertical = last["TVD"] - first["TVD"]
        if length <= 0 or abs(vertical) > length:
            raise PhysicsError(
                f"build_path: trajectory row {index}: delta MD = {length} m, delta TVD = "
                f"{vertical} m; expected increasing MD and |delta TVD| <= delta MD"
            )
        angle = units.deg_to_rad(np.round(90 - units.rad_to_deg(np.arccos(vertical / length)), 2))
        sections.extend(_interval_sections(first, last, angle, tally_table or []))
    return PipePath(sections=sections)


def _interval_sections(first, last, angle, tally_table):
    """Split one trajectory interval at the tally joints inside it.

    Each piece takes the tally geometry covering its midpoint, otherwise the geometry of the
    interval's end point.
    """
    cuts = {first["MD"], last["MD"]}
    for row in tally_table:
        cuts.update(d for d in (row["TopMD"], row["BottomMD"]) if first["MD"] < d < last["MD"])
    cuts = sorted(cuts)
    sections = []
    for low, high in zip(cuts, cuts[1:]):
        tally = next((r for r in tally_table if r["TopMD"] <= (low + high) / 2 < r["BottomMD"]), {})
        sections.append(
            PipeSection(
                length=high - low,
                inclination=angle,
                inner_diameter=tally.get("ID", last["ID"]),
                roughness=tally.get("roughness", last["roughness"]),
            )
        )
    return sections
