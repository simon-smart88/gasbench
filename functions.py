import plotly.graph_objects as go
import datetime
import requests
import pandas as pd
import numpy as np
import scipy


m3_per_kwh = 19.3 / 212.8
typical_cooking = [i * m3_per_kwh for i in [66, 90, 88, 99, 105, 110, 115, 120, 125, 130, 135]]

month_list = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
month_days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def gen_log_model(x, b, c, m, t):
	return (c / (1 + t * np.exp(-b*(x-m)))**1/t )

def pow_model(x, a, b):
	return (a * x**b)

def exp_model(x,a,b,c):
	return (a * (1-b * np.exp(-c*x)))

def get_serl_data(version, figure):
    if version == 1:
        df = pd.read_excel("SERL Stats Report (volume 1) - Tabular data v03b Final.xlsx", sheet_name = figure, skiprows = 1)
    if version == 2:
        df = pd.read_excel("SERL_Stats_Report_Aggregated_Tables_Vol_2.xlsx", sheet_name = figure, skiprows = 1)
    return df

def get_typical_gas(parameters, floor_area, occupants, start_month, model_type):
	expected_occup = exp_model(floor_area, *parameters["occup_from_area_popt"])
	expected_area = exp_model(np.array([occupants, expected_occup]), *parameters["area_from_occup_popt"])
	occupancy_scaling_factor = expected_area[0] / expected_area[1]

	pdf = pd.DataFrame({"t":np.arange(0, 367), "date":pd.date_range("2023-06-30", "2024-06-30")})
	pdf["cum"] = gen_log_model(pdf["t"], *parameters["gas_from_day_popt"]) * pow_model(floor_area, *parameters["total_from_area_popt"]) * occupancy_scaling_factor
	pdf["daily"] = pdf["cum"].diff()
	pdf = pdf.dropna()

	if model_type == "heating":
		#conversion factors for energy use required to heat water in different months
		mdf = pd.DataFrame({"water": [1.1, 1.06, 1.02, 0.98, 0.94, 0.9, 0.9, 0.94, 0.98, 1.02, 1.06, 1.1], "month": np.arange(1, 13)})
		mdf["adjust"] = mdf["water"]/ mdf.loc[(mdf["month"] >= 6) & (mdf["month"] <= 8), "water"].mean() 
		pdf["month"] = pdf["date"].dt.month
		pdf = pdf.merge(mdf)
		not_heat = pdf.loc[(pdf["month"] >= 6) & (pdf["month"] <= 8), "daily"].mean() 
		pdf["daily"] = pdf["daily"] - (pdf["adjust"] * not_heat)
		pdf["daily"] = pdf["daily"].clip(lower = 0)

	start_date = min(pdf.loc[pdf["date"].dt.month == start_month, "date"])
	pdf["date"] = np.where(pdf["date"] < start_date, pdf["date"] + pd.DateOffset(days = 365), pdf["date"])
	pdf = pdf.sort_values(by = "date")
	pdf["cum"] = pdf.daily.cumsum()
	return pdf


def get_cost_data(fuel, charge):
  if fuel == "gas":
    base_url = "https://api.octopus.energy/v1/products/VAR-22-11-01/gas-tariffs/G-1R-VAR-22-11-01-A/"
  if charge == "standing":
    url = f"{base_url}standing-charges/"
  if charge == "unit":
    url = f"{base_url}standard-unit-rates/"
  yesterday = (datetime.datetime.today()-datetime.timedelta(1)).strftime("%Y-%m-%d")
  payload = {"period_from":"2020-10-31T00:00Z","period_to" : yesterday}
  req = requests.get(url=url, params = payload).json()
  df = pd.json_normalize(req["results"])
  df = df[df["payment_method"] == "DIRECT_DEBIT"]
  df = df.drop(["value_exc_vat", "payment_method"], axis = 1)
  df.columns = [charge, "start_date", "end_date"]
  df["start_date"] = pd.to_datetime(df["start_date"]).dt.tz_localize(None)
  df["end_date"] = pd.to_datetime(df["end_date"]).dt.tz_localize(None)
  df.loc[df["end_date"].isna(), "end_date"] = pd.to_datetime(yesterday)
  gas_cost = pd.read_csv("gas_cost.csv")
  gas_cost["start_date"] = pd.to_datetime(gas_cost["start_date"])
  gas_cost["end_date"] = pd.to_datetime(gas_cost["end_date"])
  charges = ["unit", "standing"]
  to_drop = charges[not charges.index(charge)] 
  df = pd.concat([df, gas_cost])
  df = df.drop(to_drop, axis = 1)
  return df

