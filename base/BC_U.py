import numpy as np

def load_kv(path: str) -> dict[str, str]:
    d = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d

p = load_kv("params.dat")

Qsheath_Lmin = float(p["Qsheath_lpm"])
Qaerosol_Lmin = float(p["Qaerosol_lpm"])

# L/min → m³/s → scaling
def convert(Q_Lmin):
    return Q_Lmin * 1e-3 / 60.0 * 5 / 360

Qsheath = convert(Qsheath_Lmin)
Qaerosol = convert(Qaerosol_Lmin)

header = '''
/*--------------------------------*- C++ -*----------------------------------*\
| =========                 |                                                 |
| \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\    /   O peration     | Version:  2406                                  |
|   \\  /    A nd           | Website:  www.openfoam.com                      |
|    \\/     M anipulation  |                                                 |
\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    arch        "LSB;label=32;scalar=64";
    class       volVectorField;
    location    "0";
    object      U;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
'''

footer = '''
    outlet
    {
        type            pressureInletOutletVelocity;
    	value		    $internalField;
    }
    "(wall.*)"
    {
        type            noSlip;
    }
    "(front|back)"
    {
        type            wedge;
    }

}
'''

# ===== 出力 =====
with open("0/U", "w") as f:
    f.write(header)

    f.write(f"    inletSheath\n")
    f.write("    {\n")
    f.write(f"        type                    flowRateInletVelocity;\n")
    f.write(f"        volumetricFlowRate      constant {Qsheath};\n")
    f.write(f"        extrapolateProfile      0;\n")
    f.write(f"        value                   uniform (0 0 0);\n")
    f.write("    }\n\n")

    f.write(f"    inletAerosol\n")
    f.write("    {\n")
    f.write(f"        type                    flowRateInletVelocity;\n")
    f.write(f"        volumetricFlowRate      constant {Qaerosol};\n")
    f.write(f"        extrapolateProfile      0;\n")
    f.write(f"        value                   uniform (0 0 0);\n")
    f.write("    }\n\n")

    f.write(footer)
