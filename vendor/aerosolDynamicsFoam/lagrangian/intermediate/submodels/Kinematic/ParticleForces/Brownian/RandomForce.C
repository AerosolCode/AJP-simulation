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

\*---------------------------------------------------------------------------*/

#include "RandomForce.H"
#include "Random.H"

// * * * * * * * * * * * * * * * * Constructors  * * * * * * * * * * * * * * //

template<class CloudType>
Foam::RandomForce<CloudType>::RandomForce
(
    CloudType& owner,
    const fvMesh& mesh,
    const dictionary& dict
)
:
    ParticleForce<CloudType>(owner, mesh, dict, typeName, false)
{}


template<class CloudType>
Foam::RandomForce<CloudType>::RandomForce(const RandomForce& gf)
:
    ParticleForce<CloudType>(gf)
{}


// * * * * * * * * * * * * * * * * * Destructor  * * * * * * * * * * * * * * //

template<class CloudType>
Foam::RandomForce<CloudType>::~RandomForce()
{}


// * * * * * * * * * * * * * * * Member Functions  * * * * * * * * * * * * * //


template<class CloudType>
Foam::forceSuSp Foam::RandomForce<CloudType>::calcNonCoupled
(
    const typename CloudType::parcelType& p,
    const typename CloudType::parcelType::trackingData& td,
    const scalar dt,
    const scalar mass,
    const scalar Re,
    const scalar muc
) const
{
    forceSuSp value(Zero);

    Random& rnd = this->owner().rndGen();

    scalar lam = 67e-9;//muc / 0.499 * sqrt(M_PI / (8.0 * td.rhoc() * td.Pc()));
    scalar Kn = lam / p.d();
    scalar Cc = 1 + Kn * (2.514 + 0.80 * exp(-0.55 / Kn));
    scalar gamma = 3 * M_PI * muc * p.d() / Cc;
    scalar coeff = sqrt(2 * kb * T * gamma / dt);
    value.Su() = rnd.GaussNormal<vector>() * coeff;

    return value;
}


// ************************************************************************* //
