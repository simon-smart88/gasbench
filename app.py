import plotly.graph_objects as go
from shiny import App, render, ui, reactive, req
from shinywidgets import output_widget, render_plotly
import datetime
import requests
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv
import pickle
from pathlib import Path

from methods import methods_ui, methods_server
import functions as fx

load_dotenv() 

m3_per_kwh = 19.3 / 212.8
typical_cooking = [i * m3_per_kwh for i in [66, 90, 88, 99, 105, 110, 115, 120, 125, 130, 135]]

month_list = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
month_days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

app_ui = ui.page_fluid(
  ui.tags.link(href="styles.css", rel="stylesheet"),
  ui.tags.head(
    ui.tags.link(
        rel="stylesheet",
        href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"
    )
  ),
  ui.h2("Gas benchmarking"),
  ui.navset_tab(
    ui.nav_panel("Benchmarking", 
      ui.layout_sidebar(
        ui.sidebar(
          ui.input_slider("floor_area", "What is your floor area in square metres?", min = 1, max = 300, step = 1, value = 70),
          ui.input_slider("occupants", "How many people live in your property?", min = 1, max = 10, step = 1, value = 2),
          ui.input_select("start_month", "Which month do you switch on your heating?", choices = month_list[8:11], selected = 2),
          ui.accordion(
            ui.accordion_panel("Fetch your own data",
              ui.markdown("Get your Octopus API key from [here](https://octopus.energy/dashboard/new/accounts/personal-details/api-access)"),
              ui.input_text("postcode", "Postcode"),
              ui.input_text("octopus_key", "Octopus API key e.g. sk_live_...."),
              ui.input_text("octopus_gas_point", "Octopus gas point (10 digits)"),
              ui.input_text("octopus_gas_meter", "Octopus gas meter (14 characters)")
            ), open = False
          )
        ),
        ui.layout_columns(
          ui.output_ui("gas_usage"),
          ui.output_ui("co2_emissions"),
          ui.output_ui("gas_cost"),
        col_widths = [4, 4, 4],
        gap = "1rem"
        ),
        ui.layout_columns(
            ui.output_ui("gas_compare"),
            ui.output_ui("co2_diff"),
            ui.output_ui("cost_diff"),
        col_widths = [4, 4, 4],
        gap = "1rem"
        ),
        ui.layout_columns(
          ui.card(
            ui.tags.details(
              ui.tags.summary(" Overall gas use"),
              ui.markdown("Your gas use over each of the last 5 years, compared to a property of the same size and the same number of occupants.")
            ),
            output_widget("overall_gas_fig")
          ),
          ui.card(
            ui.tags.details(
              ui.tags.summary(" Heating gas use"),
                ui.markdown("Your estimated gas use for heating over each of the last 5 years, compared to a property of the same size and the same number of occupants. It is estimated by subtracting your average gas use in the summer months (June to August) from your total usage and includes an adjustment for the extra gas required to heat water in the winter.")
            ),
            output_widget("heating_gas_fig")
          ),
        col_widths = {"sm": [12],
                      "lg": [6, 6]
                      },
        gap = "1rem"
        ),
        ui.layout_columns(
          ui.card(
            ui.tags.details(
              ui.tags.summary(" Your gas use compared to others"),
              ui.markdown("How your gas use compares to other properties of a similar size. The green area uses less than average and the red area more than average, with further to left or right indicating lower or higher use.")
            ),
          output_widget("benchmark_fig")
          ),
          ui.card(
            ui.tags.details(
              ui.tags.summary(" Weekly heating use and temperature"),
              ui.markdown("How your gas use varies with temperature recorded at your nearest weather station. The weekly average temperature is shown against the average daily gas use each week.")
            ),
          output_widget("weekly_climate_fig")
          ),
          ui.card(
            ui.tags.details(
              ui.tags.summary(" Temperature and gas usage benchmark"),
              ui.markdown("How your gas use changes as temperature changes compared to others. 15-20°C is taken as the baseline and compared to how average gas use changes at different temperatures.")
            ),
          output_widget("climate_benchmark_fig")
          ),
        col_widths = {"sm": [12],
                      "md": [6, 6],
                      "lg": [4, 4, 4]
                      },
        gap = "1rem"
        ),
        ui.layout_columns(
          ui.card(
            ui.tags.details(
              ui.tags.summary("Recent gas use"),
              ui.markdown("How your recent daily gas use compares to what is expected given your own response to temperature last year and this year's temperatures.")
            ),
            output_widget("compare_recent_days_fig")
          ),
          ui.card(
            ui.tags.details(
              ui.tags.summary("Heating demand relative to standards"),
              ui.markdown("How your estimated heating use in the previous heating season compares to various building standards. These typically assume that homes are heated to a constant temperature of 20 to 21°C")
            ),
          output_widget("heating_demand_benchmark_fig")
          ),
        col_widths = [6, 6]
        )
      ),
    ),
    ui.nav_panel("About",
      ui.layout_columns(
        None,
        ui.card(
          methods_ui("methods"),
        ),
        None,
      col_widths={
        "sm": 12,
        "md": [2, 8, 2],
        "lg": [3, 6, 3]    
        },
      )
    )
  ),
  ui.markdown("Built with [Shiny for python](https://shiny.posit.co/py/). [Source code](https://github.com/simon-smart88/gasbench)"),
  title = "Gas benchmarking",
  theme = ui.Theme("cerulean")
        #cooking_bool = st.radio("Do you use gas for cooking?",("Yes", "No"))
)

