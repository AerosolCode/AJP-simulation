# Tool archive

The July 2026 one-off MOBO migration tools are preserved here and are not part
of the active start/stop workflow:

- `transition_to_mobo_202607.sh`
- `start_mobo_transition_202607.sh`

`legacy_202607/` contains the former scalar-BO rescoring and CFD diagnosis
scripts. Their conclusions and compact evidence have already been incorporated
into `reports/`. It also contains the former `ssh_config_xeon6_ajp` file, which
fixed one operator's login name and key path. The active dispatcher now builds
SSH targets from the Git-ignored `site.env` and shared host addresses.

Use `tools/start_bo_multihost.sh` and `tools/stop_bo_multihost.sh` for the
active campaign. Both obtain the work directory from
`bo_multihost_config.json` unless `AJP_CAMPAIGN_WORKDIR` is explicitly set.
