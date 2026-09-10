/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
License
    This file is part of OpenFOAM.

    OpenFOAM is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

\*---------------------------------------------------------------------------*/

#include "DistanceTrajectory.H"
#include "Pstream.H"
#include "ListListOps.H"
#include "polyPatch.H"

// * * * * * * * * * * * * * Private Member Functions  * * * * * * * * * * * //

template<class CloudType>
Foam::string Foam::DistanceTrajectory<CloudType>::parcelKey
(
    const parcelType& p
) const
{
    std::ostringstream os;
    os << static_cast<const void*>(&p);
    return string(os.str());
}


template<class CloudType>
typename Foam::DistanceTrajectory<CloudType>::parcelState&
Foam::DistanceTrajectory<CloudType>::state
(
    const parcelType& p,
    const point& position0,
    const scalar age0
)
{
    const string key = parcelKey(p);
    auto iter = states_.find(key);

    if (!iter)
    {
        parcelState ps;
        ps.id = nextParcelId_++;
        ps.lastPosition = position0;
        ps.lastAge = age0;

        states_.insert(key, ps);
        iter = states_.find(key);

        if (writeInitial_)
        {
            appendRecord(iter.val(), p, position0, age0, word("initial"));
        }
    }

    return iter.val();
}


template<class CloudType>
void Foam::DistanceTrajectory<CloudType>::appendRecord
(
    parcelState& ps,
    const parcelType& p,
    const point& position,
    const scalar age,
    const word& event
)
{
    OStringStream os;

    os  << this->owner().time().value() << tab
        << Pstream::myProcNo() << tab
        << ps.id << tab
        << ps.samplei++ << tab
        << age << tab
        << position.x() << tab
        << position.y() << tab
        << position.z() << tab
        << ps.distance << tab
        << p.cell() << tab
        << p.face() << tab
        << p.U().x() << tab
        << p.U().y() << tab
        << p.U().z() << tab
        << p.d() << tab
        << p.typeId() << tab
        << event;

    records_.append(os.str());
}


template<class CloudType>
void Foam::DistanceTrajectory<CloudType>::write()
{
    List<List<string>> procRecords(Pstream::nProcs());
    procRecords[Pstream::myProcNo()] = records_;
    Pstream::gatherList(procRecords);

    if (Pstream::master() && this->writeToFile())
    {
        OFstream& os = this->file();

        forAll(procRecords, proci)
        {
            forAll(procRecords[proci], i)
            {
                os << procRecords[proci][i].c_str() << nl;
            }
        }
    }

    records_.clearStorage();
}


// * * * * * * * * * * * * * * * * Constructors  * * * * * * * * * * * * * * //

template<class CloudType>
Foam::DistanceTrajectory<CloudType>::DistanceTrajectory
(
    const dictionary& dict,
    CloudType& owner,
    const word& modelName
)
:
    CloudFunctionObject<CloudType>(dict, owner, modelName, typeName),
    functionObjects::writeFile
    (
        owner,
        this->localPath(),
        typeName,
        this->coeffDict()
    ),
    interval_(this->coeffDict().getScalar("interval")),
    writeInitial_
    (
        this->coeffDict().template getOrDefault<Switch>
        (
            "writeInitial",
            true
        )
    ),
    writeOnPatch_
    (
        this->coeffDict().template getOrDefault<Switch>
        (
            "writeOnPatch",
            true
        )
    ),
    states_(),
    nextParcelId_(0),
    records_()
{
    if (interval_ <= 0)
    {
        FatalIOErrorInFunction(this->coeffDict())
            << "interval must be greater than zero" << nl
            << exit(FatalIOError);
    }

    if (Pstream::master() && this->writeToFile())
    {
        OFstream& os = this->file();

        this->writeCommented
        (
            os,
            "flowTime currentProc parcelId sample particleAge x y z "
            "distance cell face Ux Uy Uz d typeId event"
        );
        os << nl;
    }
}


template<class CloudType>
Foam::DistanceTrajectory<CloudType>::DistanceTrajectory
(
    const DistanceTrajectory<CloudType>& dt
)
:
    CloudFunctionObject<CloudType>(dt),
    writeFile(dt),
    interval_(dt.interval_),
    writeInitial_(dt.writeInitial_),
    writeOnPatch_(dt.writeOnPatch_),
    states_(dt.states_),
    nextParcelId_(dt.nextParcelId_),
    records_(dt.records_)
{}


// * * * * * * * * * * * * * * * Member Functions  * * * * * * * * * * * * * //

template<class CloudType>
bool Foam::DistanceTrajectory<CloudType>::postMove
(
    parcelType& p,
    const scalar dt,
    const point& position0,
    const typename parcelType::trackingData& td
)
{
    const scalar age0 = max(scalar(0), p.age() - dt);
    parcelState& ps = state(p, position0, age0);

    point position1 = p.position();
    scalar age1 = p.age();

    vector segment = position1 - ps.lastPosition;
    scalar segmentLength = mag(segment);

    while (segmentLength + SMALL >= interval_)
    {
        const scalar fraction = interval_/max(segmentLength, ROOTVSMALL);
        const point samplePosition = ps.lastPosition + fraction*segment;
        const scalar sampleAge = ps.lastAge + fraction*(age1 - ps.lastAge);

        ps.distance += interval_;
        appendRecord(ps, p, samplePosition, sampleAge, word("distance"));

        ps.lastPosition = samplePosition;
        ps.lastAge = sampleAge;

        segment = position1 - ps.lastPosition;
        segmentLength = mag(segment);
    }

    return true;
}


template<class CloudType>
bool Foam::DistanceTrajectory<CloudType>::postPatch
(
    const parcelType& p,
    const polyPatch& pp,
    const typename parcelType::trackingData& td
)
{
    if (writeOnPatch_)
    {
        parcelState& ps = state(p, p.position(), p.age());
        const scalar finalStep = mag(p.position() - ps.lastPosition);

        if (finalStep > SMALL)
        {
            ps.distance += finalStep;
            appendRecord(ps, p, p.position(), p.age(), word("patch"));
            ps.lastPosition = p.position();
            ps.lastAge = p.age();
        }
    }

    return true;
}


template<class CloudType>
void Foam::DistanceTrajectory<CloudType>::postEvolve
(
    const typename parcelType::trackingData& td
)
{
    write();
}


// ************************************************************************* //
