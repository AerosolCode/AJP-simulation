#!/usr/bin/env python3
"""Archived unstructured mesh generator; not used by production workflows."""

from __future__ import annotations

import math
import os

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

theta = -math.pi / 72
dtheta = math.pi / 36

theta0 = float(p["theta0_deg"]) * math.pi / 180
theta1 = float(p["theta1_deg"]) * math.pi / 180
theta2 = float(p["theta2_deg"]) * math.pi / 180

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

gmsh.initialize()

try:
    gmsh.model.add("AJP_nozzle")

    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", clmin)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", clmax)

    occ = gmsh.model.occ

    pts: dict[int, int] = {}
    pts[1] = occ.addPoint(0.0, t + L0 + L1 + L2 + L4, 0.0, 1.0)
    pts[2] = occ.addPoint(Rin, t + L0 + L1 + L2 + L4, 0.0, 1.0)
    pts[3] = occ.addPoint(Rin, t + L0 + L1 + L2, 0.0, 1.0)
    pts[4] = occ.addPoint(R1 - L3, t + L0 + L1 + L2, 0.0, 1.0)
    pts[5] = occ.addPoint(R2, t + L0 + L1 + L2 + l2y, 0.0, 1.0)
    pts[6] = occ.addPoint(R3, t + L0 + L1 + L2 + l2y, 0.0, 1.0)
    pts[7] = occ.addPoint(R3, t + L0 + L1 + L2 + l1y, 0.0, 1.0)
    pts[8] = occ.addPoint(R2, t + L0 + L1 + L2 + l1y, 0.0, 1.0)
    pts[9] = occ.addPoint(R1, t + L0 + L1 + L2, 0.0, 1.0)
    pts[10] = occ.addPoint(R1, t + L0 + L1, 0.0, 1.0)
    pts[11] = occ.addPoint(R, t + L0, 0.0, 1.0)
    pts[12] = occ.addPoint(R, t, 0.0, 1.0)
    pts[13] = occ.addPoint(R4, t, 0.0, 1.0)
    pts[14] = occ.addPoint(R4, t1, 0.0, 1.0)
    pts[15] = occ.addPoint(R5, t1, 0.0, 1.0)
    pts[16] = occ.addPoint(R5, 0.0, 0.0, 1.0)
    pts[17] = occ.addPoint(0.0, 0.0, 0.0, 1.0)

    lines: dict[int, int] = {}

    def add_line(idx: int, p1: int, p2: int) -> None:
        lines[idx] = occ.addLine(pts[p1], pts[p2])

    for idx in range(1, 17):
        add_line(idx, idx, idx + 1)
    add_line(17, 17, 1)

    curve_loop = occ.addCurveLoop([lines[idx] for idx in sorted(lines)])
    surf = occ.addPlaneSurface([curve_loop])

    occ.synchronize()

    occ.rotate([(2, surf)], 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, theta)

    occ.synchronize()

    out = occ.revolve(
        [(2, surf)],
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

    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[0][1]]), "front")
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[1][1]]), "back")
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[2][1]]), "inletAerosol")
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[7][1]]), "inletSheath")
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[16][1]]), "outlet")

    gmsh.model.setPhysicalName(
        2,
        gmsh.model.addPhysicalGroup(
            2,
            [out[3][1], out[4][1], out[5][1], out[6][1], out[8][1], out[9][1], out[10][1]],
        ),
        "wallUpper",
    )
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[11][1], out[12][1]]), "wallDown")
    gmsh.model.setPhysicalName(
        2,
        gmsh.model.addPhysicalGroup(2, [out[13][1], out[14][1], out[15][1]]),
        "wallCavity",
    )
    gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[17][1]]), "wallSubstrate")

    f_dist = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(f_dist, "CurvesList", [lines[11], lines[4]])
    gmsh.model.mesh.field.setNumber(f_dist, "Sampling", 200)

    f_th = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(f_th, "InField", f_dist)
    gmsh.model.mesh.field.setNumber(f_th, "SizeMin", float(os.environ.get("AJP_MESH_REFINED_SIZE_MIN", "1e-4")))
    gmsh.model.mesh.field.setNumber(f_th, "SizeMax", float(os.environ.get("AJP_MESH_REFINED_SIZE_MAX", "5e-4")))
    gmsh.model.mesh.field.setNumber(f_th, "DistMin", float(os.environ.get("AJP_MESH_REFINED_DIST_MIN", "1e-3")))
    gmsh.model.mesh.field.setNumber(f_th, "DistMax", float(os.environ.get("AJP_MESH_REFINED_DIST_MAX", "20e-3")))
    gmsh.model.mesh.field.setNumber(f_th, "Sigmoid", 1)
    gmsh.model.mesh.field.setAsBackgroundMesh(f_th)

    vol_tags = [tag for dim, tag in out if dim == 3]
    if not vol_tags:
        raise RuntimeError("No volume created. Check loop validity and axis/angle.")
    gmsh.model.setPhysicalName(3, gmsh.model.addPhysicalGroup(3, [vol_tags[0]]), "volume")

    gmsh.model.mesh.generate(3)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.write("meshData.msh")
finally:
    gmsh.finalize()
