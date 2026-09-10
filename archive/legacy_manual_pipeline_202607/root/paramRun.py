import pandas as pd
#import subprocess
import os
#import time

#MAX_RUN = 3

START_CASE = 0
END_CASE = 127

df = pd.read_csv("baseparams.csv")

for i in range(START_CASE, END_CASE + 1):

    row = df.iloc[i]

    dirname = row["case"]

    print(f"preparing : {dirname}")

    os.makedirs(dirname, exist_ok=True)

    with open(os.path.join(dirname, "params.dat"), "w") as f:

        for col in df.columns:

            if col == "case":
                continue

            f.write(f"{col}={row[col]:.8f}\n")

    os.system(f"cp -r base/* {dirname}/")
    os.system(
        f"cd {dirname} && sbatch run.sh"
    )

print("all jobs submitted")