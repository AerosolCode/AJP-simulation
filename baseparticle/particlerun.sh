cp -r ../baseparticle ./ 
cp -r 10000 baseparticle/0
cp -r constant/polyMesh baseparticle/constant/
cd baseparticle

icoUncoupledKinematicParcelFoam