# fetch daily gas use and return with datetime, kwh and cost conversions
def get_daily_gas_data(octopus_secrets, standing_cost, unit_cost):
  
  if [k for k, v in octopus_secrets.items() if not v]:
    df = pd.read_csv("2020-2025_data.csv")
    df.columns = ["index", "interval_start", "consumption"]
  else:
    yesterday = (datetime.datetime.today()-datetime.timedelta(1)).strftime("%Y-%m-%d")
    payload = {"period_from":"2020-10-31T00:00:00Z", "period_to" : yesterday, "page_size" : 25000, "group_by" : "day","order_by" : "period"}
    session = requests.Session()
    session.auth = (octopus_secrets["key"], "")
    gas_point = octopus_secrets["gas_point"]
    gas_meter = octopus_secrets["gas_meter"]
    daily_gas_req = session.get(url=f"https://api.octopus.energy/v1/gas-meter-points/{gas_point}/meters/{gas_meter}/consumption/", params = payload).json()
    df = pd.json_normalize(daily_gas_req["results"])
    df["interval_start"] = pd.to_datetime(df["interval_start"].str.split("T").str[0])
    df = df.drop([ "interval_end"], axis = 1)
  
  df["date"] = df["interval_start"]
  df = df.set_index("date")
  df.index = pd.to_datetime(df.index)
  df["consumption"] = df["consumption"] * (1 / m3_per_kwh)
  sc = standing_cost
  uc = unit_cost
  uc_idx = pd.IntervalIndex.from_arrays(uc["start_date"], uc["end_date"], closed = "both")
  sc_idx = pd.IntervalIndex.from_arrays(sc["start_date"], sc["end_date"], closed = "both")
  df["unit"] = df["interval_start"].apply(lambda x: uc.loc[uc_idx.contains(x), "unit"].sum())
  df["standing"] = df["interval_start"].apply(lambda x: sc.loc[sc_idx.contains(x), "standing"].sum())
  df["cost"] = ((df["unit"] * df["consumption"]) + df["standing"]) / 100
  return df

def get_typical_gas_cost(typical_gas, daily_gas):
  
  typical_gas['date'] = pd.to_datetime(typical_gas['date'])
  daily_gas.index = pd.to_datetime(daily_gas.index)  

  typical_gas['month_day'] = typical_gas['date'].dt.strftime('%m-%d')
  daily_gas['month_day'] = daily_gas.index.strftime('%m-%d')
  
  merged = daily_gas.merge(typical_gas[['month_day', 'daily']], on='month_day', how='left')
  merged['typical_cost'] = (merged['daily'] * merged['unit']) + merged['standing']
  
  return merged

# fetch min and max temperature data
def get_climate_data(postcode, start_date, end_date):
  from meteostat import Point, Daily
  from datetime import datetime

  response = requests.get(f"https://api.postcodes.io/postcodes/{postcode}")
  postcode_data = response.json()
  latitude = postcode_data["result"]["latitude"]
  longitude = postcode_data["result"]["longitude"]

  start = datetime.strptime(start_date, "%Y-%m-%d")
  end = datetime.strptime(end_date, "%Y-%m-%d")
  
  location = Point(latitude, longitude, 0)
  data = Daily(location, start, end)
  df = data.fetch()

  return df


