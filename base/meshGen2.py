#!/usr/bin/env python3
"""Production structured/swept mesh generator for all AJP CFD cases.

The former unstructured generator is retained in the archive on branch
``feature/structured-finite-radius-mobo-v2``.
"""

from __future__ import annotations

import math
import os
import sys

import gmsh


def load_kv(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


p = load_kv("params.dat")

clmin = float(os.environ.get("AJP_MESH_CLMIN", "1e-5"))
clmax = float(os.environ.get("AJP_MESH_CLMAX", "2e-4"))
mesh_algorithm = int(os.environ.get("AJP_MESH_ALGORITHM", "8"))

shoulder_radial_divisions = int(os.environ.get("AJP_STRUCTURED_SHOULDER_RADIAL_DIVISIONS", "50"))
structure_nozzle_taper = os.environ.get("AJP_STRUCTURED_NOZZLE_TAPER", "1") == "1"
default_throat_divisions = shoulder_radial_divisions if structure_nozzle_taper else 30
throat_divisions = int(os.environ.get("AJP_STRUCTURED_L25_DIVISIONS", str(default_throat_divisions)))
structured_test_blocks = os.environ.get("AJP_STRUCTURED_TEST_BLOCKS", "0") == "1"
substrate_layer_height = (
    float(os.environ.get("AJP_SUBSTRATE_LAYER_HEIGHT_MM", p.get("substrate_layer_height_mm", "0.2"))) * 1e-3
)
substrate_layer_divisions = int(os.environ.get("AJP_SUBSTRATE_LAYER_DIVISIONS", "6"))
substrate_axial_target = float(os.environ.get("AJP_SUBSTRATE_AXIAL_TARGET_MM", "0.1")) * 1e-3

theta0 = float(p["theta0_deg"]) * math.pi / 180
theta1 = float(p["theta1_deg"]) * math.pi / 180
theta2 = float(p["theta2_deg"]) * math.pi / 180
wedge_deg = float(os.environ.get("AJP_WEDGE_DEG", p.get("wedge_deg", "5.0")))
dtheta = wedge_deg * math.pi / 180
theta = -0.5 * dtheta

L0 = float(p["L0_mm"]) * 1e-3
L1 = float(p["L1_mm"]) * 1e-3
L2 = float(p["L2_mm"]) * 1e-3
L3 = float(p["L3_mm"]) * 1e-3
L4 = float(p["L4_mm"]) * 1e-3

R = float(p["R_mm"]) * 1e-3
Rin = float(p["Rin_mm"]) * 1e-3
t = float(p["t_mm"]) * 1e-3

R1 = float(p["R1_mm"]) * 1e-3
R2 = float(p["R2_mm"]) * 1e-3
R3 = float(p["R3_mm"]) * 1e-3

l1 = float(p["l1_mm"]) * 1e-3
l2 = float(p["l2_mm"]) * 1e-3
l1x = float(p["l1x_mm"]) * 1e-3
l1y = float(p["l1y_mm"]) * 1e-3
l2x = float(p["l2x_mm"]) * 1e-3
l2y = float(p["l2y_mm"]) * 1e-3

t2 = L3 * math.cos(theta2)
R4 = R + 10e-3
R5 = 50e-3
t1 = t + L0

if not 0.0 < substrate_layer_height < t:
    raise ValueError("substrate_layer_height_mm must be between 0 and t_mm")

def divisions_by_length(length: float, target: float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(math.ceil(max(length, 1.0e-12) / target))))


def proportional_divisions(lengths: list[float], total: int, minimum: int = 1) -> list[int]:
    if len(lengths) * minimum > total:
        raise ValueError("total divisions is too small for the requested minimum per segment")
    total_length = sum(max(length, 0.0) for length in lengths)
    if total_length <= 0.0:
        base = [minimum for _ in lengths]
        base[0] += total - sum(base)
        return base

    raw = [total * length / total_length for length in lengths]
    divisions = [max(minimum, int(math.floor(value))) for value in raw]

    while sum(divisions) > total:
        candidates = [idx for idx, value in enumerate(divisions) if value > minimum]
        idx = min(candidates, key=lambda i: raw[i] - divisions[i])
        divisions[idx] -= 1

    while sum(divisions) < total:
        idx = max(range(len(lengths)), key=lambda i: raw[i] - divisions[i])
        divisions[idx] += 1

    return divisions


