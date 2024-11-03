#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Oct 31 17:34:40 2024

@author: simon
"""

import functions as fx
import pandas as pd
from scipy.optimize import curve_fit
import numpy as np
import pickle

df = fx.get_serl_data("Figure_21")
df["date"] = pd.to_datetime(df["summary_time"], format = "%b-%y")
df["month"] = df["date"].dt.month
df["month_dum"] = np.where(df["month"] < 7, df["month"] + 6, df["month"] - 6)
df["days_per_month"] = df["date"].dt.days_in_month
df["monthly_total"] = df["days_per_month"] * df["value"]
df = df.rename(columns={"segment_1_value": "floor_area"}).sort_values(by = ["floor_area", "month_dum"])
df["cum_value"] = df.groupby(["floor_area"])["monthly_total"].cumsum()
df["cum_days"] = df.groupby(["floor_area"])["days_per_month"].cumsum()
df["cum_value_norm"] = df.groupby(["floor_area"])["monthly_total"].transform(lambda x: (x.cumsum() / x.sum()))
   
starting_values = [10/np.mean(df["cum_days"]), np.mean(df["cum_value_norm"]), np.mean(df["cum_days"]), 2]
bounds = (0, [1, 2, 200, 3])
gas_from_day_popt, gas_from_day_pcov = curve_fit(fx.gen_log_model, df["cum_days"], df["cum_value_norm"], p0 = starting_values, bounds = bounds)
   
tdf = df.groupby(["floor_area"]).agg({"mean_floor_area": "min", "monthly_total": "sum"})
starting_values = [np.max(tdf["mean_floor_area"]), 1]
total_from_area_popt, total_from_area_pcov = curve_fit(fx.pow_model, tdf["mean_floor_area"], tdf["monthly_total"],p0 = starting_values)
   
odf = fx.get_serl_data("Figure_14")
odf = odf.loc[odf["fuel"] == "Gas"]
odf = odf.dropna(subset = ["mean_occupants"])
starting_values = [odf["mean_occupants"].max(),(odf["mean_occupants"].max() - odf["mean_occupants"].min()) / odf["mean_occupants"].max(), (3/(odf["mean_floor_area"].max()-odf["mean_floor_area"].min()))]
area_from_occup_popt, area_from_occup_pcov = curve_fit(fx.exp_model,odf["mean_occupants"], odf["mean_floor_area"], p0 = starting_values)
   
df = df.dropna(subset = ["mean_occupants"])
starting_values = [df["mean_occupants"].max(), (df["mean_occupants"].max() - df["mean_occupants"].min()) / df["mean_occupants"].max(), (3/(df["mean_floor_area"].max()-df["mean_floor_area"].min()))]
occup_from_area_popt, occup_from_area_pcov = curve_fit(fx.exp_model, df["mean_floor_area"], df["mean_occupants"], p0 = starting_values)

pars = {}

pars["gas_from_day_popt"] = gas_from_day_popt
pars["gas_from_day_pcov"] = gas_from_day_pcov
pars["total_from_area_popt"] = total_from_area_popt
pars["total_from_area_pcov"] = total_from_area_pcov
pars["occup_from_area_popt"] = occup_from_area_popt
pars["occup_from_area_pcov"] = occup_from_area_pcov
pars["area_from_occup_popt"] = area_from_occup_popt
pars["area_from_occup_pcov"] = area_from_occup_pcov

with open("fitted_models.pkl", "wb") as f:
    pickle.dump(pars, f)