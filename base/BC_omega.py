import numpy as np

def load_kv(path: str):
    d = {}
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

# ===== read params =====
Rin = float(p["Rin_mm"])
t = float(p["l2y_mm"]) - float(p["l1y_mm"])

header = '''
/*--------------------------------*- C++ -*----------------------------------*
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     | Website:  https://openfoam.org
    \\  /    A nd           | Version:  9
     \\/     M anipulation  |
\*---------------------------------------------------------------------------*/
FoamFile
{
    format      ascii;
    class       volScalarField;
    object      omega;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      [0 0 -1 0 0 0 0];

internalField   uniform 1e-100;

boundaryField
{
'''

footer = '''
    outlet
    {
        //type                inletOutlet;
        type            zeroGradient;
        //inletValue	        uniform 1e-10;
    	value		        $internalField;
    }
    "wall.*"
    {
        type                omegaWallFunction;
        value               $internalField;
    }
    "(front|back)"
    {
        type            wedge;
    }
}
'''

# ===== 出力 =====
# ===== 出力 =====
with open("0/omega", "w") as f:
    f.write(header)

    f.write(f"    inletSheath\n")
    f.write("    {\n")
    f.write(f"        type                turbulentMixingLengthDissipationRateInlet;\n")
    f.write(f"        mixingLength        {0.07 * t * 1e-3};\n")
    f.write(f"        value               $internalField;\n")
    f.write("    }\n\n")

    f.write(f"    inletAerosol\n")
    f.write("    {\n")
    f.write(f"        type                turbulentMixingLengthDissipationRateInlet;\n")
    f.write(f"        mixingLength        {0.07 * Rin * 1e-3};\n")
    f.write(f"        value               $internalField;\n")
    f.write("    }\n\n")

    f.write(footer)
