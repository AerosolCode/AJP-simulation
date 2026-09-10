# AJP-simulation

> **Start here / 最初に読む文書:** 現行手法、開発経緯、有限半径のさえぎり、完了事項、
> 次の作業は [総合現状・計算手法・移行計画（PDF）](reports/ajp_project_status_ja.pdf) に
> 集約しています。編集用正本は
> [TeX source](reports/ajp_project_status_ja.tex) です。

An OpenFOAM-based CFD and particle-tracking simulation pipeline for evaluating AJP (Aerosol Jet Printing) nozzles. It runs many nozzle geometries/conditions (cases) in parallel on a SLURM cluster to obtain evaluation metrics such as deposition efficiency and overspray.

Currently this pipeline is operated as the **low-fidelity** leg of a multi-fidelity Bayesian optimization framework (a separate high-fidelity pipeline is run in parallel).

## One-time setup for each user

The shared campaign files do not contain a Linux login name or a user-specific
home-directory path. After cloning the repository on XEON6, each user creates one
local file:

```bash
cp site.env.example site.env
${EDITOR:-vi} site.env
python3 tools/check_site_config.py --config bo_multihost_config.json
```

Only the following site values normally need editing:

- `AJP_MASTER_PYTHON` — Python used by the XEON6 coordinator
- `AJP_SSH_USER_XEON1`, `AJP_SSH_USER_XEON4`, `AJP_SSH_USER_XEON5` —
  SSH login name for each remote host; these may all be different
- `AJP_WORKER_ROOT_XEON6`, `AJP_WORKER_ROOT_XEON1`,
  `AJP_WORKER_ROOT_XEON4`, `AJP_WORKER_ROOT_XEON5` — the absolute per-user
  worker area on each host

`site.env` is ignored by Git, so personal paths and login names are not committed.
The shared [site.env.example](site.env.example), [bo_config.json](bo_config.json),
and [bo_multihost_config.json](bo_multihost_config.json) remain unchanged when a
different student runs the same campaign. Host addresses and scientific settings
remain in the shared configuration.

Before the first run, install the matching tracked worker template as
`worker-env.sh` under that host's `AJP_WORKER_ROOT_<HOST>`. For example, on
XEON1 use `tools/worker-envs/xeon1.sh`; use the correspondingly named file on the
other hosts. The dispatcher injects the selected host's root into each Slurm
job. The templates use `$HOME` and `$AJP_WORKER_ROOT`, but OpenFOAM paths are
host-specific and must be checked whenever the cluster software changes. Build
`finiteRadiusDeposition` separately under each host's solver environment.

## Pipeline overview

1. **Candidate generation and dispatch** — [bo_loop.py](bo_loop.py) / [tools/bo_multihost.py](tools/bo_multihost.py)
   The constrained multi-objective BO creates each `case_XXXX` from [base/](base/) and dispatches independent Slurm jobs to the four configured hosts.

2. **CFD** — [base/run.sh](base/run.sh)
   Production always uses the structured [mesh generator](base/meshGen2.py). The former unstructured generator is archived at [archive/mesh/meshGen2_unstructured.py](archive/mesh/meshGen2_unstructured.py). The flow sequence is structured mesh → `gmshToFoam` → boundary conditions → `potentialFoam -initialiseUBCs -writep` → `simpleFoam`. `residualControl` can stop converged cases before the 10,000-iteration ceiling.

3. **Particle tracking** — [baseparticle/loopaerosolDynamics.sh](baseparticle/loopaerosolDynamics.sh)
   After CFD completion, the coordinator copies [baseparticle/](baseparticle/) and submits four replicated-mesh particle shards. The template loads `finiteRadiusDeposition`, preserves the wedge mesh, and stops at 95% resolved parcels or the case-specific horizon `min(5 s, max(0.5 s, 3*T_transit))`.

4. **Collection and next proposal**
   The coordinator retrieves `particle_fates_all.csv`, evaluates the three objectives and two constraints, updates `bo_observations.csv`, and proposes the next constrained qLogNEHVI batch.

