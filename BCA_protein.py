from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

# ===================================================
# raw_df 示例
# 我这里没有 样品体积，需要这一列计算后面的稀释方法
# ===================================================
	id	volume_ul	conc	abs
0	1	20	0.00000	0.107
1	2	20	0.03125	0.149
2	3	20	0.06250	0.173
3	4	20	0.12500	0.229
4	5	20	0.20000	0.449
5	6	20	0.25000	0.308
6	7	20	0.40000	0.403
7	8	20	0.50000	0.539
8	wc30_G_1	2	NaN	0.483
9	wc30_G_2	2	NaN	0.528
10	wc30_G_31	2	NaN	0.495
11	wc30_WT	2	NaN	0.516
## 读取数据
DATA_FILE = "bca_data.xlsx"
OUTPUT_DIR = Path(".")


# 1. Read data and split into standard/sample dataframes.
# If your data is CSV, replace this with: raw_df = pd.read_csv(DATA_FILE)
## 必须有 样本 id，加样体积（ul），浓度（标准品有，样品无），吸光度,样品体积 5列，列名可以任意，但必须包含这些信息。
## 加样体积标准品 一般是 20ul，样品是 1-20 ul，要填写
raw_df = pd.read_excel(DATA_FILE)

raw_df = raw_df.rename(
    columns={
        "id": "id",
        "体积": "volume_ul",
        "浓度": "conc",
        "吸光度": "abs",
        "样品体积": "sample_volume_ul",
    }
)

raw_df["conc"] = pd.to_numeric(raw_df["conc"], errors="coerce")
raw_df["abs"] = pd.to_numeric(raw_df["abs"], errors="coerce")
raw_df["volume_ul"] = pd.to_numeric(raw_df["volume_ul"], errors="coerce")
if "sample_volume_ul" in raw_df.columns:
    raw_df["sample_volume_ul"] = pd.to_numeric(
        raw_df["sample_volume_ul"], errors="coerce"
    )

## 拆分标曲和样品
standard_df = raw_df.loc[raw_df["conc"].notna(), ["id", "volume_ul", "conc", "abs"]].copy()
sample_columns = ["id", "volume_ul", "abs"]
if "sample_volume_ul" in raw_df.columns:
    sample_columns.append("sample_volume_ul")
sample_df = raw_df.loc[raw_df["conc"].isna(), sample_columns].copy()
sample_df = sample_df.rename(columns={"id": "sample"})


### 这里可以踢掉标曲中的离群值重新跑
# Choose the standard points used for fitting here.
# Start with all points. After checking the plot, subset this dataframe directly.
fit_standard_df = standard_df.copy()

# Example: exclude standard point id == 5
# fit_standard_df = standard_df.loc[standard_df["id"] != 5].copy()

# Example: keep only standards with concentration <= 0.4
# fit_standard_df = standard_df.loc[standard_df["conc"] <= 0.4].copy()


# 2. Fit standard curve.
def fit_standard_curve(standard_df):
    """Fit a linear BCA standard curve.

    Parameters
    ----------
    standard_df : pandas.DataFrame
        Standard curve dataframe used for fitting. It must contain ``conc`` and
        ``abs`` columns. Subset this dataframe before calling the function if
        you want to remove outliers.

    Returns
    -------
    model : sklearn.linear_model.LinearRegression
        Fitted linear regression model.
    fit_df : pandas.DataFrame
        Copy of the input dataframe with ``fitted_abs`` and ``residual`` added.
    fit_info : dict
        Dictionary with slope, intercept, R2, and number of fitted points.
    """
    if len(standard_df) < 2:
        raise ValueError("At least two standard points are needed for linear fitting.")

    fit_df = standard_df.copy()
    x = fit_df[["conc"]].to_numpy()
    y = fit_df["abs"].to_numpy()

    model = LinearRegression()
    model.fit(x, y)

    fit_df["fitted_abs"] = model.predict(x)
    fit_df["residual"] = fit_df["abs"] - fit_df["fitted_abs"]

    fit_info = {
        "slope": float(model.coef_[0]),
        "intercept": float(model.intercept_),
        "r2": float(r2_score(y, fit_df["fitted_abs"])),
        "n_points": int(len(fit_df)),
    }

    return model, fit_df, fit_info


