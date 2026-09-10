#include "finiteRadiusDeposition.H"

#include "Pstream.H"
#include "ListListOps.H"
#include "polyBoundaryMesh.H"
#include "linePointRef.H"
#include "pointHit.H"

template<class CloudType>
void Foam::finiteRadiusDeposition<CloudType>::buildTree()
{
    const polyMesh& mesh = this->owner().mesh();
    const labelList& patchIDs = collector_.IDs();

    label nFaces = 0;
    for (const label patchi : patchIDs)
    {
        nFaces += mesh.boundaryMesh()[patchi].size();
    }

    labelList wallFaces(nFaces);
    label faceCount = 0;
    for (const label patchi : patchIDs)
    {
        const polyPatch& pp = mesh.boundaryMesh()[patchi];
        forAll(pp, patchFacei)
        {
            wallFaces[faceCount] = pp.start() + patchFacei;
            ++faceCount;
        }
    }

    treeBoundBox bounds(mesh.points());
    bounds.grow(max(ROOTVSMALL, 1e-9*max(bounds.mag(), scalar(1))));

    wallTreePtr_.reset
    (
        new indexedOctree<treeDataFace>
        (
            treeDataFace(true, mesh, wallFaces),
            bounds,
            8,
            10,
            3.0
        )
    );
}


template<class CloudType>
Foam::scalar Foam::finiteRadiusDeposition<CloudType>::pointFaceDistance
(
    const point& sample,
    const label facei,
    point& nearest
) const
{
    const polyMesh& mesh = this->owner().mesh();
    const pointHit hit = mesh.faces()[facei].nearestPoint(sample, mesh.points());
    nearest = hit.point();
    return mag(sample - nearest);
}


template<class CloudType>
Foam::scalar Foam::finiteRadiusDeposition<CloudType>::segmentFaceDistance
(
    const point& start,
    const point& end,
    const label facei,
    scalar& segmentFraction,
    point& nearest
) const
{
    const polyMesh& mesh = this->owner().mesh();
    const face& f = mesh.faces()[facei];
    const pointField& points = mesh.points();
    const vector displacement = end - start;
    const scalar lengthSqr = magSqr(displacement);

    scalar minDistance = GREAT;
    segmentFraction = 0;
    nearest = Zero;

    if (lengthSqr > VSMALL)
    {
        const pointHit intersection = f.intersection
        (
            start,
            displacement,
            mesh.faceCentres()[facei],
            points,
            intersection::HALF_RAY
        );

        if (intersection.hit() && intersection.distance() <= 1)
        {
            nearest = intersection.point();
            segmentFraction = min
            (
                scalar(1),
                max(scalar(0), ((nearest - start) & displacement)/lengthSqr)
            );
            return 0;
        }
    }

    point facePoint;
    scalar distance = pointFaceDistance(start, facei, facePoint);
    if (distance < minDistance)
    {
        minDistance = distance;
        segmentFraction = 0;
        nearest = facePoint;
    }

    distance = pointFaceDistance(end, facei, facePoint);
    if (distance < minDistance)
    {
        minDistance = distance;
        segmentFraction = 1;
        nearest = facePoint;
    }

    if (lengthSqr > VSMALL)
    {
        const linePointRef segment(start, end);
        forAll(f, fp)
        {
            const label next = f.fcIndex(fp);
            const linePointRef edge(points[f[fp]], points[f[next]]);
            point onSegment;
            point onEdge;
            distance = segment.nearestDist(edge, onSegment, onEdge);

            if (distance < minDistance)
            {
                minDistance = distance;
                segmentFraction = min
                (
                    scalar(1),
                    max
                    (
                        scalar(0),
                        ((onSegment - start) & displacement)/lengthSqr
                    )
                );
                nearest = onEdge;
            }
        }
    }

    return minDistance;
}


template<class CloudType>
bool Foam::finiteRadiusDeposition<CloudType>::firstContact
(
    const point& start,
    const point& end,
    const scalar radius,
    scalar& fraction,
    label& facei,
    point& wallPoint
) const
{
    if (!wallTreePtr_.valid())
    {
        return false;
    }

    const point boxMin
    (
        min(start.x(), end.x()),
        min(start.y(), end.y()),
        min(start.z(), end.z())
    );
    const point boxMax
    (
        max(start.x(), end.x()),
        max(start.y(), end.y()),
        max(start.z(), end.z())
    );
    treeBoundBox searchBox(boxMin, boxMax);
    searchBox.grow(radius + ROOTVSMALL);
    const labelList candidates = wallTreePtr_->findBox(searchBox);
    const treeDataFace& shapes = wallTreePtr_->shapes();

    bool found = false;
    fraction = GREAT;
    facei = -1;

    for (const label shapei : candidates)
    {
        const label candidateFacei = shapes.objectIndex(shapei);
        scalar minimumFraction = 0;
        point nearestAtMinimum;
        const scalar minimumDistance = segmentFaceDistance
        (
            start,
            end,
            candidateFacei,
            minimumFraction,
            nearestAtMinimum
        );

        if (minimumDistance > radius || minimumFraction >= fraction)
        {
            continue;
        }

        scalar lo = 0;
        scalar hi = minimumFraction;
        point nearest;

        scalar startDistance = pointFaceDistance(start, candidateFacei, nearest);
        if (startDistance <= radius)
        {
            hi = 0;
        }
        else
        {
            for (label iter = 0; iter < nBisection_; ++iter)
            {
                const scalar mid = 0.5*(lo + hi);
                const point sample = start + mid*(end - start);
                const scalar distance = pointFaceDistance
                (
                    sample,
                    candidateFacei,
                    nearest
                );

                if (distance <= radius)
                {
                    hi = mid;
                }
                else
                {
                    lo = mid;
                }
            }
        }

        if (hi < fraction)
        {
            found = true;
            fraction = hi;
            facei = candidateFacei;
            const point centre = start + fraction*(end - start);
            (void)pointFaceDistance(centre, facei, wallPoint);
        }
    }

    return found;
}


