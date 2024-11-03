import pickle
import copy
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
from statsmodels.formula.api import ols
from scipy.optimize import curve_fit

plots = {}

def get_serl_data(figure):
	req = requests.get('https://rdr.ucl.ac.uk/ndownloader/files/35857037')
	df = pd.read_excel(req.content,sheet_name=figure,skiprows=1)
	return(df)

def log_model(x, a, b, c, m):
    return (a + c / (1 + np.exp(-b * (x-m))))

def gen_log_model(x, b, c, m, t):
    return (c / (1 + t * np.exp(-b*(x-m)))**1/t )

def pow_model(x, a, b):
    return (a * x**b)

def exp_model(x,a,b,c):
	return (a * (1-b * np.exp(-c*x)))

df = get_serl_data("Figure_21")
df["date"] = pd.to_datetime(df["summary_time"],format="%b-%y")
df["month"] = df["date"].dt.month
df["month_dum"] = np.where(df["month"] < 8, df["month"] + 5, df["month"] - 7)
df["days_per_month"] = df["date"].dt.days_in_month
df["monthly_total"] = df["days_per_month"] * df["value"]
df = df.rename(columns={"segment_1_value": "floor_area"}).sort_values(by=["floor_area","month_dum"])
df["cum_value"] = df.groupby(["floor_area"])["monthly_total"].cumsum()
df["cum_days"] = df.groupby(["floor_area"])["days_per_month"].cumsum()
cum_fig = px.scatter(df, x="cum_days", y="cum_value", color="floor_area",category_orders={"floor_area": ["50 or less", "50 to 100", "100 to 150", "150to 200", "Over 200"]})
cum_fig.update_layout(xaxis_title="Days",yaxis_title="Gas use (kWh)")
plots["cum_fig"] = cum_fig

df["cum_value_norm"] = df.groupby(["floor_area"])["monthly_total"].transform(lambda x: (x.cumsum()/x.sum()))
cum_norm_fig = px.scatter(df, x="cum_days", y="cum_value_norm", color="floor_area")
cum_norm_fig.update_layout(xaxis_title="Days",yaxis_title="Fraction of annual gas use")
plots["cum_norm_fig"] = copy.deepcopy(cum_norm_fig)

starting_values = [0,10/np.mean(df["cum_days"]),np.mean(df["cum_value_norm"]),np.mean(df["cum_days"])]
bounds = (0, [1, 1, 2, 200])
popt, pcov = curve_fit(log_model, df["cum_days"], df["cum_value_norm"],p0=starting_values,bounds=bounds)
residuals = df["cum_value_norm"]- log_model(df["cum_days"], *popt)
ss_res = np.sum(residuals**2)
rmse = np.mean(residuals**2)**0.5
ss_tot = np.sum((df["cum_value_norm"]-np.mean(df["cum_value_norm"]))**2)
r_squared = 1 - (ss_res / ss_tot)
cum_norm_fig.add_annotation(x=0, y=0.95,text=f"<i>R²</i> = {round(r_squared,4)}",showarrow=False,xanchor="left",font=dict(size=16))
cum_norm_fig.add_annotation(x=0, y=0.85,text=f"RMSE = {round(rmse,4)}",showarrow=False,xanchor="left",font=dict(size=16))
cum_norm_fig.add_trace(go.Scatter(x=np.arange(1,366), y=log_model(np.arange(1,366), *popt), name="log_model"))
plots["cum_norm_fig_b"] = copy.deepcopy(cum_norm_fig)