model, standard_fit_df, fit_info = fit_standard_curve(fit_standard_df)


# 3. Calculate sample concentration from the fitted curve.
def calc_sample_conc(sample_df, model, final_volume_ul=20.0):
    """Calculate original sample concentrations from BCA absorbance.

    Parameters
    ----------
    sample_df : pandas.DataFrame
        Sample dataframe with ``abs`` and ``volume_ul`` columns. Extra columns,
        such as ``sample_volume_ul``, are preserved in the output.
    model : sklearn.linear_model.LinearRegression
        Fitted standard curve model from :func:`fit_standard_curve`.
    final_volume_ul : float, optional
        Final sample volume in the BCA well before adding BCA working reagent.
        The default is 20.0.

    Returns
    -------
    result_df : pandas.DataFrame
        Sample dataframe with ``diluted_conc``, ``dilution_factor``, and
        ``original_conc`` added.
    """
    slope = float(model.coef_[0])
    intercept = float(model.intercept_)
    if slope == 0:
        raise ValueError("The fitted standard curve has a slope of zero.")

    result_df = sample_df.copy()
    result_df["diluted_conc"] = (result_df["abs"] - intercept) / slope
    result_df["dilution_factor"] = final_volume_ul / result_df["volume_ul"]
    result_df["original_conc"] = result_df["diluted_conc"] * result_df["dilution_factor"]

    return result_df


sample_result_df = calc_sample_conc(sample_df, model, final_volume_ul=20.0)


def calc_loading_mix(
    sample_conc_df,
    target_conc,
    loading_buffer_fold,
    conc_col="original_conc",
    sample_volume_col="sample_volume_ul",
):
    """Calculate loading buffer and dilution buffer volumes.

    Parameters
    ----------
    sample_conc_df : pandas.DataFrame
        Sample concentration dataframe, usually the output of
        :func:`calc_sample_conc`. It must contain a concentration column and a
        sample volume column.
    target_conc : float
        Target final protein concentration after adding dilution buffer and
        loading buffer. Use the same concentration unit as ``conc_col``.
    loading_buffer_fold : float
        Fold concentration of the loading buffer, for example 5 for 5X loading
        buffer. The calculated final loading buffer concentration is 1X.
    conc_col : str, optional
        Column containing the original sample concentration. The default is
        ``original_conc``.
    sample_volume_col : str, optional
        Column containing the sample volume to use for loading preparation, in
        microliters. The default is ``sample_volume_ul``.

    Returns
    -------
    result_df : pandas.DataFrame
        Copy of ``sample_conc_df`` with ``target_conc``, ``protein_amount``,
        ``final_volume_ul``, ``loading_buffer_ul``, ``dilution_buffer_ul``, and
        ``loading_mix_feasible`` added.
    """
    if loading_buffer_fold <= 1:
        raise ValueError("loading_buffer_fold must be greater than 1.")
    if target_conc <= 0:
        raise ValueError("target_conc must be greater than 0.")

    result_df = sample_conc_df.copy()
    result_df["target_conc"] = target_conc
    result_df["protein_amount"] = (
        result_df[conc_col] * result_df[sample_volume_col]
    )
    result_df["final_volume_ul"] = result_df["protein_amount"] / target_conc
    result_df["loading_buffer_ul"] = (
        result_df["final_volume_ul"] / loading_buffer_fold
    )
    result_df["dilution_buffer_ul"] = (
        result_df["final_volume_ul"]
        - result_df[sample_volume_col]
        - result_df["loading_buffer_ul"]
    )
    result_df["loading_mix_feasible"] = result_df["dilution_buffer_ul"] >= 0

    return result_df


