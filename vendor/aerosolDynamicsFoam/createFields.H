#include "readGravitationalAcceleration.H"

const IOobject::writeOption carrierWriteOption =
    args.found("particleParallel") ? IOobject::NO_WRITE : IOobject::AUTO_WRITE;

Info<< "Reading field U\n" << endl;
volVectorField U
(
    IOobject
    (
        "U",
        runTime.timeName(),
        mesh,
        IOobject::MUST_READ,
        carrierWriteOption
    ),
    mesh
);

#include "createPhi.H"

singlePhaseTransportModel laminarTransport(U, phi);

dimensionedScalar rhoInfValue
(
    "rhoInf",
    dimDensity,
    laminarTransport
);

volScalarField rhoInf
(
    IOobject
    (
        "rho",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        carrierWriteOption
    ),
    mesh,
    rhoInfValue
);

autoPtr<incompressible::turbulenceModel> turbulence
(
    incompressible::turbulenceModel::New(U, phi, laminarTransport)
);

volScalarField mu
(
    IOobject
    (
        "mu",
        runTime.timeName(),
        mesh,
        IOobject::NO_READ,
        carrierWriteOption
    ),
    laminarTransport.nu()*rhoInfValue
);

const word kinematicCloudName
(
    args.getOrDefault<word>("cloud", "kinematicCloud")
);

Info<< "Constructing kinematicCloud " << kinematicCloudName << endl;
basicKinematicCloud kinematicCloud
(
    kinematicCloudName,
    rhoInf,
    U,
    mu,
    g
);

if (args.found("particleParallel"))
{
    #define suppressRegisteredFieldWrites(Type)                              \
        for (const word& fieldName : mesh.names<Type>())                     \
        {                                                                    \
            mesh.lookupObjectRef<Type>(fieldName).writeOpt                   \
            (                                                                \
                IOobject::NO_WRITE                                           \
            );                                                               \
        }

    suppressRegisteredFieldWrites(volScalarField);
    suppressRegisteredFieldWrites(volVectorField);
    suppressRegisteredFieldWrites(volSphericalTensorField);
    suppressRegisteredFieldWrites(volSymmTensorField);
    suppressRegisteredFieldWrites(volTensorField);
    suppressRegisteredFieldWrites(surfaceScalarField);
    suppressRegisteredFieldWrites(surfaceVectorField);

    #undef suppressRegisteredFieldWrites
}
