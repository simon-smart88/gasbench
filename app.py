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
from methods import methods_ui, methods_server
import functions as fx

load_dotenv() 

m3_per_kwh = 19.3 / 212.8
typical_cooking = [i * m3_per_kwh for i in [66, 90, 88, 99, 105, 110, 115, 120, 125, 130, 135]]

month_list = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
month_days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

app_ui = ui.page_fluid(
  
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
        ui.row(
          ui.column(4, 
            ui.output_ui("gas_usage")
          ),
          ui.column(4,
            ui.output_ui("co2_emissions")
          ),
          ui.column(4,
            ui.output_ui("gas_cost")
          )
        ),
        ui.row(
          ui.column(4, 
            ui.output_ui("gas_compare")
          ),
          ui.column(4,
            ui.output_ui("co2_diff")
          ),
          ui.column(4,
            ui.output_ui("cost_diff")
          )
        ),
        ui.row(
        ui.column(6,
          output_widget("overall_gas_fig")
          ),
        ui.column(6,
          output_widget("heating_gas_fig")
          )
        ),
        ui.row(
        ui.column(4,
          output_widget("benchmark_fig")
          ),
        ui.column(4,
          output_widget("weekly_climate_fig")
          ),
        ui.column(4,
          output_widget("climate_benchmark_fig")
          )
        ),
      ),
    ),
    ui.nav_panel("About",
      ui.row(
        ui.column(6,
          ui.card(
            methods_ui("methods"),
          ),
        class_="mx-auto")
      )
    )
  ),
  ui.markdown("Built with [Shiny for python](https://shiny.posit.co/py/). [Source code](https://github.com/simon-smart88/gasbench)"),
  title = "Gas benchmarking",
  theme = ui.Theme("cerulean"),
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
    if input.octopus_key() == "" or input.octopus_gas_point() == "" or input.octopus_gas_meter() == "":
      octopus_secrets = {"key": os.getenv("OCTOPUS_KEY"), "gas_point": os.getenv("OCTOPUS_GAS_POINT"), "gas_meter": os.getenv("OCTOPUS_GAS_METER")}
    else:
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
  def daily_gas_data():
    return fx.get_daily_gas_data(octopus_secrets())

  @reactive.calc
  def overall_gas_data():
    return fx.pivot_to_season(daily_gas_data(), input.start_month(), "overall", month_offset(), month_number())
  
  @reactive.calc
  def overall_typical_gas_data():
    return fx.get_typical_gas(parameters, input.floor_area(), input.occupants(), month_list.index(input.start_month()) + 1, "overall")
  
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
    
  @render.ui
  def gas_usage():
    return ui.value_box(
      "Gas used in the last year",
      f"{round(latest_gas_sum(), 1)} kWh",
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
    else:
      icon = "fas fa-arrow-up"
      diff = "higher"
      theme = "red"
      diff_percent = abs(diff_percent)
    return ui.value_box(
      "Gas use compared to typical",
      f"{round(diff_percent, 1)}% {diff}",
      showcase = ui.tags.i(class_ = icon),
      theme = theme)
  
  @render.ui
  def co2_emissions():
    return ui.value_box(
      "CO₂ emissions in the last year",
      f"{round(latest_gas_sum() * 0.203, 0)} kg",
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
    f"{round(co2_diff, 0)} kg",
    showcase = ui.tags.i(class_ = icon),
    theme = theme)
  
  @render.ui
  def gas_cost():
    cost = ((latest_gas_sum() * 0.0587) + (0.298  * 365)) * 1.05
    return ui.value_box(
      "Cost of gas in the last year",
      f"£{round(cost, 0)}",
      "At current prices of 5.87p/kWh and 27.98p/day and 5% VAT",
      showcase = ui.tags.i(class_ = "fas fa-sterling-sign"),
      theme = "blue"
    )
  
  @render.ui
  def cost_diff():
    cost_diff = overall_gas_diff() * 0.0587
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
    f"£{round(cost_diff, 0)}",
    showcase = ui.tags.i(class_ = icon),
    theme = theme)

  @render_plotly
  def overall_gas_fig():
    plot = go.Figure()
    for column in overall_gas_data().columns[0:]:
      plot.add_trace(go.Scatter(x = overall_gas_data().index, y = overall_gas_data()[column], name = column))
    plot.add_trace(go.Scatter(x = overall_typical_gas_data()["date"], y = overall_typical_gas_data()["cum"], name = "Typical"))
    plot.update_layout(title = "Overall gas use", xaxis_title = "", yaxis_title = "Gas use (kWh)", 
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white")
    return plot

  @render_plotly
  def heating_gas_fig():
    plot = go.Figure()
    for column in heating_gas_data().columns[0:]:
      plot.add_trace(go.Scatter(x = heating_gas_data().index, y = heating_gas_data()[column], name = column))
    plot.add_trace(go.Scatter(x = heating_typical_gas_data()["date"], y = heating_typical_gas_data()["cum"], name = "Typical"))
    plot.update_layout(title = "Heating gas use", xaxis_title = "", yaxis_title = "Gas use (kWh)", 
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white")
    return plot

  @render_plotly
  def benchmark_fig():
    plot = fx.bench_fig(typical_gas_sum(), typical_gas_sd(), latest_gas_sum(), "gas")
    return plot
  
  @render_plotly
  def weekly_climate_fig():
    df = climate_data()
    df.resample("W").mean()
    df["year"] = df.index.year 
    
    plot = go.Figure()
    for y in df.year.unique():
      ydf = df[df["year"] == y]
      plot.add_trace(go.Scatter(x = ydf["tavg"], y = ydf["consumption"], mode = "markers", name = str(y)))
    plot.update_layout(title = "Weekly heating use and temperature", xaxis_title = "Average temperature (°C)", yaxis_title = "Daily gas use (kWh)", 
      xaxis = dict(tickformat = "%e %b", showgrid = False), yaxis = dict(showgrid = False), plot_bgcolor = "white")
    return(plot)

  @render_plotly
  def climate_benchmark_fig():
    df = climate_data()
    
    # serl = fx.get_serl_data("Figure_6")
    # serl = serl[serl["fuel"] == "Gas"]
    # serl["resp"] = serl["value"] / min(serl["value"])

    # benchmark data derived from above
    temp_response = [0, 10.06, 6.61, 3.02, 1, 0]
    bin_edges = [-5, 0, 5, 10, 15, 20, 25]
    bin_labels = ["-5 to 0", "0 to 5", "5 to 10", "10 to 15", "15 to 20", "20 to 25"]
    df["temperature_bins"] = pd.cut(df["tavg"], bins = bin_edges, labels = bin_labels, right = False)
    
    mean_values = pd.DataFrame(df.groupby("temperature_bins")["consumption"].mean())
    mean_values["benchmark"] = temp_response
    mean_values["benchmark"] = mean_values["benchmark"] * mean_values["consumption"][4]
    
    plot = go.Figure(data=[
    go.Bar(name="Benchmark", x = mean_values.index, y = mean_values["benchmark"]),
    go.Bar(name="Your usage", x = mean_values.index, y = mean_values["consumption"])
    ])
    
    plot.update_layout(barmode = "group",
    xaxis_title = "Temperature (°C)",
    yaxis_title = "Daily gas use (kWh)",
    title = "Temperature and gas usage benchmark",
    xaxis = dict(showgrid = False), 
    yaxis = dict(showgrid = False), plot_bgcolor = "white")
    
    return plot
    
    
    
    
app = App(app_ui, server)