# Set your target concentration and uncomment this block when needed.
# loading_mix_df = calc_loading_mix(
#     sample_result_df,
#     target_conc=1.0,
#     loading_buffer_fold=5,
# )
# print("Loading mix:")
# print(loading_mix_df)


#====================================================
# 画图
#====================================================

# 4. Plot standard curve and residuals.
used_index = standard_fit_df.index
excluded_standard_df = standard_df.loc[~standard_df.index.isin(used_index)].copy()

x_min = 0
x_max = max(standard_df["conc"].max(), sample_result_df["diluted_conc"].max()) * 1.05
x_line = np.linspace(x_min, x_max, 200)
y_line = model.predict(x_line.reshape(-1, 1))

fig, (ax_curve, ax_residual) = plt.subplots(1, 2, figsize=(12, 5))

ax_curve.scatter(
    standard_fit_df["conc"],
    standard_fit_df["abs"],
    color="tab:blue",
    label="standard used for fit",
)
ax_curve.plot(
    x_line,
    y_line,
    color="black",
    label=(
        f"Abs = {fit_info['slope']:.4f} * Conc + {fit_info['intercept']:.4f}\n"
        f"R2 = {fit_info['r2']:.4f}"
    ),
)

if not excluded_standard_df.empty:
    ax_curve.scatter(
        excluded_standard_df["conc"],
        excluded_standard_df["abs"],
        color="tab:red",
        marker="x",
        s=80,
        label="standard not used for fit",
    )

ax_curve.scatter(
    sample_result_df["diluted_conc"],
    sample_result_df["abs"],
    color="tab:green",
    marker="s",
    label="sample",
)

for _, row in standard_df.iterrows():
    ax_curve.annotate(
        str(row["id"]),
        (row["conc"], row["abs"]),
        xytext=(5, 5),
        textcoords="offset points",
    )

for _, row in sample_result_df.iterrows():
    ax_curve.annotate(
        row["sample"],
        (row["diluted_conc"], row["abs"]),
        xytext=(5, -12),
        textcoords="offset points",
    )

ax_curve.set_xlabel("Concentration")
ax_curve.set_ylabel("Absorbance")
ax_curve.set_title("BCA standard curve")
ax_curve.legend()

ax_residual.axhline(0, color="black", linewidth=1)
ax_residual.scatter(
    standard_fit_df["conc"],
    standard_fit_df["residual"],
    color="tab:blue",
    label="standard used for fit",
)

if not excluded_standard_df.empty:
    excluded_standard_df["fitted_abs"] = model.predict(
        excluded_standard_df[["conc"]].to_numpy()
    )
    excluded_standard_df["residual"] = (
        excluded_standard_df["abs"] - excluded_standard_df["fitted_abs"]
    )
    ax_residual.scatter(
        excluded_standard_df["conc"],
        excluded_standard_df["residual"],
        color="tab:red",
        marker="x",
        s=80,
        label="standard not used for fit",
    )

for _, row in standard_fit_df.iterrows():
    ax_residual.annotate(
        str(row["id"]),
        (row["conc"], row["residual"]),
        xytext=(5, 5),
        textcoords="offset points",
    )

for _, row in excluded_standard_df.iterrows():
    ax_residual.annotate(
        str(row["id"]),
        (row["conc"], row["residual"]),
        xytext=(5, 5),
        textcoords="offset points",
    )

ax_residual.set_xlabel("Concentration")
ax_residual.set_ylabel("Residual absorbance")
ax_residual.set_title("Residual plot")
ax_residual.legend()

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "bca_standard_curve.png", dpi=300)
plt.show()


print("Fit information:")
print(fit_info)
print()
print("Sample concentrations:")
print(sample_result_df)

# standard_fit_df.to_csv(OUTPUT_DIR / "bca_standard_fit.csv", index=False)
# sample_result_df.to_csv(OUTPUT_DIR / "bca_sample_concentration.csv", index=False)
