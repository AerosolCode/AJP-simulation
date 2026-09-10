/*---------------------------------------------------------------------------*\
  Finite-radius wall deposition CloudFunctionObject
\*---------------------------------------------------------------------------*/

#ifndef finiteRadiusDeposition_H
#define finiteRadiusDeposition_H

#include "CloudFunctionObject.H"
#include "writeFile.H"
#include "cloudFunctionObjectTools.H"
#include "indexedOctree.H"
#include "treeDataFace.H"
#include "DynamicList.H"
#include "Switch.H"

namespace Foam
{

template<class CloudType>
class finiteRadiusDeposition
:
    public CloudFunctionObject<CloudType>,
    public functionObjects::writeFile
{
    typedef typename CloudType::parcelType parcelType;

    cloudFunctionObjectTools::collector collector_;
    word action_;
    scalar radiusFactor_;
    scalar absoluteTolerance_;
    label nBisection_;
    Switch log_;
    Switch resetOnStart_;

    autoPtr<indexedOctree<treeDataFace>> wallTreePtr_;
    DynamicList<string> records_;
    label nDeposited_;

    void operator=(const finiteRadiusDeposition<CloudType>&) = delete;

    void buildTree();

    scalar pointFaceDistance
    (
        const point& sample,
        const label facei,
        point& nearest
    ) const;

    scalar segmentFaceDistance
    (
        const point& start,
        const point& end,
        const label facei,
        scalar& segmentFraction,
        point& nearest
    ) const;

    bool firstContact
    (
        const point& start,
        const point& end,
        const scalar radius,
        scalar& fraction,
        label& facei,
        point& wallPoint
    ) const;

    virtual void write();

public:

    TypeName("finiteRadiusDeposition");

    finiteRadiusDeposition
    (
        const dictionary& dict,
        CloudType& owner,
        const word& modelName
    );

    finiteRadiusDeposition
    (
        const finiteRadiusDeposition<CloudType>& rhs
    );

    virtual autoPtr<CloudFunctionObject<CloudType>> clone() const
    {
        return autoPtr<CloudFunctionObject<CloudType>>
        (
            new finiteRadiusDeposition<CloudType>(*this)
        );
    }

    virtual ~finiteRadiusDeposition() = default;

    virtual bool postMove
    (
        parcelType& p,
        const scalar dt,
        const point& position0,
        const typename parcelType::trackingData& td
    );
};

} // End namespace Foam

#ifdef NoRepository
    #include "finiteRadiusDeposition.C"
#endif

#endif