starting_values = [10/np.mean(df["cum_days"]),np.mean(df["cum_value_norm"]),np.mean(df["cum_days"]),2]
bounds = (0, [1, 2, 200,3])
gen_log_popt, gen_log_pcov = curve_fit(gen_log_model, df["cum_days"], df["cum_value_norm"],p0=starting_values,bounds=bounds)
residuals = df["cum_value_norm"] - gen_log_model(df["cum_days"], *gen_log_popt)
ss_res = np.sum(residuals**2)
rmse = np.mean(residuals**2)**0.5
ss_tot = np.sum((df["cum_value_norm"]-np.mean(df["cum_value_norm"]))**2)
r_squared = 1 - (ss_res / ss_tot)
cum_norm_fig.add_annotation(x=0, y=0.95,text=f"<i>R²</i> = {round(r_squared,4)}",showarrow=False,xanchor="left",font=dict(size=16))
cum_norm_fig.add_annotation(x=0, y=0.85,text=f"RMSE = {round(rmse,4)}",showarrow=False,xanchor="left",font=dict(size=16))
cum_norm_fig.add_trace(go.Scatter(x=np.arange(1,366), y=gen_log_model(np.arange(1,366), *gen_log_popt), name="gen_log_model"))
plots["cum_norm_fig_c"] = copy.deepcopy(cum_norm_fig)

tdf = df.groupby(["floor_area"]).agg({"mean_floor_area": "min", "monthly_total":"sum"})
starting_values = [np.max(tdf["mean_floor_area"]),1]
total_popt, total_pcov = curve_fit(pow_model, tdf["mean_floor_area"], tdf["monthly_total"],p0=starting_values)
total_fig = px.scatter(tdf, x="mean_floor_area", y="monthly_total")
total_fig.update_layout(xaxis_title="Floor area (m²)",yaxis_title="Annual gas use (kWh)")
total_fig.add_trace(go.Scatter(x=np.arange(1,300), y=pow_model(np.arange(1,300), *total_popt), name="pow_model"))
plots["total_fig"] = total_fig

df["monthly_total_modelled_cum"] = df.apply(lambda row : gen_log_model(row["cum_days"], *gen_log_popt) * pow_model(row["mean_floor_area"], *total_popt)  , axis=1)
df["monthly_total_modelled"] = df.groupby(["floor_area"])["monthly_total_modelled_cum"].diff()
df["monthly_total_modelled"] = df["monthly_total_modelled"].fillna(df["monthly_total_modelled_cum"])
model_compare_fig = px.scatter(df, x="monthly_total_modelled", y="monthly_total",color="summary_time")
model_compare_fig.add_trace(go.Scatter(x=[0,5000], y=[0,5000], name="1:1 line"))
model_compare_fig.update_layout(xaxis_title="Modelled gas use (kWh)",yaxis_title="Observed gas use (kWh)")
plots["model_compare_fig"] = model_compare_fig

odf = get_serl_data("Figure_14")
odf = odf.loc[odf["fuel"] == "Gas"]
odf = odf.dropna(subset = ["mean_occupants"])
starting_values = [odf["mean_occupants"].max(),(odf["mean_occupants"].max()-odf["mean_occupants"].min())/odf["mean_occupants"].max(),(3/(odf["mean_floor_area"].max()-odf["mean_floor_area"].min()))]
area_from_occup_popt, area_from_occup_pcov = curve_fit(exp_model,odf["mean_occupants"], odf["mean_floor_area"],p0=starting_values)

df = df.dropna(subset=["mean_occupants"])
starting_values = [df["mean_occupants"].max(),(df["mean_occupants"].max()-df["mean_occupants"].min())/df["mean_occupants"].max(),(3/(df["mean_floor_area"].max()-df["mean_floor_area"].min()))]
occup_from_area_popt, occup_from_area_pcov = curve_fit(exp_model, df["mean_floor_area"],df["mean_occupants"],p0=starting_values)

occupancy_fig = px.scatter(odf,x="mean_floor_area",y="mean_occupants")
occupancy_fig.add_trace(go.Scatter(x=df["mean_floor_area"], y=df["mean_occupants"], mode="markers"))
occupancy_fig.update_layout(xaxis_title="Floor area (m²)",yaxis_title="Number of occupants")
occupancy_fig.add_trace(go.Scatter(x=np.arange(1,300), y=exp_model(np.arange(1,300), *occup_from_area_popt), name="Occupancy from area", mode="lines"))
occupancy_fig.add_trace(go.Scatter(x=exp_model(np.arange(1,8),*area_from_occup_popt),y=np.arange(1,8), name="Area from occupancy", mode="lines"))
plots["occupancy_fig"] = occupancy_fig

with open("method_plots.pkl", "wb") as f:
    pickle.dump(plots, f)