def server(input, output, session):
  
  methods_server("methods")
  
  with open("fitted_models.pkl", "rb") as f:
    parameters = pickle.load(f)
  
  @reactive.calc
  def month_offset():
    return sum(month_days[0:month_list.index(input.start_month())])
  
  @reactive.calc
  def month_number():
    return month_list.index(input.start_month()) + 1
  
  @reactive.calc
  def octopus_secrets():
    # if input.octopus_key() == "" or input.octopus_gas_point() == "" or input.octopus_gas_meter() == "":
    #   octopus_secrets = {"key": os.getenv("OCTOPUS_KEY"), "gas_point": os.getenv("OCTOPUS_GAS_POINT"), "gas_meter": os.getenv("OCTOPUS_GAS_METER")}
    # else:
    octopus_secrets = {"key": input.octopus_key(), "gas_point": input.octopus_gas_point(), "gas_meter": input.octopus_gas_meter()}
    return octopus_secrets
  
  @reactive.calc
  def postcode():
    if input.postcode() == "":
      postcode = os.getenv("POSTCODE")
    else:
      postcode = input.postcode()
    return postcode

  @reactive.calc
  def gas_standing_cost():
    return fx.get_cost_data("gas", "standing")
    
  @reactive.calc
  def gas_unit_cost():
    return fx.get_cost_data("gas", "unit")

  @reactive.calc
  def daily_gas_data():
    # req(gas_standing_cost())
    # req(gas_unit_cost())
    return fx.get_daily_gas_data(octopus_secrets(), gas_standing_cost(), gas_unit_cost())

  @reactive.calc
  def overall_gas_data():
    return fx.pivot_to_season(daily_gas_data(), input.start_month(), "overall", month_offset(), month_number())
  
  @reactive.calc
  def overall_typical_gas_data():
    return fx.get_typical_gas(parameters, input.floor_area(), input.occupants(), month_list.index(input.start_month()) + 1, "overall")
  
  @reactive.calc
  def typical_gas_cost():
    return fx.get_typical_gas_cost(overall_typical_gas_data(), daily_gas_data())
  
  @reactive.calc
  def heating_gas_data():
    return fx.pivot_to_season(daily_gas_data(), input.start_month(), "heating", month_offset(), month_number())

  @reactive.calc
  def heating_typical_gas_data():
    return fx.get_typical_gas(parameters, input.floor_area(), input.occupants(), month_list.index(input.start_month()) + 1, "heating")
  
  @reactive.calc
  def current_dos():
    return overall_gas_data().iloc[:,-1].index.get_loc(overall_gas_data().iloc[:,-1].last_valid_index())

  @reactive.calc
  def latest_gas_sum():
    return daily_gas_data()["consumption"].tail(365).sum()
  
  @reactive.calc
  def typical_gas_sum():
    return overall_typical_gas_data()["cum"].tail(1).min()
  
  @reactive.calc
  def typical_gas_sd():
    return 2809.077 * np.exp(0.00005240616 * typical_gas_sum())

  @reactive.calc
  def overall_gas_diff():
    n_years = len(overall_gas_data().columns) - 1
    this_year = overall_typical_gas_data()["cum"][current_dos()]
    total_typical = (typical_gas_sum() * n_years) + this_year
    total_actual = daily_gas_data()["consumption"].sum()
    return total_typical - total_actual
  
  @reactive.calc
  def climate_data():
    yesterday = (datetime.datetime.today()-datetime.timedelta(1)).strftime("%Y-%m-%d")
    climate_data = fx.get_climate_data(postcode(), "2020-11-01", yesterday)
    return pd.merge(daily_gas_data(), climate_data, right_index = True, left_index = True)

  @reactive.calc
  def climate_benchmark_data():
    df = climate_data()
    
    # df = fx.get_serl_data(2, "Figure_5")
    # df = df[df["quantity"] == "Gas"]
    # mean_df = df.groupby(["segment_3_value"]).mean().reset_index()
    # mean_df["relative_value"] = mean_df["median"] / mean_df.loc[mean_df["segment_3_value"] == "15_to_20", "median"].squeeze()
    
    # benchmark data derived from above
    temp_response = [13.09, 10.45, 7.07, 2.95, 1, 0.75]
    bin_edges = [-5, 0, 5, 10, 15, 20, 25]
    bin_labels = ["-5 to 0", "0 to 5", "5 to 10", "10 to 15", "15 to 20", "20 to 25"]
    df["temperature_bins"] = pd.cut(df["tavg"], bins = bin_edges, labels = bin_labels, right = False)
    df = df.tail(365)
    mean_values = pd.DataFrame(df.groupby("temperature_bins")[["consumption", "tavg"]].mean())
    mean_values["benchmark"] = temp_response
    mean_values["benchmark"] = mean_values["benchmark"] * mean_values["consumption"][4]
    return mean_values  

  @render.ui
  def gas_usage():
    return ui.value_box(
      "Gas used in the last year",
      f"{int(latest_gas_sum())} kWh",
      f"Enough to boil {int(latest_gas_sum() * 10.08 / 365)} kettles every day",
      # 3600000 / 357000 (4200 j per l per C * 85 C)
      showcase = ui.tags.i(class_ = "fas fa-fire-flame-simple"),
      theme = "blue"
    )
  
  @render.ui
  def gas_compare():
    diff_percent = (typical_gas_sum() - latest_gas_sum()) / typical_gas_sum() * 100
    if diff_percent > 0:
      icon = "fas fa-arrow-down"
      diff = "lower"
      theme = "green"
      note = "Well done!"
    else:
      icon = "fas fa-arrow-up"
      diff = "higher"
      theme = "red"
      note = "Room for improvement"
      diff_percent = abs(diff_percent)
    return ui.value_box(
      "Gas use compared to typical",
      f"{round(diff_percent, 1)}% {diff}",
      note,
      showcase = ui.tags.i(class_ = icon),
      theme = theme)
  
  @render.ui
  def co2_emissions():
    co2 = int(latest_gas_sum() * 0.203)
    return ui.value_box(
      "CO₂ emissions in the last year",
      f"{co2} kg",
      f"{int(co2 / (117 * input.occupants()))}% of your typical carbon footprint",
      # https://www.openaccessgovernment.org/the-average-british-carbon-footprint-is-five-times-over-paris-agreement-recommendations/152669/
      showcase = ui.tags.i(class_ = "fas fa-cloud"),
      theme = "blue"
    )
  
  @render.ui
  def co2_diff():
    co2_diff = overall_gas_diff() * 0.203
    if co2_diff > 0:
      icon = "fas fa-arrow-down"
      diff = "saved"
      theme = "green"
    else:
      icon = "fas fa-arrow-up"
      diff = "extra"
      theme = "red"
      co2_diff = abs(co2_diff)
    return ui.value_box(
    f"Total CO₂ emissions {diff} compared to typical",
    f"{int(co2_diff)} kg",
    f"Equivalent to flying for {int(co2_diff / 90)} hours",
    # source https://www.clevel.co.uk/flight-carbon-calculator/
    showcase = ui.tags.i(class_ = icon),
    theme = theme)
  
  @render.ui
  def gas_cost():
    cost = daily_gas_data()["cost"].tail(365).sum()
    return ui.value_box(
      "Cost of gas in the last year",
      f"£{int(cost)}",
      "At current prices of 5.87p/kWh and 27.98p/day and 5% VAT",
      showcase = ui.tags.i(class_ = "fas fa-sterling-sign"),
      theme = "blue"
    )
  
  @render.ui
  def cost_diff():
    # req(gas_unit_cost())
    cost_diff = (typical_gas_cost()["typical_cost"].sum() - typical_gas_cost()["cost"].sum()) / 100
    if cost_diff > 0:
      icon = "fas fa-arrow-down"
      diff = "saved"
      theme = "green"
    else:
      icon = "fas fa-arrow-up"
      diff = "extra spent"
      theme = "red"
      cost_diff = abs(cost_diff)
    return ui.value_box(
    f"Total {diff} compared to typical",
    f"£{int(cost_diff)}",
    f"Equivalent to {int(cost_diff / 0.3)} Freddos",
    showcase = ui.tags.i(class_ = icon),
    theme = theme)

  @render_plotly
  def overall_gas_fig():
    plot = go.Figure()
    plot.add_trace(go.Scatter(x = overall_typical_gas_data()["date"].dt.strftime("%Y-%m-%d"), y = overall_typical_gas_data()["cum"], name = "Typical", line = dict(width = 4)))
    for column in overall_gas_data().columns[0:]:
      plot.add_trace(go.Scatter(x = overall_gas_data().index.strftime("%Y-%m-%d"), y = overall_gas_data()[column], name = column))
    plot.update_layout(title = "", xaxis_title = "", yaxis_title = "Gas use (kWh)", xaxis_type="date",
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white",legend=dict(y=1.1, orientation="h"))
    return plot

  @render_plotly
  def heating_gas_fig():
    plot = go.Figure()
    plot.add_trace(go.Scatter(x = heating_typical_gas_data()["date"].dt.strftime("%Y-%m-%d"), y = heating_typical_gas_data()["cum"], name = "Typical", line = dict(width = 4)))
    for column in heating_gas_data().columns[0:]:
      plot.add_trace(go.Scatter(x = heating_gas_data().index.strftime("%Y-%m-%d"), y = heating_gas_data()[column], name = column))
    plot.update_layout(title = "", xaxis_title = "", yaxis_title = "Gas use (kWh)", xaxis_type="date",
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white", legend=dict(y=1.1, orientation="h"))
    return plot

  @render_plotly
  def benchmark_fig():
    plot = fx.bench_fig(typical_gas_sum(), typical_gas_sd(), latest_gas_sum(), "gas")
    return plot
  
  @render_plotly
  def weekly_climate_fig():
    df = climate_data()
    # df = df.drop(["interval_start"], axis = 1)
    df = df.select_dtypes(include=['number']) 
    df = df.resample("W").mean()
    df["year"] = df.index.year 
    
    plot = go.Figure()
    for y in df.year.unique():
      ydf = df[df["year"] == y]
      plot.add_trace(go.Scatter(x = ydf["tavg"], y = ydf["consumption"], mode = "markers", name = str(y)))
    plot.update_layout(title = "", xaxis_title = "Average temperature (°C)", yaxis_title = "Daily gas use (kWh)", 
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white", legend=dict(y=1.1, orientation="h"))
    return(plot)

  @render_plotly
  def climate_benchmark_fig():

    df = climate_benchmark_data()
    
    plot = go.Figure(data=[
    go.Bar(name="Benchmark", x = df.index, y = df["benchmark"]),
    go.Bar(name="Your usage", x = df.index, y = df["consumption"])
    ])
    
    plot.update_layout(barmode = "group",
    xaxis_title = "Temperature (°C)",
    yaxis_title = "Daily gas use (kWh)",
    title = "",
    xaxis = dict(showgrid = False), 
    yaxis = dict(showgrid = False), plot_bgcolor = "white", legend=dict(y=1.1, orientation="h"))
    
    return plot

  @render_plotly
  def compare_recent_days_fig():
    yesterday = (datetime.datetime.today()-datetime.timedelta(1)).strftime("%Y-%m-%d")
    df = fx.compare_years(climate_data(), yesterday)
    # may not be sensible assuming this is always linear
    baseline = climate_benchmark_data()[climate_benchmark_data()["tavg"] < 17.5]
    df["expected"] = fx.expected_from_temperature(df["tavg"].tolist(), baseline["tavg"], baseline["consumption"])
    years = df.index.year.unique()
    plot = go.Figure()
    x_values = df.index[df.index.year == years[-1]].strftime("%Y-%m-%d")
    for year in years[-1:]:
    #for year in years:
      plot.add_trace(go.Bar(name=year, x=x_values, y=df["consumption"][df.index.year == year]))
    plot.add_trace(go.Bar(name="Expected from temperature", x=x_values, y=df["expected"][df.index.year == year]))
    plot.update_layout(xaxis = dict(tickformat = "%e %b"), plot_bgcolor = "white", legend=dict(y=1.1, orientation="h"))
    return plot

  @render_plotly
  def heating_demand_benchmark_fig():
    values = [15, 25, 30,	50,	85,	125]
    standards = ["Passive House",	"EnerPHit",	"PHI Low Energy Building", "AECB CarbonLite Retrofit", "Average UK New Build", "Average UK House"]
    # uses total of previous heating season
    heating_demand = heating_gas_data().iloc[:,-2:-1].tail(1).squeeze()
    demand_per_m2 = heating_demand / input.floor_area()
    values.append(demand_per_m2)
    standards.append("Your property")
    sorted_data = sorted(zip(values, standards))
    values, standards = zip(*sorted_data)
    colors = ["RoyalBlue" if standard != "Your property" else "Red" for standard in standards]
    plot = go.Figure()
    plot.add_trace(go.Bar(y = standards, x = values, text = standards, textposition = "inside", orientation = "h", marker_color = colors))
    plot.update_layout(xaxis = dict(title = "kWh/m²/yr"), plot_bgcolor = "white", legend=dict(y=1.1, orientation="h"), yaxis = dict(title = "", showticklabels = False))
    return plot

  
www_dir = Path(__file__).parent / "www"
app = App(app_ui, server, static_assets = www_dir)