template<class CloudType>
void Foam::finiteRadiusDeposition<CloudType>::write()
{
    this->setModelProperty("nDeposited", nDeposited_);

    List<List<string>> procRecords(Pstream::nProcs());
    procRecords[Pstream::myProcNo()] = records_;
    Pstream::gatherList(procRecords);

    if (Pstream::master() && this->writeToFile())
    {
        OFstream& os = this->file();
        forAll(procRecords, proci)
        {
            forAll(procRecords[proci], recordi)
            {
                os << procRecords[proci][recordi].c_str() << nl;
            }
        }
    }

    records_.clearStorage();
}


template<class CloudType>
Foam::finiteRadiusDeposition<CloudType>::finiteRadiusDeposition
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
    collector_(this->coeffDict(), owner.mesh()),
    action_(this->coeffDict().getWord("action")),
    radiusFactor_(this->coeffDict().getScalar("radiusFactor")),
    absoluteTolerance_(this->coeffDict().getScalar("absoluteTolerance")),
    nBisection_(this->coeffDict().getLabel("nBisection")),
    log_(this->coeffDict().template getOrDefault<Switch>("log", false)),
    resetOnStart_
    (
        this->coeffDict().template getOrDefault<Switch>("resetOnStart", true)
    ),
    wallTreePtr_(nullptr),
    records_(),
    nDeposited_(0)
{
    if (action_ != "remove")
    {
        FatalIOErrorInFunction(this->coeffDict())
            << "Only action remove is supported; got " << action_ << nl
            << exit(FatalIOError);
    }
    if (radiusFactor_ < 0 || absoluteTolerance_ < 0 || nBisection_ < 1)
    {
        FatalIOErrorInFunction(this->coeffDict())
            << "radiusFactor and absoluteTolerance must be non-negative, "
            << "and nBisection must be positive" << nl
            << exit(FatalIOError);
    }

    buildTree();

    if (!resetOnStart_)
    {
        nDeposited_ = this->template getModelProperty<label>("nDeposited");
    }

    if (Pstream::master() && this->writeToFile())
    {
        OFstream& os = this->file();
        this->writeCommented
        (
            os,
            "flowTime currentProc patch face origProc origId typeId nParticle "
            "d radius centerX centerY centerZ wallX wallY wallZ"
        );
        os << nl;
    }

    if (log_)
    {
        Info<< "    finiteRadiusDeposition patches: "
            << flatOutput(collector_.names()) << ", radiusFactor="
            << radiusFactor_ << ", absoluteTolerance="
            << absoluteTolerance_ << nl;
    }
}


template<class CloudType>
Foam::finiteRadiusDeposition<CloudType>::finiteRadiusDeposition
(
    const finiteRadiusDeposition<CloudType>& rhs
)
:
    CloudFunctionObject<CloudType>(rhs),
    writeFile(rhs),
    collector_(rhs.collector_),
    action_(rhs.action_),
    radiusFactor_(rhs.radiusFactor_),
    absoluteTolerance_(rhs.absoluteTolerance_),
    nBisection_(rhs.nBisection_),
    log_(rhs.log_),
    resetOnStart_(rhs.resetOnStart_),
    wallTreePtr_(nullptr),
    records_(rhs.records_),
    nDeposited_(rhs.nDeposited_)
{
    buildTree();
}


template<class CloudType>
bool Foam::finiteRadiusDeposition<CloudType>::postMove
(
    parcelType& p,
    const scalar dt,
    const point& position0,
    const typename parcelType::trackingData& td
)
{
    const scalar radius = radiusFactor_*p.d() + absoluteTolerance_;
    if (radius <= 0)
    {
        return true;
    }

    scalar fraction;
    label facei;
    point wallPoint;
    const point position1 = p.position();

    if (!firstContact(position0, position1, radius, fraction, facei, wallPoint))
    {
        return true;
    }

    const point centre = position0 + fraction*(position1 - position0);
    const label patchi = this->owner().mesh().boundaryMesh().whichPatch(facei);
    const word& patchName = this->owner().mesh().boundaryMesh()[patchi].name();
    const scalar eventTime = this->owner().time().value() - (1 - fraction)*dt;

    OStringStream os;
    os  << eventTime << tab
        << Pstream::myProcNo() << tab
        << patchName << tab
        << facei << tab
        << p.origProc() << tab
        << p.origId() << tab
        << p.typeId() << tab
        << p.nParticle() << tab
        << p.d() << tab
        << radius << tab
        << centre.x() << tab << centre.y() << tab << centre.z() << tab
        << wallPoint.x() << tab << wallPoint.y() << tab << wallPoint.z();
    records_.append(os.str());

    p.position() = centre;
    ++nDeposited_;

    if (log_)
    {
        Info<< "    finite-radius deposition: patch=" << patchName
            << " origProc=" << p.origProc() << " origId=" << p.origId()
            << " d=" << p.d() << " centre=" << centre << nl;
    }

    return false;
}
