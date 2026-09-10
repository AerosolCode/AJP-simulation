# aerosolDynamicsFoam

## English

`aerosolDynamicsFoam` is a one-way Lagrangian particle tracking solver for a
fixed, precomputed incompressible carrier-flow field.  It does not solve the
carrier-flow equations and does not feed parcel source terms back to the
Eulerian phase.  The solver is intended for cases such as impactor calculations,
where many particle sizes and injection locations are tracked through a fixed
flow field.

### Build

Load the OpenFOAM v2406 environment and build the local Lagrangian library and
solver.

```bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc
wmake lagrangian/intermediate
wmake
```

In restricted environments, the compilation may succeed but the final link can
fail when writing to `$WM_PROJECT_USER_DIR/platforms/...`.  In that case, the
failure is an output-permission problem, not necessarily a C++ compilation
error.

### Basic Run

Run the solver on an undecomposed case:

```bash
aerosolDynamicsFoam -case testImpactor
```

The default cloud name is `kinematicCloud`.  A different cloud name can be
selected with:

```bash
aerosolDynamicsFoam -case <case> -cloud <cloudName>
```

The corresponding cloud dictionary is `<cloudName>Properties`.

### Replicated-Mesh Particle Parallel Mode

The solver provides a replicated-mesh particle-parallel mode:

```bash
mpirun -np 8 aerosolDynamicsFoam -case testImpactor -particleParallel
```

This is not standard OpenFOAM mesh decomposition.  Do not use `decomposePar`,
`reconstructPar`, or the OpenFOAM `-parallel` option with this mode.  Each rank
reads the full mesh and carrier field, while the injected parcels are split
among particle shards.  This avoids processor-patch migration for particles and
is well suited to fixed-flow, one-way particle tracking.

Rank and shard counts are normally detected from MPI launcher environment
variables such as `OMPI_COMM_WORLD_RANK`, `PMI_RANK`, `PMIX_RANK`, and
`SLURM_PROCID`.  They can also be specified manually:

```bash
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 0 -nParticleShards 4
```

For debugging, the shards can be run one at a time without MPI:

```bash
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 0 -nParticleShards 2
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 1 -nParticleShards 2
```

In particle-parallel mode, outputs are written under shard-specific cloud names:

```text
<time>/lagrangian/kinematicCloud_shard0
<time>/lagrangian/kinematicCloud_shard1
postProcessing/lagrangian/kinematicCloud_shard0
postProcessing/lagrangian/kinematicCloud_shard1
```

Post-processing files such as `ParticlePostProcessing` `.dat` files must be
merged across `kinematicCloud_shard*` directories.  This mode does not create
`processor*` directories, so standard `reconstructPar` is not the merge path.

### Event-Driven Tracking

For fixed-flow particle tracking, the cloud can be advanced over a prescribed
physical tracking horizon without repeatedly looping the Eulerian time:

```text
solution
{
    eventDriven          true;
    eventTrackTime       <physicalTrackingTime>;
    deltaTMax            <maxParticleStep>;
    stopWhenCloudEmpty   false;
}
```

`deltaTMax` limits the internal particle tracking step.  It should not be made
too large when wall impacts, cell crossings, stochastic dispersion, or random
forces are important.  With `stopWhenCloudEmpty true`, event-driven tracking
stops once all shards have no remaining parcels.

### Distance-Based Trajectory Output

The `distanceTrajectory` cloud function writes trajectory samples when a parcel
has moved by a prescribed distance, independent of `controlDict.writeInterval`:

```text
cloudFunctions
{
    trajectoryByDistance
    {
        type          distanceTrajectory;
        interval      1e-5;       // [m]
        writeInitial  true;       // optional, default true
        writeOnPatch  true;       // optional, default true
    }
}
```

The output is written as
`postProcessing/lagrangian/<cloud>/trajectoryByDistance/<startTime>/distanceTrajectory.dat`.
Columns include `parcelId`, `sample`, `particleAge`, `x y z`, cumulative
`distance`, `U`, `d`, `typeId`, and an `event` flag (`initial`, `distance`, or
`patch`).  The `parcelId` is run-local and should be interpreted within each
cloud/shard output file.

### Analytic Position Tracking

