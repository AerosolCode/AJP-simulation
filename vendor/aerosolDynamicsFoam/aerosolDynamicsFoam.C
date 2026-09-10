/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2011-2016 OpenFOAM Foundation
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

Application
    aerosolDynamicsFoam

Group
    grpLagrangianSolvers

Description
    Transient one-way solver for the passive transport of a single kinematic
    particle cloud on a fixed, pre-calculated carrier-flow field.

    The carrier-flow equations are not solved and parcel source terms are not
    fed back to the carrier phase.

\*---------------------------------------------------------------------------*/

#include "fvCFD.H"
#include "singlePhaseTransportModel.H"
#include "turbulentTransportModel.H"
#include "basicKinematicCloud.H"

#include <cstdlib>

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

int main(int argc, char *argv[])
{
    argList::addNote
    (
        "Transient solver for the passive transport"
        " of a single kinematic particle cloud"
    );
    argList::addOption
    (
        "cloud",
        "name",
        "specify alternative cloud name. default is 'kinematicCloud'"
    );
    argList::addOption
    (
        "particleShard",
        "index",
        "track only parcels assigned to this particle shard"
    );
    argList::addOption
    (
        "nParticleShards",
        "n",
        "number of particle shards for replicated-mesh particle tracking"
    );
    argList::addBoolOption
    (
        "particleParallel",
        "split injected parcels over launcher ranks without mesh decomposition"
    );

    #include "postProcess.H"

    #include "addCheckCaseOptions.H"
    #include "setRootCaseLists.H"
    #include "createTime.H"
    #include "createMesh.H"
    #include "createControl.H"

    const bool particleParallel = args.found("particleParallel");

    auto envLabel = [](const char* name, const label defaultValue)
    {
        const string value(getEnv(name));

        if (value.empty())
        {
            return defaultValue;
        }

        return label(std::atoi(value.c_str()));
    };

    label particleShard = args.getOrDefault<label>("particleShard", 0);
    label nParticleShards = args.getOrDefault<label>("nParticleShards", 1);

    if (particleParallel)
    {
        if (!args.found("particleShard"))
        {
            particleShard = envLabel
            (
                "OMPI_COMM_WORLD_RANK",
                envLabel
                (
                    "PMI_RANK",
                    envLabel
                    (
                        "PMIX_RANK",
                        envLabel("SLURM_PROCID", 0)
                    )
                )
            );
        }

        if (!args.found("nParticleShards"))
        {
            nParticleShards = envLabel
            (
                "OMPI_COMM_WORLD_SIZE",
                envLabel
                (
                    "PMI_SIZE",
                    envLabel
                    (
                        "PMIX_SIZE",
                        envLabel("SLURM_NTASKS", 1)
                    )
                )
            );
        }

        Info<< "Particle-parallel replicated-mesh mode: shard "
            << particleShard << " of " << nParticleShards << nl
            << "    Use mpirun without OpenFOAM -parallel/decomposePar."
            << endl;
    }

    if (particleParallel || args.found("particleShard"))
    {
        setEnv
        (
            "FOAM_PARTICLE_SHARD",
            name(particleShard),
            true
        );
    }

    if (particleParallel || args.found("nParticleShards"))
    {
        setEnv
        (
            "FOAM_N_PARTICLE_SHARDS",
            name(nParticleShards),
            true
        );
    }

    #include "createFields.H"

    // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

    Info<< "\nStarting time loop\n" << endl;
    

    while (runTime.loop())
    {
        Info<< "Time = " << runTime.timeName() << nl << endl;

        Info<< "Evolving " << kinematicCloud.name() << endl;

        laminarTransport.correct();

        mu = laminarTransport.nu()*rhoInfValue;

        kinematicCloud.evolve();

        runTime.write();

        runTime.printExecutionTime(Info);

        if
        (
            kinematicCloud.solution().eventDriven()
         && kinematicCloud.solution().stopWhenCloudEmpty()
        )
        {
            const label nParcels =
                returnReduce(kinematicCloud.size(), sumOp<label>());

            if (!nParcels)
            {
                Info<< "No parcels remain; stopping event-driven tracking"
                    << nl << endl;
                break;
            }
        }
    }

    Info<< "End\n" << endl;

    return 0;
}


// ************************************************************************* //
