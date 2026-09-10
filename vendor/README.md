# Vendored solver source

`aerosolDynamicsFoam/` is a source snapshot of
<https://github.com/AerosolCode/aerosolDynamicsFoam.git> at upstream commit
`5c0f5880f7bcac11aaf203f1066d1dd85298314a`.

The AJP simulation branch also tracks its local `KinematicParcel.C/.H`
modifications in this parent repository. Keeping the snapshot as ordinary
vendored files, rather than an unconfigured nested Git repository, ensures that
a normal clone of AJP-simulation contains the exact solver source used by the
particle workflow.

Generated `Make/linux*` and `lnInclude/` products remain excluded by the
vendored `.gitignore`.
