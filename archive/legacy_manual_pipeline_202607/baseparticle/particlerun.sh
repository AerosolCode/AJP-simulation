#!/bin/bash
#SBATCH --output=output_particle.txt
#SBATCH --error=error_particle.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000

# baseparticle コピー
#rm -rf baseparticle
#cp -r ../baseparticle ./

# CFD結果を 0 として使用
rm -rf 0
cp -r ../10000 0

# meshコピー
rm -rf constant/polyMesh
cp -r ../constant/polyMesh constant/

# wedge → symmetryPlane

sed -i \
's/type[[:space:]]*wedge/type    symmetryPlane/g' \
constant/polyMesh/boundary

for f in \
    0/U \
    0/p \
    0/k \
    0/omega \
    0/nut \
    0/phi 
do
    if [ -f "$f" ]; then
            sed -i \
            's/type[[:space:]]*wedge/type            symmetryPlane/g' \
            "$f"
    fi
done



CASE_NUM=$(basename "$(dirname "$PWD")" | sed 's/case_//')

touch "p_${CASE_NUM}.foam"

touch log.icoUncoupledKinematicParcelFoam
icoUncoupledKinematicParcelFoam > log.icoUncoupledKinematicParcelFoam 2>&1



#cp -r ../baseparticle ./ 
#cp -r 10000 baseparticle/0
#cp -r constant/polyMesh baseparticle/constant/
#cd baseparticle

#icoUncoupledKinematicParcelFoam