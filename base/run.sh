python meshGen2.py
gmshToFoam meshData.msh
python changeBCType.py

python BC_omega.py
python BC_U.py

simpleFoam