# convert daily data into cumulative use per heating season
def pivot_to_season(df, start_month, typical_type, month_offset, month_number):
  df = df.copy()
  if typical_type == "heating":
    df["month"] = pd.to_datetime(df["interval_start"], utc = True).dt.month
    daily_not_heat = df.loc[(df["month"] >= 6) & (df["month"] <= 8), "consumption"].mean()
    df["consumption"] = (df["consumption"] - daily_not_heat).clip(lower = 0)
    df.loc[(df["month"] >= 6) & (df["month"] <= 8), "consumption"] = 0
    df = df.drop(["month"], axis = 1)
    #need to use conversion factor here...
    
  month_abbrev = month_list[month_list.index(start_month)-1].upper()[0:3]
  month_filter = "A-" + month_abbrev

  df["season"] = df.index.to_period(month_filter).year - 1
  df["dos"] = (df.index - df.index.to_period(month_filter).start_time).days + 1
  df["cumulative"] = df.groupby(pd.Grouper(freq=month_filter))["consumption"].cumsum()
  
  pivot_index = pd.date_range(start="2023-" + "{:02d}".format(month_number)+"-01", end = "2024-" + "{:02d}".format(month_number-1)+"-"+str(month_days[month_number]))
  year_index = []
  for y in list(pd.unique(df["season"])):
      year_index.append(str(y)+"-"+str(y+1))
  
  piv = pd.pivot_table(df, index = ["dos"], columns=["season"], values=["cumulative"])
  piv = piv.fillna(method="bfill")
  piv.index = pivot_index
  piv.columns = year_index
  return piv

def bench_fig(mean, sd, actual, energy_type):
	dist_x = np.arange(0, mean + (3 * sd), 10)
	#use_dist = scipy.stats.norm.pdf(dist_x,loc=mean,scale=sd)
	use_dist = scipy.stats.skewnorm.pdf(dist_x, 0.4, loc = mean, scale = sd)
	fig = go.Figure()
	bdf = pd.DataFrame({"x" : dist_x, "y" : use_dist})
	bdf["cum"] = bdf["y"].cumsum()/bdf["y"].sum()
	limits = np.arange(0.25, 1.25, 0.25)
	bench_cols = ["#2ecc71 ", "#82e0aa", "#f1948a", "#e74c3c"]
	categories = ["Lowest 25%", "Below average", "Above average", "Highest 25%"]
	for l, c, n in zip(limits, bench_cols, categories):
	    block = bdf.loc[(bdf["cum"] >= l-0.25) & (bdf["cum"] < l)]
	    close = pd.DataFrame({"x":[block["x"].max(), block["x"].min()], "y":[0, 0]})
	    block = pd.concat([block, close])
	    fig.add_trace(go.Scatter(x = block["x"], y = block["y"], fill = "toself", fillcolor = c, line_color = c, name = n))
	fig.add_vline(x = actual, line_width = 2, line_color = "black")
	fig.update_layout(xaxis_title = f"{energy_type.capitalize()} use (kWh)", legend=dict(y=1.1, orientation="h"),
  	xaxis = dict(showgrid = False), yaxis=dict(showgrid = False), plot_bgcolor = "white")
	if actual > mean:
		fig.add_annotation(x = actual, y = max(use_dist) * 0.66, text = f"Your {energy_type} use <br> in the last year", showarrow = False, xanchor = "right")
	if actual <=  mean:
		fig.add_annotation(x = actual, y = max(use_dist) * 0.66, text = f"Your {energy_type} use <br> in the last year", showarrow = False, xanchor = "left")
	fig.update_yaxes(visible = False)
	return fig

def compare_years(df, yesterday):
  result = pd.DataFrame()
  years = df.index.year.unique()
  date = yesterday[5:]
  
  for year in years:
    end_date = pd.to_datetime(f'{year}-{date}')
    start_date = end_date - pd.Timedelta(days=30)
    mask = (df.index >= start_date) & (df.index <= end_date)
    result = pd.concat([result, df[mask]])
  return result

def expected_from_temperature(temperatures, baseline_temp, baseline_values):
  from scipy.stats import linregress
  model = linregress(baseline_temp, baseline_values)
  slope = model[0]
  intercept = model[1]
  expected = []
  for t in temperatures:
    if t < 17.5:
        expected.append(intercept + (slope * t)) 
    if t >= 17.5:
        expected.append(min(baseline_values))
  return(expected)

  