## Bayesian optimization loop

[bo_loop.py](bo_loop.py) and [tools/bo_multihost.py](tools/bo_multihost.py) provide the closed-loop low-fidelity BO driver. XEON6 runs the persistent coordinator:

Prepare a fresh initial design without submitting jobs:

```bash
python3 tools/bo_multihost.py --config bo_multihost_config.json \
  init --initial-batch 32 --prepare-only
```

On XEON6, from the repository clone:

```bash
./tools/start_bo_multihost.sh
python3 tools/bo_multihost.py --config bo_multihost_config.json status
```

It prepares cases, submits CFD/particle jobs, collects `particle_fates_all.csv`, writes `bo_observations.csv`, and proposes asynchronous candidates with constrained BoTorch `qLogNEHVI`. The three objectives are target capture fraction, target precision, and target-centered deposition compactness. Resolved fraction and nozzle-wall deposition are feasibility constraints. XEON6 centrally coordinates independent Slurm workers on XEON6, XEON1, XEON4, and XEON5. The dispatcher has finite evaluation-budget and Pareto-hypervolume stagnation termination conditions. Install the CPU candidate-generation dependencies with `python -m pip install -r requirements-mobo.txt`. See the [current Japanese report](reports/ajp_project_status_ja.pdf) for the exact method, validation status, and operating cautions.

## Directory structure

- `base/` — CFD case template (mesh generation, boundary conditions, solver settings)
- `baseparticle/` — particle-tracking case template
- `bo_config.json`, `bo_multihost_config.json` — active fresh-campaign configuration
- `site.env.example` — tracked per-user configuration template; `site.env` is ignored
- `tests/` — source-level regression tests; keep and run these
- `test_cases/` — disposable/generated OpenFOAM validation output
- `tools/` — active runtime, host setup, and validation utilities
- `archive/` — pre-reset configuration, legacy scripts, and generated-case evidence
- `archive/mesh/` — archived unstructured mesh generator; not used in production

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

---

# AJP-simulation（日本語版）

AJP（Aerosol Jet Printing）ノズルの評価を目的とした、OpenFOAMベースのCFD・粒子追跡シミュレーションパイプラインです。SLURMクラスタ上で多数のノズル形状・条件（ケース）を並列に実行し、堆積効率やオーバースプレーなどの評価指標を得ることを目指しています。

現状はマルチフィデリティ・ベイズ最適化フレームワークの**低フィデリティ**計算として運用しています（高フィデリティ計算は別途並行して実行）。

## 利用者ごとの初回設定

共有するcampaign設定には、Linuxのユーザー名や利用者固有のhome directoryを直接書きません。
XEON6でrepositoryをcloneしたあと、各利用者がローカル設定を1つだけ作成します。

```bash
cp site.env.example site.env
${EDITOR:-vi} site.env
python3 tools/check_site_config.py --config bo_multihost_config.json
```

通常、変更するのは次の利用者固有値だけです。

- `AJP_MASTER_PYTHON` — XEON6 coordinatorが使うPython
- `AJP_SSH_USER_XEON1`、`AJP_SSH_USER_XEON4`、`AJP_SSH_USER_XEON5` —
  remote hostごとのSSH login名。3台で異なる値も指定可能
- `AJP_WORKER_ROOT_XEON6`、`AJP_WORKER_ROOT_XEON1`、
  `AJP_WORKER_ROOT_XEON4`、`AJP_WORKER_ROOT_XEON5` — hostごとの利用者用worker領域の絶対path

`site.env`はGit管理外なので、個人のpathやlogin名をcommitしません。利用者が変わっても、
共有する[site.env.example](site.env.example)、[bo_config.json](bo_config.json)、
[bo_multihost_config.json](bo_multihost_config.json)は変更しません。host addressと計算条件は
共有設定に残します。

