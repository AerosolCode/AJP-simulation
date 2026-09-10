/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2011-2017 OpenFOAM Foundation
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

Class
    Foam::RandomForce

Group
    grpLagrangianIntermediateForceSubModels

Description
    Calculates a Brownian random force for kinematic particles.

SourceFiles
    RandomForce.C

\*---------------------------------------------------------------------------*/

#ifndef Foam_RandomForce_H
#define Foam_RandomForce_H

#include "ParticleForce.H"

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

namespace Foam
{

// Forward Declarations
class fvMesh;

/*---------------------------------------------------------------------------*\
                       Class RandomForce Declaration
\*---------------------------------------------------------------------------*/

template<class CloudType>
class RandomForce
:
    public ParticleForce<CloudType>
{
    // Private Data

    const scalar kb = 1.38e-23;
    const scalar T = 300.0;

public:

    //- Runtime type information
    TypeName("random");


    // Constructors

    //- Construct from mesh
    RandomForce
    (
        CloudType& owner,
        const fvMesh& mesh,
        const dictionary& dict
    );

    //- Construct copy
    RandomForce(const RandomForce& randf);

    //- Construct and return a clone
    virtual autoPtr<ParticleForce<CloudType>> clone() const
    {
        return autoPtr<ParticleForce<CloudType>>
        (
            new RandomForce<CloudType>(*this)
        );
    }


    //- Destructor
    virtual ~RandomForce();


    // Member Functions

    // Access


    // Random number generation
    //void generateRandom();


    //- Calculate the non-coupled force
    virtual forceSuSp calcNonCoupled
    (
        const typename CloudType::parcelType& p,
        const typename CloudType::parcelType::trackingData& td,
        const scalar dt,
        const scalar mass,
        const scalar Re,
        const scalar muc
    ) const;
};


// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

} // End namespace Foam

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

#ifdef NoRepository
    #include "RandomForce.C"
#endif

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

#endif

// ************************************************************************* //
