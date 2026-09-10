/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2011-2017 OpenFOAM Foundation
    Copyright (C) 2015-2022 OpenCFD Ltd.
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

#include "ManualInjection.H"
#include "mathematicalConstants.H"
#include "bitSet.H"
#include "OSspecific.H"

#include <cstdlib>

using namespace Foam::constant::mathematical;

// * * * * * * * * * * * * * * * * Constructors  * * * * * * * * * * * * * * //

template<class CloudType>
Foam::ManualInjection<CloudType>::ManualInjection
(
    const dictionary& dict,
    CloudType& owner,
    const word& modelName
)
:
    InjectionModel<CloudType>(dict, owner, modelName, typeName),
    positionsFile_(this->coeffDict().lookup("positionsFile")),
    positions_
    (
        IOobject
        (
            positionsFile_,
            owner.db().time().constant(),
            owner.mesh(),
            IOobject::MUST_READ,
            IOobject::NO_WRITE
        )
    ),
    diameters_(positions_.size()),
    injectorCells_(positions_.size(), -1),
    injectorTetFaces_(positions_.size(), -1),
    injectorTetPts_(positions_.size(), -1),
    U0_(this->coeffDict().lookup("U0")),
    sizeDistribution_
    (
        distributionModel::New
        (
            this->coeffDict().subDict("sizeDistribution"),
            owner.rndGen()
        )
    ),
    ignoreOutOfBounds_
    (
        this->coeffDict().getOrDefault("ignoreOutOfBounds", false)
    ),
    nParticleShards_
    (
        this->coeffDict().template getOrDefault<label>("nParticleShards", 1)
    ),
    particleShard_
    (
        this->coeffDict().template getOrDefault<label>("particleShard", 0)
    )
{
    const string nShardsEnv(getEnv("FOAM_N_PARTICLE_SHARDS"));
    const string shardEnv(getEnv("FOAM_PARTICLE_SHARD"));

    if (!nShardsEnv.empty())
    {
        nParticleShards_ = std::atoi(nShardsEnv.c_str());
    }

    if (!shardEnv.empty())
    {
        particleShard_ = std::atoi(shardEnv.c_str());
    }

    if (nParticleShards_ < 1)
    {
        FatalIOErrorInFunction(this->coeffDict())
            << "nParticleShards must be greater than zero" << nl
            << exit(FatalIOError);
    }

    if (particleShard_ < 0 || particleShard_ >= nParticleShards_)
    {
        FatalIOErrorInFunction(this->coeffDict())
            << "particleShard must be in [0, nParticleShards). "
            << "particleShard = " << particleShard_
            << ", nParticleShards = " << nParticleShards_ << nl
            << exit(FatalIOError);
    }

    if (nParticleShards_ > 1)
    {
        Info<< "    Particle shard " << particleShard_
            << " of " << nParticleShards_ << endl;
    }

    updateMesh();

    // Construct parcel diameters
    forAll(diameters_, i)
    {
        diameters_[i] = sizeDistribution_->sample();
    }

    // Determine volume of particles to inject
    this->volumeTotal_ = sum(pow3(diameters_))*pi/6.0;
}


template<class CloudType>
Foam::ManualInjection<CloudType>::ManualInjection
(
    const ManualInjection<CloudType>& im
)
:
    InjectionModel<CloudType>(im),
    positionsFile_(im.positionsFile_),
    positions_(im.positions_),
    diameters_(im.diameters_),
    injectorCells_(im.injectorCells_),
    injectorTetFaces_(im.injectorTetFaces_),
    injectorTetPts_(im.injectorTetPts_),
    U0_(im.U0_),
    sizeDistribution_(im.sizeDistribution_.clone()),
    ignoreOutOfBounds_(im.ignoreOutOfBounds_),
    nParticleShards_(im.nParticleShards_),
    particleShard_(im.particleShard_)
{}


// * * * * * * * * * * * * * * * * Destructor  * * * * * * * * * * * * * * * //

template<class CloudType>
Foam::ManualInjection<CloudType>::~ManualInjection()
{}


// * * * * * * * * * * * * * * * Member Functions  * * * * * * * * * * * * * //

template<class CloudType>
void Foam::ManualInjection<CloudType>::updateMesh()
{
    label nRejected = 0;
    label nShardRejected = 0;

    bitSet keep(positions_.size(), true);

    forAll(positions_, pI)
    {
        if (nParticleShards_ > 1 && (pI % nParticleShards_) != particleShard_)
        {
            keep.unset(pI);
            nShardRejected++;
            continue;
        }

        if
        (
            !this->findCellAtPosition
            (
                injectorCells_[pI],
                injectorTetFaces_[pI],
                injectorTetPts_[pI],
                positions_[pI],
                !ignoreOutOfBounds_
            )
        )
        {
            keep.unset(pI);
            nRejected++;
        }
    }

    if (nRejected + nShardRejected > 0)
    {
        inplaceSubset(keep, positions_);
        inplaceSubset(keep, diameters_);
        inplaceSubset(keep, injectorCells_);
        inplaceSubset(keep, injectorTetFaces_);
        inplaceSubset(keep, injectorTetPts_);

        if (nRejected > 0)
        {
            Info<< "    " << nRejected
                << " particles ignored, out of bounds" << endl;
        }
    }

    if (nShardRejected > 0)
    {
        Info<< "    " << nShardRejected
            << " particles assigned to other particle shards" << endl;
    }
}


template<class CloudType>
Foam::scalar Foam::ManualInjection<CloudType>::timeEnd() const
{
    // Injection is instantaneous - but allow for a finite interval to
    // avoid numerical issues when interval is zero
    return this->SOI_ + SMALL;
}


template<class CloudType>
Foam::label Foam::ManualInjection<CloudType>::parcelsToInject
(
    const scalar time0,
    const scalar time1
)
{
    if ((0.0 >= time0) && (0.0 < time1))
    {
        return positions_.size();
    }

    return 0;
}


template<class CloudType>
Foam::scalar Foam::ManualInjection<CloudType>::volumeToInject
(
    const scalar time0,
    const scalar time1
)
{
    // All parcels introduced at SOI
    if ((0.0 >= time0) && (0.0 < time1))
    {
        return this->volumeTotal_;
    }

    return 0.0;
}


template<class CloudType>
void Foam::ManualInjection<CloudType>::setPositionAndCell
(
    const label parcelI,
    const label,
    const scalar,
    vector& position,
    label& cellOwner,
    label& tetFacei,
    label& tetPti
)
{
    position = positions_[parcelI];
    cellOwner = injectorCells_[parcelI];
    tetFacei = injectorTetFaces_[parcelI];
    tetPti = injectorTetPts_[parcelI];
}


template<class CloudType>
void Foam::ManualInjection<CloudType>::setProperties
(
    const label parcelI,
    const label,
    const scalar,
    typename CloudType::parcelType& parcel
)
{
    // set particle velocity
    parcel.U() = U0_;

    // set particle diameter
    parcel.d() = diameters_[parcelI];
}


template<class CloudType>
bool Foam::ManualInjection<CloudType>::fullyDescribed() const
{
    return false;
}


template<class CloudType>
bool Foam::ManualInjection<CloudType>::validInjection(const label)
{
    return true;
}


// ************************************************************************* //