def progression_from_first_to_last_width(
    length: float,
    first_width: float,
    target_last_width: float,
    minimum: int,
    maximum: int,
) -> tuple[int, float, float]:
    """Return cell count and ratio so the first cell matches first_width.

    Gmsh takes a number of points and a geometric progression ratio, not a
    direct first/last cell size. We therefore search the cell count whose exact
    first-cell match gives a last cell closest to target_last_width.
    """
    length = max(length, 1.0e-12)
    first_width = max(first_width, 1.0e-12)
    target_last_width = max(target_last_width, first_width)
    best: tuple[float, int, float, float] | None = None

    for divisions in range(max(2, minimum), max(2, maximum) + 1):
        if length / divisions < first_width:
            continue

        def scaled_first_width(ratio: float) -> float:
            if abs(ratio - 1.0) < 1.0e-12:
                return length / divisions
            return length * (ratio - 1.0) / (ratio**divisions - 1.0)

        lo = 1.0
        hi = 2.0
        while scaled_first_width(hi) > first_width and hi < 100.0:
            hi *= 2.0
        if hi >= 100.0:
            continue

        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if scaled_first_width(mid) > first_width:
                lo = mid
            else:
                hi = mid

        ratio = 0.5 * (lo + hi)
        actual_first = scaled_first_width(ratio)
        actual_last = actual_first * ratio ** (divisions - 1)
        error = abs(actual_last - target_last_width)
        if best is None or error < best[0]:
            best = (error, divisions, ratio, actual_last)

    if best is None:
        divisions = max(minimum, min(maximum, int(math.ceil(length / first_width))))
        return divisions, 1.0, length / divisions

    _, divisions, ratio, actual_last = best
    return divisions, ratio, actual_last


l24_divisions, l3_divisions, l30_divisions = proportional_divisions(
    [Rin, R1 - L3 - Rin, L3],
    shoulder_radial_divisions,
)


gmsh.initialize()