For small particles with short relaxation times, updating velocity analytically
but moving the parcel with an explicit `U_old*dt` displacement can produce
noticeable errors in wall-hit position and hit time.  The optional analytic
position update uses a frozen-coefficient displacement:

```text
solution
{
    analyticPositionTracking true;
}
```

Within a cell, the particle velocity is approximated by

```text
dU/dt = alpha - beta U
```

and the displacement is computed from the analytic integral of this velocity.
The implementation still uses the existing straight-line `trackToFace` geometry
for face crossing, but the hit time is re-evaluated from the analytic
displacement when a face is reached.  With `analyticPositionTracking false`, the
solver uses the legacy displacement behavior, which is useful for regression
checks against OpenFOAM's `icoUncoupledKinematicParcelFoam`.

### Benchmark Summary

A detailed benchmark report is available in
[`benchmarkResults.tex`](benchmarkResults.tex).  The main benchmark case is
`testImpactor`, with particle diameters from `0.10` to `1.00 um`.

Key findings:

- `analyticPositionTracking true` reduces the coarse-step bias in the
  outlet/substrate split and allows larger particle steps to be used with less
  loss of fate accuracy.
- The most sensitive particle sizes in the tested impactor case are on the
  small-particle side, especially `0.10-0.40 um`, with some localized
  sensitivity near `0.85 um`.
- With `analyticPositionTracking false`, the custom solver recovers the legacy
  behavior of OpenFOAM's `icoUncoupledKinematicParcelFoam` at fine time steps.
  In the benchmark, the `1e-7 s` case matched the baseline patch-fate counts.
- Standard OpenFOAM cell-decomposition parallelism did not speed up the
  `icoUncoupledKinematicParcelFoam` benchmark for this fixed-flow particle
  problem.  Four-way mesh decomposition was essentially the same speed as
  serial execution.
- Replicated-mesh particle sharding is a better fit for this workload because
  it directly divides the dominant particle work and avoids particle migration
  across processor patches.  A two-shard check was nearly ideal for a
  particle-dominated benchmark.

Important caveats:

- Replicated-mesh particle sharding increases memory use roughly in proportion
  to the number of ranks because every rank stores the full mesh and carrier
  fields.
- Sharded output must be merged in post-processing.
- Particle sharding is most effective when the parcel count is large enough to
  dominate MPI launch, mesh reading, and output costs.
- Standard cell decomposition can still be appropriate for a coupled solver or
  an expensive Eulerian flow solve, but it is not the natural first choice for
  this fixed-flow, one-way particle-tracking solver.

## 日本語

`aerosolDynamicsFoam` は、固定済みの非圧縮流れ場を使って粒子だけを追跡する
1-way Lagrangian particle tracking solver です。流体方程式は解かず、粒子から
流体側への source term の戻しも行いません。

## ビルド

OpenFOAM v2406 の環境を読み込んでから、ローカルの Lagrangian ライブラリと
solver をビルドします。

```bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc
wmake lagrangian/intermediate
wmake
```

制限付き環境では、`wmake` が C++ のコンパイルまでは通っても、最後に
`$WM_PROJECT_USER_DIR/platforms/...` へ実行ファイルを書けずに失敗することが
あります。その場合は C++ エラーではなく、出力先の権限エラーです。

## 通常実行

通常は undecomposed case に対してそのまま実行します。

```bash
aerosolDynamicsFoam -case testImpactor
```

cloud 名のデフォルトは `kinematicCloud` です。別名を使う場合は次のようにします。

```bash
aerosolDynamicsFoam -case <case> -cloud <cloudName>
```

この場合、読み込まれる cloud properties は `<cloudName>Properties` です。

## 粒子並列実行

この solver には、メッシュを各 rank に複製し、粒子だけを分担する
replicated-mesh particle parallel mode があります。

```bash
mpirun -np 8 aerosolDynamicsFoam -case testImpactor -particleParallel
```

これは OpenFOAM 標準の領域分割並列ではありません。`decomposePar`、
`reconstructPar`、OpenFOAM の `-parallel` option は使いません。各 rank は同じ
full mesh と carrier field を読み、注入粒子だけを shard に分けて追跡します。

通常は MPI launcher の環境変数から rank と総 rank 数を自動検出します。
対応している主な環境変数は `OMPI_COMM_WORLD_RANK`, `PMI_RANK`, `PMIX_RANK`,
`SLURM_PROCID` などです。手動指定もできます。