初回実行前に、各hostで対応する`tools/worker-envs/<host>.sh`を、そのhostの
`AJP_WORKER_ROOT_<HOST>`直下へ`worker-env.sh`として配置します。dispatcherは選択したhostの
worker rootを各Slurm jobへ渡します。template中の利用者pathは`$HOME`と`$AJP_WORKER_ROOT`
から決まりますが、OpenFOAM pathはhost固有なので、cluster softwareの更新時には確認が
必要です。`finiteRadiusDeposition`は各hostのsolver環境で個別buildします。

## パイプライン概要

1. **候補生成・分散投入** — [bo_loop.py](bo_loop.py) / [tools/bo_multihost.py](tools/bo_multihost.py)
   制約付き多目的BOが[base/](base/)から`case_XXXX`を作り、設定された4ホストの独立Slurmへ投入します。

2. **CFD本体** — [base/run.sh](base/run.sh)
   productionでは常にstructured版の [meshGen2.py](base/meshGen2.py) を使います。旧unstructured版は [archive/mesh/](archive/mesh/) に退避済みです。structured mesh → `gmshToFoam` → 境界条件生成 → `potentialFoam -initialiseUBCs -writep` → `simpleFoam` の順に実行し、収束時は`residualControl`、未収束時は最大10,000反復で停止します。

3. **粒子追跡** — [baseparticle/loopaerosolDynamics.sh](baseparticle/loopaerosolDynamics.sh)
   CFD完了後、coordinatorが[baseparticle/](baseparticle/)をコピーし、複製mesh上の4 particle shardを投入します。有限半径さえぎりをloadし、wedgeを保持したまま、95%解決またはケース別上限`min(5 s, max(0.5 s, 3*T_transit))`まで追跡します。

4. **回収・次候補提案**
   coordinatorが`particle_fates_all.csv`を回収し、3目的2制約を評価して`bo_observations.csv`を更新し、制約付きqLogNEHVIで次batchを提案します。

## ベイズ最適化ループ

[bo_loop.py](bo_loop.py) と [tools/bo_multihost.py](tools/bo_multihost.py) が低フィデリティ計算用の閉ループ BO を構成します。XEON6で常駐コーディネーターを起動・確認します。

ジョブを投入せず、新規初期設計だけを準備します。

```bash
python3 tools/bo_multihost.py --config bo_multihost_config.json \
  init --initial-batch 32 --prepare-only
```

XEON6上でrepositoryのdirectoryへ移動して実行します。

```bash
./tools/start_bo_multihost.sh
python3 tools/bo_multihost.py --config bo_multihost_config.json status
```

ケース作成、CFD/粒子追跡投入、`particle_fates_all.csv` の回収、`bo_observations.csv` の更新、制約付きqLogNEHVIによる次候補生成までを行います。3目的はtarget捕集率、target precision、target中心compactness、2制約は解決率とノズル壁面沈着率です。XEON6がマスターとなり、XEON6、XEON1、XEON4、XEON5の独立Slurmへケースを配分して一元管理します。数式、有限半径のさえぎり、検証状況、次作業は [現行総合報告](reports/ajp_project_status_ja.pdf) を参照してください。

## ディレクトリ構成

- `base/` — CFDケースのテンプレート（メッシュ生成・境界条件・ソルバー設定）
- `baseparticle/` — 粒子追跡ケースのテンプレート
- `bo_config.json`, `bo_multihost_config.json` — 新規campaign用の現行設定
- `site.env.example` — 利用者固有設定の雛形。コピー後の`site.env`はGit管理外
- `tests/` — 保持・実行すべきソース回帰テスト
- `test_cases/` — 再生成可能なOpenFOAM検証ケースの出力先
- `tools/` — 現行runtime、host構築、検証用utility
- `archive/` — reset前の設定、旧script、生成ケース証跡
- `archive/mesh/` — 旧unstructured mesh生成器（productionでは不使用）

## ライセンス

このプロジェクトは [GNU General Public License v3.0](LICENSE) の下で公開されています。
