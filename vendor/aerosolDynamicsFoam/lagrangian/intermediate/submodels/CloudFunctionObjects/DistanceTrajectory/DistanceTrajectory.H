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

#ifndef DistanceTrajectory_H
#define DistanceTrajectory_H

#include "CloudFunctionObject.H"
#include "writeFile.H"
#include "HashTable.H"
#include "DynamicList.H"

#include <sstream>

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

namespace Foam
{

/*---------------------------------------------------------------------------*\
                       Class DistanceTrajectory Declaration
\*---------------------------------------------------------------------------*/

template<class CloudType>
class DistanceTrajectory
:
    public CloudFunctionObject<CloudType>,
    public functionObjects::writeFile
{
    // Private Data

        //- Convenience typedef for parcel type
        typedef typename CloudType::parcelType parcelType;

        struct parcelState
        {
            label id;
            label samplei;
            point lastPosition;
            scalar lastAge;
            scalar distance;

            parcelState()
            :
                id(-1),
                samplei(0),
                lastPosition(Zero),
                lastAge(0),
                distance(0)
            {}
        };

        //- Distance between trajectory samples [m]
        scalar interval_;

        //- Write the injection/first-seen position
        Switch writeInitial_;

        //- Write patch-hit/end positions even when not at the interval
        Switch writeOnPatch_;

        //- Parcel states keyed by the parcel object address
        HashTable<parcelState, string> states_;

        //- Next run-local parcel id
        label nextParcelId_;

        //- Buffered records awaiting collective write
        DynamicList<string> records_;


    // Private Member Functions

        //- No copy assignment
        void operator=(const DistanceTrajectory<CloudType>&) = delete;

        //- String key for the current parcel object
        string parcelKey(const parcelType& p) const;

        //- Lookup or create state for parcel
        parcelState& state
        (
            const parcelType& p,
            const point& position0,
            const scalar age0
        );

        //- Append a single output record
        void appendRecord
        (
            parcelState& ps,
            const parcelType& p,
            const point& position,
            const scalar age,
            const word& event
        );

        //- Write buffered records
        virtual void write();


public:

    //- Runtime type information
    TypeName("distanceTrajectory");


    // Constructors

        //- Construct from dictionary
        DistanceTrajectory
        (
            const dictionary& dict,
            CloudType& owner,
            const word& modelName
        );

        //- Copy construct
        DistanceTrajectory(const DistanceTrajectory<CloudType>& dt);

        //- Construct and return a clone
        virtual autoPtr<CloudFunctionObject<CloudType>> clone() const
        {
            return autoPtr<CloudFunctionObject<CloudType>>
            (
                new DistanceTrajectory<CloudType>(*this)
            );
        }


    //- Destructor
    virtual ~DistanceTrajectory() = default;


    // Member Functions

        // Evaluation

            //- Post-move hook
            virtual bool postMove
            (
                parcelType& p,
                const scalar dt,
                const point& position0,
                const typename parcelType::trackingData& td
            );

            //- Post-patch hook
            virtual bool postPatch
            (
                const parcelType& p,
                const polyPatch& pp,
                const typename parcelType::trackingData& td
            );

            //- Post-evolve hook
            virtual void postEvolve
            (
                const typename parcelType::trackingData& td
            );
};


// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

} // End namespace Foam

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

#ifdef NoRepository
    #include "DistanceTrajectory.C"
#endif

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

#endif

// ************************************************************************* //