try:
    gmsh.model.add("AJP_nozzle")

    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", clmin)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", clmax)
    gmsh.option.setNumber("Mesh.Algorithm", mesh_algorithm)
    gmsh.option.setNumber("Mesh.RecombineAll", 0)
    gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 1)

    occ = gmsh.model.occ

    def add_profile_point(radius: float, axial: float) -> int:
        """Place the meridional profile on the centered wedge start plane."""
        return occ.addPoint(
            radius * math.cos(theta),
            axial,
            -radius * math.sin(theta),
            1.0,
        )

    pts: dict[int, int] = {}
    pts[1] = add_profile_point(0.0, t + L0 + L1 + L2 + L4)
    pts[2] = add_profile_point(Rin, t + L0 + L1 + L2 + L4)
    pts[3] = add_profile_point(Rin, t + L0 + L1 + L2)
    pts[4] = add_profile_point(R1 - L3, t + L0 + L1 + L2)
    pts[5] = add_profile_point(R2, t + L0 + L1 + L2 + l2y)
    pts[6] = add_profile_point(R3, t + L0 + L1 + L2 + l2y)
    pts[7] = add_profile_point(R3, t + L0 + L1 + L2 + l1y)
    pts[8] = add_profile_point(R2, t + L0 + L1 + L2 + l1y)
    pts[9] = add_profile_point(R1, t + L0 + L1 + L2)
    pts[10] = add_profile_point(R1, t + L0 + L1)
    pts[11] = add_profile_point(R, t + L0)
    pts[12] = add_profile_point(R, t)
    pts[13] = add_profile_point(R4, t)
    pts[14] = add_profile_point(R4, t1)
    pts[15] = add_profile_point(R5, t1)
    pts[16] = add_profile_point(R5, 0.0)
    pts[17] = add_profile_point(0.0, 0.0)

    # Axis-side construction points aligned to outer profile points. These
    # split the original axis edge L17 so later quadrilateral blocks can use
    # matching axial levels.
    pts[18] = add_profile_point(0.0, t)  # aligned with point 12
    pts[19] = add_profile_point(0.0, t + L0)  # aligned with point 11
    pts[20] = add_profile_point(0.0, t + L0 + L1)  # aligned with point 10
    pts[21] = add_profile_point(0.0, t + L0 + L1 + L2)  # aligned with point 3
    pts[22] = add_profile_point(R, 0.0)  # bottom edge point aligned with point 12
    pts[23] = add_profile_point(R4, 0.0)  # bottom edge point aligned with point 13
    pts[31] = add_profile_point(0.0, substrate_layer_height)
    pts[32] = add_profile_point(R, substrate_layer_height)
    pts[33] = add_profile_point(R4, substrate_layer_height)
    pts[34] = add_profile_point(R5, substrate_layer_height)
    pts[35] = add_profile_point(R5, t)  # split point on L15 aligned with point 13
    pts[40] = add_profile_point(Rin, t + L0 + L1)  # point on L29 aligned with point 3
    pts[41] = add_profile_point(R1 - L3, t + L0 + L1)  # point on L29 aligned with point 4

    lines: dict[int, int] = {}

    def add_line(idx: int, p1: int, p2: int) -> None:
        lines[idx] = occ.addLine(pts[p1], pts[p2])

    for idx in range(1, 15):
        add_line(idx, idx, idx + 1)
    add_line(15, 15, 35)
    add_line(16, 16, 23)
    add_line(17, 17, 31)
    add_line(18, 18, 19)
    add_line(19, 19, 20)
    add_line(20, 20, 21)
    add_line(21, 21, 1)
    add_line(22, 23, 22)
    add_line(23, 22, 17)
    add_line(31, 31, 18)
    add_line(34, 34, 16)
    add_line(39, 35, 34)

    construction_lines: dict[int, int] = {}

    def add_construction_line(idx: int, p1: int, p2: int) -> None:
        construction_lines[idx] = occ.addLine(pts[p1], pts[p2])

    add_construction_line(24, 3, 21)
    add_construction_line(25, 11, 19)
    add_construction_line(26, 12, 18)
    add_construction_line(27, 12, 32)
    add_construction_line(28, 13, 33)
    add_construction_line(29, 10, 41)
    add_construction_line(30, 4, 9)
    add_construction_line(32, 32, 22)
    add_construction_line(33, 33, 23)
    add_construction_line(35, 31, 32)
    add_construction_line(36, 32, 33)
    add_construction_line(37, 33, 34)
    add_construction_line(38, 13, 35)
    add_construction_line(40, 41, 40)
    add_construction_line(41, 40, 20)
    add_construction_line(42, 3, 40)
    add_construction_line(43, 4, 41)

    def curve(idx: int) -> int:
        sign = -1 if idx < 0 else 1
        key = abs(idx)
        if key in lines:
            tag = lines[key]
        else:
            tag = construction_lines[key]
        return sign * tag

    def set_curve_divisions(
        idx: int,
        divisions: int,
        mesh_type: str = "Progression",
        coef: float = 1.0,
        reverse: bool = False,
    ) -> None:
        # Gmsh expects number of points, which is one more than the number of cells.
        curve_coef = 1.0 / coef if reverse and mesh_type == "Progression" and coef != 0.0 else coef
        gmsh.model.mesh.setTransfiniteCurve(abs(curve(idx)), divisions + 1, mesh_type, curve_coef)

    structured_block_specs = {
        "axis_inlet": ([1, 2, 24, 21], [1, 2, 3, 21]),
        "core_shoulder_inner": ([-24, 42, 41, 20], [21, 3, 40, 20]),
        "core_shoulder_middle": ([3, 43, 40, -42], [3, 4, 41, 40]),
        "core_shoulder_outer": ([30, 9, 29, -43], [4, 9, 10, 41]),
        "nozzle_taper": ([-41, -40, -29, 10, 25, 19], [20, 10, 11, 19]),
        "nozzle_throat": ([-25, 11, 26, 18], [19, 11, 12, 18]),
        "axis_substrate_upper": ([-26, 27, -35, 31], [18, 12, 32, 31]),
        "axis_substrate_layer": ([35, 32, 23, 17], [31, 32, 22, 17]),
        "near_substrate_upper": ([12, 28, -36, -27], [12, 13, 33, 32]),
        "near_substrate_layer": ([36, 33, 22, -32], [32, 33, 23, 22]),
        "far_field_upper": ([14, 15, -38, 13], [14, 15, 35, 13]),
        "far_field_lower": ([38, 39, -37, -28], [13, 35, 34, 33]),
        "far_substrate_layer": ([37, 34, 16, -33], [33, 34, 16, 23]),
        "sheath_cavity": ([4, 5, 6, 7, 8, -30], [4, 5, 6, 7, 8, 9]),
    }
    structured_surfaces: dict[str, int] = {}
    for name, (loop_ids, corners) in structured_block_specs.items():
        loop = occ.addCurveLoop([curve(idx) for idx in loop_ids])
        surface = occ.addPlaneSurface([loop])
        structured_surfaces[name] = surface

    occ.synchronize()

    inlet_axial_divisions = divisions_by_length(L4, 1.0e-3, 8, 80)
    shoulder_axial_divisions = divisions_by_length(L2, 1.0e-3, 8, 80)
    taper_axial_divisions = divisions_by_length(L1, 5.0e-4, 8, 80)
    throat_axial_divisions = divisions_by_length(L0, 5.0e-4, 8, 50)
    near_field_axial_divisions = divisions_by_length(L0, 5.0e-4, 8, 60)
    substrate_axial_divisions = divisions_by_length(t - substrate_layer_height, substrate_axial_target, 4, 100)
    throat_radial_width = R / throat_divisions
    substrate_radial_divisions = max(1, int(round((R4 - R) / throat_radial_width)))
    substrate_far_radial_divisions, substrate_far_progression, substrate_far_last_width = (
        progression_from_first_to_last_width(
            R5 - R4,
            throat_radial_width,
            float(os.environ.get("AJP_SUBSTRATE_FAR_LAST_WIDTH_MM", "2.0")) * 1e-3,
            8,
            240,
        )
    )
    # Only curves required by four-corner transfinite blocks are fixed here.
    # The six-edge sheath_cavity block is deliberately left to Gmsh's regular
    # sizing, without construction splits or explicit edge divisions.
    for idx in (1, 24, 41):
        set_curve_divisions(idx, l24_divisions)
    for idx in (3, 40):
        set_curve_divisions(idx, l3_divisions)
    for idx in (30, 29):
        set_curve_divisions(idx, l30_divisions)
    for idx in (9, 20, 42, 43):
        set_curve_divisions(idx, shoulder_axial_divisions)
    for idx in (25, 26, 23):
        set_curve_divisions(idx, throat_divisions)
    for idx in (2, 21):
        set_curve_divisions(idx, inlet_axial_divisions)
    if structure_nozzle_taper:
        for idx in (10, 19):
            set_curve_divisions(idx, taper_axial_divisions)
    for idx in (11, 18):
        set_curve_divisions(idx, throat_axial_divisions)
    for idx in (31, 27, 28):
        set_curve_divisions(idx, substrate_axial_divisions)
    for idx in (13, 15):
        set_curve_divisions(idx, near_field_axial_divisions)
    for idx in (39,):
        set_curve_divisions(idx, substrate_axial_divisions)
    for idx in (17, 32, 33, 34):
        set_curve_divisions(idx, substrate_layer_divisions)
    for idx in (12, 22, 36):
        set_curve_divisions(idx, substrate_radial_divisions)
    for idx in (14, 37, 38):
        set_curve_divisions(idx, substrate_far_radial_divisions, "Progression", substrate_far_progression)
    for idx in (16,):
        set_curve_divisions(idx, substrate_far_radial_divisions, "Progression", substrate_far_progression, reverse=True)
    for idx in (35,):
        set_curve_divisions(idx, throat_divisions)

    for name, surface in structured_surfaces.items():
        corners = structured_block_specs[name][1]
        transfinite_enabled = (
            len(corners) == 4
            and (name != "nozzle_taper" or structure_nozzle_taper)
        )
        if transfinite_enabled:
            gmsh.model.mesh.setTransfiniteSurface(surface, cornerTags=[pts[idx] for idx in corners])
        if name != "sheath_cavity":
            gmsh.model.mesh.setRecombine(2, surface)

    if structured_test_blocks:
        for name, surface in structured_surfaces.items():
            pg = gmsh.model.addPhysicalGroup(2, [surface])
            gmsh.model.setPhysicalName(2, pg, name)
        gmsh.model.mesh.generate(2)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.write("meshData.msh")
        sys.exit(0)

    profile_entities = [(2, surface) for surface in structured_surfaces.values()]
    out = occ.revolve(
        profile_entities,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        dtheta,
        numElements=[1],
        recombine=True,
    )

    occ.synchronize()

    vol_tags = [tag for dim, tag in out if dim == 3]
    if not vol_tags:
        raise RuntimeError("No volume created. Check loop validity and axis/angle.")
    gmsh.model.setPhysicalName(3, gmsh.model.addPhysicalGroup(3, vol_tags), "volume")

    external_surfaces = sorted(
        {
            tag
            for dim, tag in gmsh.model.getBoundary(
                [(3, tag) for tag in vol_tags],
                combined=True,
                oriented=False,
                recursive=False,
            )
            if dim == 2
        }
    )

    y_top = t + L0 + L1 + L2 + L4
    y_nozzle_outer = t + L0 + L1
    y_sheath_low = t + L0 + L1 + L2 + l1y
    y_sheath_high = t + L0 + L1 + L2 + l2y
    coord_tol = 1.0e-6
    radial_tol = 1.0e-4
    angle_tol = abs(dtheta) * 0.25

    physical_surfaces: dict[str, list[int]] = {
        "front": [],
        "back": [],
        "inletAerosol": [],
        "inletSheath": [],
        "outlet": [],
        "wallUpper": [],
        "wallDown": [],
        "wallCavity": [],
        "wallSubstrate": [],
    }

    def near(value: float, target: float) -> bool:
        return abs(value - target) <= coord_tol

    for surface in external_surfaces:
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, surface)
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, surface)
        r_center = math.hypot(cx, cz)
        r_min = min(math.hypot(xmin, zmin), math.hypot(xmin, zmax), math.hypot(xmax, zmin), math.hypot(xmax, zmax))
        r_max = max(math.hypot(xmin, zmin), math.hypot(xmin, zmax), math.hypot(xmax, zmin), math.hypot(xmax, zmax))
        y_span = ymax - ymin
        angle = math.atan2(cz, cx) if r_center > coord_tol else 0.0

        if abs(angle - abs(theta)) <= angle_tol:
            physical_surfaces["front"].append(surface)
        elif abs(angle + abs(theta)) <= angle_tol:
            physical_surfaces["back"].append(surface)
        elif y_span <= coord_tol and near(cy, y_top):
            physical_surfaces["inletAerosol"].append(surface)
        elif abs(r_center - R3) <= radial_tol and ymin >= y_sheath_low - coord_tol and ymax <= y_sheath_high + coord_tol:
            physical_surfaces["inletSheath"].append(surface)
        elif abs(r_center - R5) <= radial_tol:
            physical_surfaces["outlet"].append(surface)
        elif y_span <= coord_tol and near(cy, 0.0):
            physical_surfaces["wallSubstrate"].append(surface)
        elif r_max <= R1 + coord_tol and ymin >= t - coord_tol and ymax <= y_nozzle_outer + coord_tol:
            physical_surfaces["wallDown"].append(surface)
        elif r_min >= R - coord_tol and (
            y_span <= coord_tol and (near(cy, t) or near(cy, t1))
            or abs(r_center - R4) <= radial_tol and ymin >= t - coord_tol and ymax <= t1 + coord_tol
        ):
            physical_surfaces["wallCavity"].append(surface)
        else:
            physical_surfaces["wallUpper"].append(surface)

    missing = [name for name, tags in physical_surfaces.items() if not tags]
    if missing and os.environ.get("AJP_DEBUG_BOUNDARY_CLASSIFICATION", "0") == "1":
        print("Boundary classification debug:")
        for surface in external_surfaces:
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, surface)
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, surface)
            r_center = math.hypot(cx, cz)
            angle = math.atan2(cz, cx) if r_center > coord_tol else 0.0
            owner = next((name for name, tags in physical_surfaces.items() if surface in tags), "UNCLASSIFIED")
            print(
                f"  surface={surface} owner={owner} "
                f"center=({cx:.8g}, {cy:.8g}, {cz:.8g}) "
                f"r={r_center:.8g} angle={angle:.8g} "
                f"bbox=({xmin:.8g}, {ymin:.8g}, {zmin:.8g}, {xmax:.8g}, {ymax:.8g}, {zmax:.8g})"
            )
    if missing:
        raise RuntimeError(f"Failed to classify mesh boundary surfaces for: {', '.join(missing)}")

    for name, tags in physical_surfaces.items():
        gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, tags), name)

    gmsh.model.mesh.generate(3)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.write("meshData.msh")
finally:
    gmsh.finalize()
