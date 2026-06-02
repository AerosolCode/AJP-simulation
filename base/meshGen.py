import math
import gmsh

def load_kv(path: str) -> dict[str, str]:
    d: dict[str, str] = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d

# ===== load params =====
p = load_kv("params.dat")

# ===== base constants =====
INCH = 25.4e-3  # [m]

clmin = 1e-5
clmax = 2e-4

theta  = -math.pi / 72   # rotate first
dtheta =  math.pi / 36   # then revolve this much

# ===== parse (required) =====
theta0           = float(p["theta0_deg"]) * math.pi / 180
theta1           = float(p["theta1_deg"]) * math.pi / 180
theta2           = float(p["theta2_deg"]) * math.pi / 180

L0               = float(p["L0_mm"])    * 1e-3
L1               = float(p["L1_mm"])    * 1e-3
L2               = float(p["L2_mm"])    * 1e-3
L3               = float(p["L3_mm"])    * 1e-3
L4               = float(p["L4_mm"])    * 1e-3

R                = float(p["R_mm"])     * 1e-3
t                = float(p["t_mm"])     * 1e-3

Q1               = float(p["Q1_lpm"])   * 1e-3 / 60
Q2               = float(p["Q2_lpm"])   * 1e-3 / 60

# ===== derived / aliases (match your variable names) =====
alpha1 = 5
alpha2 = 5
l2 = L3 * math.sin(theta1)
l3 = L3 + l2 * alpha1 * math.cos(theta2)
R1 = R + L1 * math.tan(theta0)
R2 = R1 + (l3 - L3) * math.tan(theta2)
R3 = R1 + l3 * math.tan(theta1)
R4 = R + 1e-3
R5 = 50e-3
t1 = t + L0

l4 = (R3 - R2) * alpha2


gmsh.initialize()
gmsh.model.add("AJP_nozzle")

gmsh.option.setNumber("Mesh.CharacteristicLengthMin", clmin)
gmsh.option.setNumber("Mesh.CharacteristicLengthMax", clmax)

occ = gmsh.model.occ

# -------------------------
# Build points (store gmsh point tags!)
# -------------------------
pts = {}

pts[1] = occ.addPoint(0.0,  t + L0 + L1 + L2 + L3 + L4, 0.0, 1.0)
pts[2] = occ.addPoint(R1,   t + L0 + L1 + L2 + L3 + L4, 0.0, 1.0)
pts[3] = occ.addPoint(R1,   t + L0 + L1 + L2 + L3,      0.0, 1.0)
pts[4] = occ.addPoint(R2,   t + L0 + L1 + L2 + l3,      0.0, 1.0)
pts[5] = occ.addPoint(R2,   t + L0 + L1 + L2 + l3 + l4, 0.0, 1.0)
pts[6] = occ.addPoint(R3,   t + L0 + L1 + L2 + l3 + l4, 0.0, 1.0)
pts[7] = occ.addPoint(R3,   t + L0 + L1 + L2 + l3,      0.0, 1.0)

pts[8] = occ.addPoint(R1,   t + L0 + L1 + L2,           0.0, 1.0)
pts[9] = occ.addPoint(R1,   t + L0 + L1,                0.0, 1.0)
pts[10] = occ.addPoint(R,    t + L0,                     0.0, 1.0)
pts[11] = occ.addPoint(R,    t,                          0.0, 1.0)

pts[12] = occ.addPoint(R3,   t,                         0.0, 1.0)
pts[13] = occ.addPoint(R3,   t1,                        0.0, 1.0)
pts[14] = occ.addPoint(R4,   t1,                        0.0, 1.0)
pts[15] = occ.addPoint(R4,   0.0,                       0.0, 1.0)
pts[16] = occ.addPoint(0.0,  0.0,                       0.0, 1.0)

# -------------------------
# Build lines (MUST use point tags: pts[...])
# -------------------------
lines = {}

def add_line(idx, p1, p2):
    lines[idx] = occ.addLine(pts[p1], pts[p2])

Npts = len(pts)
for i, pt in enumerate(pts):
    if(i + 1 == Npts):
        add_line(pt, pt, 1)
    else:
        add_line(pt, pt, pt + 1)

# -------------------------
# Surface from curve loop
# -------------------------
loop_line_tags = [lines[i] for i in sorted(lines.keys())]
cloop = occ.addCurveLoop(loop_line_tags)
surf  = occ.addPlaneSurface([cloop])

occ.synchronize()

occ.rotate([(2, surf)], 0.0, 0.0, 0.0,
           0.0, 1.0, 0.0,
           theta0)

occ.synchronize()

out = occ.revolve([(2, surf)],
                  0.0, 0.0, 0.0,
                  0.0, 1.0, 0.0,
                  dtheta,
                  numElements=[1],
                  recombine=True)

occ.synchronize()

gmsh.fltk.run()

# ----- electrode surfaces -----
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[0][1]]), f"front")
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[14][1]]), f"back")

gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[1][1]]), f"inletAerosol")
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[5][1]]), f"inletSheath")
gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[14][1]]), f"outlet")

s = [out[2][1], out[3][1], out[4][1], out[6][1], out[7][1], out[8][1]] 
pg = gmsh.model.addPhysicalGroup(2, s)
gmsh.model.setPhysicalName(2, pg, f"wallUpper")

s = [out[9][1], out[10][1]] 
pg = gmsh.model.addPhysicalGroup(2, s)
gmsh.model.setPhysicalName(2, pg, f"wallDown")

s = [out[11][1], out[12][1], out[13][1]] 
pg = gmsh.model.addPhysicalGroup(2, s)
gmsh.model.setPhysicalName(2, pg, f"wallCavity")

gmsh.model.setPhysicalName(2, gmsh.model.addPhysicalGroup(2, [out[15][1]]), f"wallSubstrate")


# get created volume tag(s)
vol_tags = [tag for (dim, tag) in out if dim == 3]
if not vol_tags:
    raise RuntimeError("No volume created. Check loop validity and axis/angle.")
vol = vol_tags[0]

# Physical groups (recommended for OpenFOAM)
pgV = gmsh.model.addPhysicalGroup(3, [vol])
gmsh.model.setPhysicalName(3, pgV, "volume")

# -------------------------
# Mesh + write
# -------------------------
#gmsh.model.mesh.generate(3)
# ---- recombine 2D surfaces → quad mesh ----
#gmsh.model.mesh.setRecombine(2, surf)

# ---- choose hex-friendly algorithm ----
#gmsh.option.setNumber("Mesh.Algorithm3D", 8)

# ---- mesh ----
#gmsh.model.mesh.generate(2)
gmsh.model.mesh.generate(3)

gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.write("meshData.msh")

gmsh.finalize()