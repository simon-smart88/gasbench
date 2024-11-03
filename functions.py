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

def get_serl_data(figure):
	df = pd.read_excel("SERL Stats Report (volume 1) - Tabular data v03b Final.xlsx", sheet_name = figure, skiprows = 1)
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

# fetch daily gas use and return with datetime and kwh conversions
def get_daily_gas_data(octopus_secrets):
	yesterday = (datetime.datetime.today()-datetime.timedelta(1)).strftime("%Y-%m-%d")
	payload = {"period_from":"2020-10-31T00:00:00Z", "period_to" : yesterday, "page_size" : 25000, "group_by" : "day","order_by" : "period"}
	session = requests.Session()
	session.auth = (octopus_secrets["key"], "")
	gas_point = octopus_secrets["gas_point"]
	gas_meter = octopus_secrets["gas_meter"]
	daily_gas_req = session.get(url=f"https://api.octopus.energy/v1/gas-meter-points/{gas_point}/meters/{gas_meter}/consumption/", params = payload).json()
	df = pd.json_normalize(daily_gas_req["results"])
	df["interval_start"] = pd.to_datetime(df["interval_start"].str.split("T").str[0])
	df["date"] = df["interval_start"]
	df = df.set_index("date")
	df.index = pd.to_datetime(df.index)
	df["consumption"] = df["consumption"] * (1 / m3_per_kwh)
	return df

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
	fig.update_layout(title = "Gas benchmark", xaxis_title = f"{energy_type.capitalize()} use (kWh)",
  	xaxis = dict(showgrid = False), yaxis=dict(showgrid = False), plot_bgcolor = "white")
	if actual > mean:
		fig.add_annotation(x = actual, y = max(use_dist) * 0.66, text = f"Your {energy_type} use <br> in the last year", showarrow = False, xanchor = "right")
	if actual <=  mean:
		fig.add_annotation(x = actual, y = max(use_dist) * 0.66, text = f"Your {energy_type} use <br> in the last year", showarrow = False, xanchor = "left")
	fig.update_yaxes(visible = False)
	return fig