```bash
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 0 -nParticleShards 4
```

デバッグ時は、MPI を使わずに shard を1つずつ走らせることもできます。

```bash
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 0 -nParticleShards 2
aerosolDynamicsFoam -case testImpactor -particleParallel -particleShard 1 -nParticleShards 2
```

## 出力

通常実行では、従来どおり `kinematicCloud` に出力されます。

```text
<time>/lagrangian/kinematicCloud
postProcessing/lagrangian/kinematicCloud
```

`-particleParallel` では、shard ごとに cloud 名を分けて出力します。

```text
<time>/lagrangian/kinematicCloud_shard0
<time>/lagrangian/kinematicCloud_shard1
postProcessing/lagrangian/kinematicCloud_shard0
postProcessing/lagrangian/kinematicCloud_shard1
```

`U`, `rho`, `mu`, `phi`, turbulence field などの carrier field は、複数 rank が
同じ Eulerian field を同時に書かないよう、`-particleParallel` 時には書き出しを
抑制しています。一方で、`kinematicCloud_shard0:UTrans` のような shard 名付きの
cloud source field は出ることがあります。

## postProcessing の扱い

`ParticlePostProcessing` の `.dat` は shard ごとに分かれて出ます。解析時には
次のようなディレクトリ以下を後処理で結合してください。

```text
postProcessing/lagrangian/kinematicCloud_shard*/...
```

結合時は、header は1つだけ残し、データ行を結合します。必要であれば時刻列などで
sort してください。この粒子並列モードでは `processor*` ディレクトリを作らないため、
標準の `reconstructPar` で結合する方式ではありません。

## eventDriven tracking

インパクタのように、上流の広い流路で速度変化が小さい場合は `eventDriven` が有効です。
cloud の `solution` dictionary に以下を設定します。

```text
eventDriven          true;
eventTrackTime       <physicalTrackingTime>;
deltaTMax            <maxParticleStep>;
stopWhenCloudEmpty   false;
```

`deltaTMax` は内部の粒子追跡時間幅の上限です。セル通過、壁面到達、乱流分散、
ランダム力を扱う場合に重要なので、大きくしすぎないでください。

`stopWhenCloudEmpty true` にすると、全 shard の粒子が消えた時点で計算を終了します。
十分な tracking horizon を与える場合の無駄な空回しを減らせます。

## 変位ベースの軌跡出力

`distanceTrajectory` cloud function を使うと、`controlDict.writeInterval` ではなく、
粒子が指定距離だけ進んだタイミングで軌跡点を出力できます。

```text
cloudFunctions
{
    trajectoryByDistance
    {
        type          distanceTrajectory;
        interval      1e-5;       // [m]
        writeInitial  true;       // optional, default true
        writeOnPatch  true;       // optional, default true
    }
}
```

出力先は
`postProcessing/lagrangian/<cloud>/trajectoryByDistance/<startTime>/distanceTrajectory.dat`
です。列には `parcelId`, `sample`, `particleAge`, `x y z`, 累積 `distance`, `U`,
`d`, `typeId`, `event` (`initial`, `distance`, `patch`) が含まれます。`parcelId` は
実行中の cloud/shard 内での ID として扱ってください。

## 高速化のための実装メモ

この solver では、固定済み carrier field 上で多数の粒子を流す用途を想定して、
計算時間を減らすためにいくつかの変更を入れています。

まず、流体場は解き直さず、`U`, `p`, `rho`, `mu`, turbulence field などを読み込んで
粒子だけを進めます。粒子から carrier 側への source term は戻さないため、
粒子間・粒子流体間の強い双方向結合を解く用途ではなく、インパクタの捕集効率や
粒径依存の通過・付着を見る用途に寄せています。

次に、通常の OpenFOAM 領域分割ではなく、replicated-mesh particle parallel mode で
粒子だけを shard に分けます。メッシュを分割しないので粒子が processor patch を
またぐ通信を避けられ、粒子数が多いケースでは実装と後処理が単純になります。
一方で、各 rank が full mesh を持つため、メモリ使用量は rank 数に比例します。

