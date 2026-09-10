/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2011-2015 OpenFOAM Foundation
    Copyright (C) 2020 OpenCFD Ltd.
-------------------------------------------------------------------------------
License
    This file is part of OpenFOAM.

    OpenFOAM is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    OpenFOAM is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
    FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
    for more details.

    You should have received a copy of the GNU General Public License
    along with OpenFOAM.  If not, see <http://www.gnu.org/licenses/>.

\*---------------------------------------------------------------------------*/

#include "basicKinematicCloud.H"

#include "KinematicReynoldsNumber.H"
#include "ParticlePostProcessing.H"
#include "DistanceTrajectory.H"

#include "StokesDragForce.H"
#include "SphereDragForce.H"
#include "RandomForce.H"
#include "GravityForce.H"

#include "NoDispersion.H"
#include "GradientDispersionRAS.H"
#include "StochasticDispersionRAS.H"
#include "ManualInjection.H"
#include "StandardWallInteraction.H"
#include "NoStochasticCollision.H"
#include "NoSurfaceFilm.H"

#include "NoDamping.H"
#include "NoIsotropy.H"
#include "NoPacking.H"

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

makeCloudFunctionObject(basicKinematicCloud);
makeCloudFunctionObjectType(KinematicReynoldsNumber, basicKinematicCloud);
makeCloudFunctionObjectType(ParticlePostProcessing, basicKinematicCloud);
makeCloudFunctionObjectType(DistanceTrajectory, basicKinematicCloud);

makeParticleForceModel(basicKinematicCloud);
makeParticleForceModelType(StokesDragForce, basicKinematicCloud);
makeParticleForceModelType(SphereDragForce, basicKinematicCloud);
makeParticleForceModelType(RandomForce, basicKinematicCloud);
makeParticleForceModelType(GravityForce, basicKinematicCloud);

makeDispersionModel(basicKinematicCloud);
makeDispersionModelType(NoDispersion, basicKinematicCloud);
defineNamedTemplateTypeNameAndDebug
(
    Foam::DispersionRASModel<Foam::basicKinematicCloud::kinematicCloudType>,
    0
);
makeDispersionModelType(GradientDispersionRAS, basicKinematicCloud);
makeDispersionModelType(StochasticDispersionRAS, basicKinematicCloud);

makeInjectionModel(basicKinematicCloud);
makeInjectionModelType(ManualInjection, basicKinematicCloud);

makePatchInteractionModel(basicKinematicCloud);
makePatchInteractionModelType(StandardWallInteraction, basicKinematicCloud);

makeStochasticCollisionModel(basicKinematicCloud);
makeStochasticCollisionModelType(NoStochasticCollision, basicKinematicCloud);

makeSurfaceFilmModel(basicKinematicCloud);
makeSurfaceFilmModelType(NoSurfaceFilm, basicKinematicCloud);

makeDampingModel(basicKinematicCloud);
makeDampingModelType(NoDamping, basicKinematicCloud);

makeIsotropyModel(basicKinematicCloud);
makeIsotropyModelType(NoIsotropy, basicKinematicCloud);

makePackingModel(basicKinematicCloud);
makePackingModelType(NoPacking, basicKinematicCloud);

// ************************************************************************* //
