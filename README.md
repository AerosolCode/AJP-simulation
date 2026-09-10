# AJP-simulation — BOの実行手順

環境は利用者が準備済みであることを前提に、初期条件を生成し、CFD・粒子計算・結果回収・次候補生成を一段ずつ実行します。以下はすべてリポジトリ直下で実行します。

## 条件数と世代の数え方

**現在の既定値は「初期32条件、追加8条件」で、1世代32条件に固定されてはいません。** このREADMEでは、初期128条件を評価した後、1世代32条件ずつ追加する例を示します。件数は毎回コマンドで明示し、既定値は変更していません。

| 項目 | 件数の指定箇所 | 現在の既定値 | この手順での指定 |
| --- | --- | --- | --- |
| 初期条件数 | `init --initial-batch` | 32 | 128 |
| 1回に追加する条件数 | `suggest --batch-size` | 8 | 32 |
| BOモデルを使い始める有効観測数 | `bo_config.json` の `bo.gp_min_points` | 32 | 変更しない |
| BO内部の獲得関数の分割評価数 | `bo.acq_batch_size` | 128 | 変更しない。生成条件数ではない |

`bo_candidates.csv` の `generation` は初期生成が0、その後は `suggest` を1回実行するごとに1増えます。「世代」は候補生成のまとまりであり、同時に実行するジョブ数ではありません。

## 1. 計算を始める前に

利用するPythonでNumPy・Gmshと [requirements-mobo.txt](requirements-mobo.txt) の依存パッケージを使えるようにし、OpenFOAM・Slurm・MPI・互換性のある粒子solverを準備してください。環境設定ファイルの作成や読み込みは不要です。ジョブは投入元の環境を引き継ぐので、計算ノードでも同じPATH・ライブラリ・作業ディレクトリを利用できる状態にします。

粒子solver本体は同梱していません。有限半径のさえぎりライブラリは残しているため、使用するsolverと同じOpenFOAM環境で、別途build済みのsolverソースを指定して作成します。

```bash
# /absolute/path/to/aerosolDynamicsFoam は手元のsolverソースの絶対パスへ置換
bash baseparticle/build_custom.sh /absolute/path/to/aerosolDynamicsFoam
```

外部solverには、`liboneWayIntermediate` と必要なヘッダを備え、`-particleParallel`・`-nParticleShards` とwedge反射に対応した改修版が必要であり、標準solverへそのまま置き換えることはできません。生成した `baseparticle/custom/finiteRadiusDeposition/lib/libfiniteRadiusDeposition.so` は粒子ケースへコピーされます。

共有する計算条件は [bo_config.json](bo_config.json) の形状範囲・目的関数・制約・乱数seedで指定します。CFDと粒子計算のSlurm資源指定は、それぞれ `base/run.sh` と `baseparticle/loopaerosolDynamics.sh` の `#SBATCH` 行を確認してください。条件やテンプレートは初期生成前に確認し、途中で評価条件を変えないでください。

## 2. 初期128条件を生成する

新しい計算を始めるときに、一度だけ実行します。

```bash
python3 bo_loop.py --config bo_config.json init --initial-batch 128
python3 bo_loop.py --config bo_config.json status
```

初期条件は、`bo_config.json` の範囲と形状制約を満たす候補から、条件間の距離を広げるmaximin法で選びます。この時点ではCFD・粒子計算は実行しません。

既定の保存先は次のとおりです。初期128条件は `case_0000`〜`case_0127`、`generation=0` になります。

```text
campaigns/manual_structured_finite_radius/
├── bo_config_snapshot.json  # 開始時の設定の控え
├── bo_candidates.csv        # 候補の条件・世代・生成手法
├── bo_observations.csv      # collect後に作成される評価結果
├── case_0000/
│   ├── params.dat          # CFDへ渡す具体的な形状・流量条件
│   ├── run.sh              # CFD実行スクリプト
│   └── baseparticle/       # 粒子投入時に準備されるケース
└── case_0001/ ... case_0127/
```

初期生成をやり直す場合は、既存結果を消さずに別の保存先を指定します。例えば `--config bo_config.json --workdir campaigns/run02 init --initial-batch 128` とし、その計算に関する以後の全コマンドにも同じ `--workdir campaigns/run02` を付けます。実行時の設定は `--config` で指定したJSONを読むため、開始時の控えがあっても元のJSONを途中で書き換えないでください。

## 3. CFDを実行する

以下は最初の2条件を選ぶ例です。`--cases` の後を実際に計算したいケース名へ置き換えます。まず `--dry-run` で確認してから投入してください。

```bash
python3 bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001 --dry-run
python3 bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001

squeue -u "$USER"
python3 bo_loop.py --config bo_config.json status
```

各ケースの `log.potentialFoam`・`log.simpleFoam` と `CFD_DONE` を確認し、CFDの成功を待って次へ進みます。structuredメッシュを使い、残差停止した場合も最新のCFD時刻の流れ場を粒子計算へ渡します。

## 4. 粒子計算を実行する

CFDが成功したケースを指定します。この操作で各ケース内に `baseparticle/` を準備し、粒子計算を投入します。

```bash
python3 bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001 --dry-run
python3 bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001

squeue -u "$USER"
python3 bo_loop.py --config bo_config.json status
```

各ケースの `baseparticle/` 内のログと `PARTICLE_DONE` を確認し、終了を待ちます。

## 5. 結果を回収する

```bash
python3 bo_loop.py --config bo_config.json \
  collect --cases case_0000 case_0001
python3 bo_loop.py --config bo_config.json status
```

`bo_observations.csv` に目的関数・制約などの評価結果が追記されます。回収済みケースは再度追加されません。手順3〜5を繰り返し、初期128条件の評価を終えます。

投入・回収コマンドの `--cases` を省略すると、全候補のうちその段階の対象になるケースを処理します。投入では多数のジョブが送られ得るため、クラスタの利用制限に合わせてケースを選んでください。

## 6. BOで次の32条件を生成する

初期評価を回収したら、次を実行します。

```bash
python3 bo_loop.py --config bo_config.json suggest --batch-size 32
```

上記の初期128条件の続きなら、`case_0128`〜`case_0159` が `generation=1` として追加されます。生成した32条件について手順3〜5を実行し、回収が終わってから再び `suggest --batch-size 32` を実行します。次は `generation=2` の32条件です。`init` は再実行しません。

`suggest` はその時点までに回収した有効観測から制約付き多目的BO（qLogNEHVI）で候補を提案します。有効観測が32件未満ならmaximin法を使います。依存パッケージの不足やモデル計算の失敗時もmaximinへ切り替わるため、標準エラーと `bo_candidates.csv` の `method` を確認してください。`maximin_mobo_fallback` はBOモデルによる提案ではありません。

この手順では「1世代の計算・回収を終えてから次世代を生成する」運用にします。`suggest` 自体は未完了ケースがあっても実行できるため、終了待ちや次世代へ進む判断は利用者が行います。候補生成だけを繰り返しても、計算・回収をしなければBOの学習データは増えません。

## 計算に失敗したとき

`status` に `cfd_failed` または `particle_failed` が出たら、該当ケースのログを確認します。再試行する場合は、ジョブが終了していることを確認し、回収前に原因を修正して該当段階の `CFD_FAILED` または `PARTICLE_FAILED` 印だけを取り除いてから再投入します。失敗として記録する場合は `collect` します。

強制終了では失敗印が残らない場合もあるため、Slurmの `sacct` でも確認してください。キューを確認できないときは、重複投入を防ぐため投入コマンドは停止します。

Licensed under [GNU GPL v3.0](LICENSE).