さらに、`eventDriven` tracking を使うと、carrier の `deltaT` に縛られず、
粒子を指定した物理時間まで一気に追跡できます。固定流れ場で粒子だけを多数流す場合、
Eulerian time loop の回数を減らせるので効果が大きいです。

## 解析変位 tracking

短い粒子緩和時間を持つ小径粒子では、速度更新だけを解析的に扱っても、
位置の tracking に `U_old*dt` を使うと、壁面到達位置や到達時刻に誤差が出やすくなります。
そのため、オプションで位置更新にも frozen-coefficient の解析変位を使えるようにしています。

```text
solution
{
    analyticPositionTracking true;
}
```

有効時は、各セル内で force coefficient を凍結し、

```text
dU/dt = alpha - beta U
```

の解析解から `dx = integral(U(t), t=0..dt)` を計算します。その変位長が
`maxCo*cellLength` を大きく超えないように粒子ごとの tracking substep を選び、
既存の `trackToFace` で face 交差を処理します。

注意点として、face 検出の幾何は既存の直線 tracking を使っています。したがって、
完全な曲線軌道と face 平面の交差を解いているわけではありません。ただし、face に
当たった場合は、直線 chord 上の到達割合をそのまま時間割合とはみなさず、
解析変位長から hit time を再評価します。これにより、短い緩和時間での
`U_old*dt` 由来の位置誤差を抑えます。

`analyticPositionTracking false` の場合は従来挙動で、tracking 変位は基本的に
現在速度から作られます。比較用や既存ケースとの互換性を優先する場合は false のまま
使えます。

## 時間刻みと粒径感度

ベンチマークでは、`analyticPositionTracking true` にすると、粒子 fate
そのものは比較的大きな `deltaT` でも安定しやすいことを確認しています。一方で、
到達時刻や到達位置の差は、escape/stick の境界に近い粒径で目立ちます。

今回の `testImpactor` では、感度が出やすいのは主にサブミクロン側です。

```text
0.10 - 0.42 um : outlet と substrate が混在しやすい
0.53 - 0.85 um : 到達位置差が比較的大きい
>= 1 um        : 多くは substrate 側で、fate は比較的変わりにくい
```

そのため、高速化の検証では大粒径だけでなく、少なくとも `0.1-1 um` を厚めに残して
比較してください。特に `0.5-0.9 um` 付近は、捕集・通過の境界確認に効きやすいです。

`deltaT` を粗くした時の確認では、最終 fate だけでなく、patch 到達時刻と到達位置も
比較してください。fate が一致していても、境界近傍では到達位置の差が後続の判定に
効く可能性があります。

## 現在の確認結果

現状ソースに対して以下を確認しました。

```bash
wmake lagrangian/intermediate
wmake
```

`wmake lagrangian/intermediate` は成功しました。solver 本体も C++ コンパイルは成功し、
最後の production binary へのリンクだけが、この実行環境の filesystem 制限で
止まりました。そのため、検証用に `/tmp/aerosolDynamicsFoam-current` へ一時リンクして
実行確認しました。

`testImpactor` の一時コピーに対して、以下の shard-equivalent test は成功しています。

```bash
/tmp/aerosolDynamicsFoam-current -case <tmpCase> -particleParallel -particleShard 0 -nParticleShards 2
/tmp/aerosolDynamicsFoam-current -case <tmpCase> -particleParallel -particleShard 1 -nParticleShards 2
```

現在の `testImpactor` では各 shard が 1500 parcels を担当し、
`kinematicCloud_shard0` と `kinematicCloud_shard1` に分かれて出力されることを確認しました。

なお、この制限付き実行環境では直接の `mpirun` は solver 起動前に PMIx の listener
socket 作成で失敗しました。これは MPI runtime 側の環境制限であり、上記の shard
検証では solver の粒子分割、出力分離、終了処理は正常でした。

## 注意点

- 各 rank が full mesh と carrier field を持つため、メモリ使用量は概ね rank 数に比例します。
- 粒子数が少ない場合、rank 数を増やしすぎると固定費が勝って遅くなることがあります。
- `-particleParallel` は OpenFOAM の `-parallel` と併用しません。
- 書き出し頻度を高くしすぎると、計算より I/O が支配的になります。
- random force や stochastic dispersion を使う場合、shard ごとに異なる乱数 seed を使います。
