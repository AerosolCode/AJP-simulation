from scipy.stats import qmc
import os
import math

# =========================
# 1. Sobolで振る変数範囲
# =========================
bounds = {
    "R_mm": (0.5, 2.0),
    "alphaRin": (0.3, 0.7),
    "alphaL0": (1.0, 5.0),
    "L1_mm": (1.0, 20.0),
    "alphaL2": (0.5, 5.0),
    "alphaL3": (0, 1),
    "theta0_deg": (10.0, 60.0),
    "theta1_deg": (10.0, 60.0),
    "alphaTheta2": (0.0, 1.0),
    "alphat": (0.5, 5.0),
    "U_mps": (1.0, 50.0),
}

keys = list(bounds.keys())

# =========================
# 2. Sobolサンプリング
# =========================
m = 0  # 2^5 = 32
n_dim = len(keys)

sampler = qmc.Sobol(d=n_dim, scramble=True, seed=0)
X = sampler.random_base2(m=m)

# =========================
# 3. 0〜1を実スケールに変換
# =========================
def scale_sample(x):
    raw = {}

    for i, key in enumerate(keys):
        low, high = bounds[key]
        raw[key] = low + (high - low) * x[i]

    return raw

# =========================
# 4. alpha係数から実パラメータへ変換
# =========================
def convert_params(raw):
    R = raw["R_mm"]
    L0 = raw["alphaL0"] * R
    R1 = R + raw["L1_mm"] * math.tan(raw["theta0_deg"] * math.pi / 180)
    Rin = raw["alphaRin"] * R1
    L3min_mm = Rin + 1
    L3max_mm = R1 - 1
    if L3min_mm >= L3max_mm:
        return None
    L3 = R1 - L3min_mm - (L3max_mm - L3min_mm) * raw["alphaL3"]
    theta2 = raw["alphaTheta2"] * (raw["theta1_deg"] - 10) + 10
    
    U = raw["U_mps"]
    Q = math.pi * R**2 * U
    Qaerosol = Q * Rin**2 / (Rin**2 + R1**2 - (R1 - L3)**2) # m mm^2 / s
    Qsheath = Q - Qaerosol # m mm^2 / s   

    l1 = 3 * L3
    l1x = l1 * math.sin(raw["theta1_deg"] * math.pi / 180)
    l1y = l1 * math.cos(raw["theta1_deg"] * math.pi / 180)     
    l2x = l1x + L3
    l2 = l2x / math.sin(theta2 * math.pi / 180)
    l2y = l2x / math.tan(theta2 * math.pi / 180)

    R2 = R1 + l1x
    R3 = R2 + (l2x - l1x) * 5
    R4 = R + 1e-3

    params = {
        "R_mm": R,
        "L0_mm" : L0,
        "R1_mm": R1,
        "Rin_mm": Rin,

        "L1_mm": raw["L1_mm"],
        "L2_mm": raw["alphaL2"] * R1,
        "L3_mm": L3,
        "L4_mm": 5 * Rin,
        "t_mm": raw["alphat"] * R,

        "theta0_deg": raw["theta0_deg"],
        "theta1_deg": raw["theta1_deg"],
        "theta2_deg": theta2,
        "U_mps": raw["U_mps"],
        "Qaerosol_lpm": Qaerosol / 1000 * 60.0,
        "Qsheath_lpm": Qsheath / 1000 * 60.0,

        "R1_mm": R1,
        "R2_mm": R2,
        "R3_mm": R3,

        "l1_mm": l1,
        "l2_mm": l2,
        "l1x_mm": l1x,
        "l1y_mm": l1y,
        "l2x_mm": l2x,
        "l2y_mm": l2y,
    }

    return params

# =========================
# 5. PARAMS.DATを書き出し
# =========================
output_keys = [
    "R_mm",
    "Rin_mm",
    "L0_mm",
    "L1_mm",
    "L2_mm",
    "L3_mm",
    "L4_mm",
    "t_mm",
    "theta0_deg",
    "theta1_deg",
    "theta2_deg",
    "U_mps",
    "Qaerosol_lpm",
    "Qsheath_lpm",
    "R1_mm",
    "R2_mm",
    "R3_mm",
    "l1_mm",
    "l2_mm",
    "l1x_mm",
    "l1y_mm",
    "l2x_mm",
    "l2y_mm",
]

valid_count = 0

for i, x in enumerate(X):
    raw = scale_sample(x)
    params = convert_params(raw)

    if params is None:
        continue

    dirname = f"case_{valid_count:04d}"
    os.makedirs(dirname, exist_ok=True)

    with open(os.path.join(dirname, "params.dat"), "w") as f:
        for key in output_keys:
            f.write(f"{key}={params[key]:.8f}\n")

    valid_count += 1

    os.system(f"cp -r base/* {dirname}/")
    os.chdir(dirname)
    os.system("bash run.sh")
    os.chdir("../")

print(f"{valid_count} valid cases generated.")