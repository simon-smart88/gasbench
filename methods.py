from shiny import ui, render, module
from shinywidgets import output_widget, render_plotly
import pickle

code_one ="""
def get_serl_data(figure):
	req = requests.get("https://rdr.ucl.ac.uk/ndownloader/files/35857037")
	df = pd.read_excel(req.content,sheet_name=figure,skiprows=1)
	return(df)

df = get_serl_data("Figure_21")
df["date"] = pd.to_datetime(df["summary_time"], format = "%b-%y")
df["month"] = df["date"].dt.month
df["month_dum"] = np.where(df["month"] < 8, df["month"] + 5, df["month"] - 7)
df["days_per_month"] = df["date"].dt.days_in_month
df["monthly_total"] = df["days_per_month"] * df["value"]
df = df.rename(columns = {"segment_1_value": "floor_area"}).sort_values(by = ["floor_area", "month_dum"])
df["cum_value"] = df.groupby(["floor_area"])["monthly_total"].cumsum()
df["cum_days"] = df.groupby(["floor_area"])["days_per_month"].cumsum()
"""

code_two = """
df["cum_value_norm"] = df.groupby(["floor_area"])["monthly_total"].transform(lambda x: (x.cumsum()/x.sum()))
cum_norm_fig = px.scatter(df, x="cum_days", y="cum_value_norm", color="floor_area")
"""

code_three = """
from scipy.optimize import curve_fit
def log_fit(x, a, b, c, m):
    return (a + c / (1 + np.exp(-b * (x-m))))

starting_values = [0,10/np.mean(df["cum_days"]), np.mean(df["cum_value_norm"]), np.mean(df["cum_days"])]
bounds = (0, [1, 1, 2, 200])
popt, pcov = curve_fit(log_fit, df["cum_days"], df["cum_value_norm"], p0 = starting_values, bounds = bounds)

residuals = df["cum_value_norm"]- log_fit(df["cum_days"], *popt)
ss_res = np.sum(residuals**2)
rmse = np.mean(residuals**2)**0.5
ss_tot = np.sum((df["cum_value_norm"] - np.mean(df["cum_value_norm"]))**2)
r_squared = 1 - (ss_res / ss_tot)

cum_norm_fig.add_annotation(x = 0, y = 0.95,text = f"<i>R²</i> = {round(r_squared,4)}",showarrow = False,xanchor = "left",font  = dict(size = 16))
cum_norm_fig.add_annotation(x = 0, y = 0.85,text = f"RMSE = {round(rmse,4)}",showarrow  = False,xanchor  = "left",font  = dict(size  = 16))
cum_norm_fig.add_trace(go.Scatter(x  = np.arange(1,366), y  = log_fit(np.arange(1,366), *popt), name  = "log_fit"))
"""

code_four = """
df["month_dum"] = np.where(df["month"] < 7, df["month"] + 6, df["month"] - 6)
df = df.sort_values(by=["floor_area","month_dum"])
df["cum_value"] = df.groupby(["floor_area"])["monthly_total"].cumsum()
df["cum_days"] = df.groupby(["floor_area"])["days_per_month"].cumsum()
df["cum_value_norm"] = df.groupby(["floor_area"])["monthly_total"].transform(lambda x: (x.cumsum()/x.sum()))

cum_norm_fig = px.scatter(df, x="cum_days", y="cum_value_norm", color="floor_area")
cum_norm_fig.update_layout(xaxis_title="Days",yaxis_title="Fraction of annual gas use")

popt, pcov = curve_fit(log_model, df["cum_days"], df["cum_value_norm"],p0=starting_values,bounds=bounds)
cum_norm_fig.add_trace(go.Scatter(x=np.arange(1,366), y=log_model(np.arange(1,366), *popt), name="log_model"))

def gen_log_model(x, b, c, m, t):
    return (c / (1 + t * np.exp(-b*(x-m)))**1/t )

starting_values = [10/np.mean(df["cum_days"]),np.mean(df["cum_value_norm"]),np.mean(df["cum_days"]),2]
bounds = (0, [1, 2, 200,3])
popt, pcov = curve_fit(gen_log_model, df["cum_days"], df["cum_value_norm"],p0=starting_values,bounds=bounds)

cum_norm_fig.add_trace(go.Scatter(x=np.arange(1,366), y=gen_log_model(np.arange(1,366), *popt), name="gen_log_model"))
"""

@module.ui
def methods_ui():
    return [
      ui.tags.link(
        rel = "stylesheet",
        href = "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css"
      ),
      ui.tags.script(
        src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"
      ),
      ui.tags.script(
        src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"
      ),
      ui.h2("Methods"),
      ui.markdown("This application allows you to view your smart meter data and provide context to see how much energy you use relative to other similar households. It relies on data from a representative sample of 13000 households collected by the [Smart Energy Research Lab at UCL](https://serl.ac.uk/). They have produced a [report](https://discovery.ucl.ac.uk/id/eprint/10148066/1/SERL%20Stats%20Report%201.pdf), published a [paper](https://doi.org/10.1016/j.enbuild.2022.111845) and made the [summary data](https://rdr.ucl.ac.uk/ndownloader/files/35857037) available. Coming from a naive position as an energy researcher, but with previous experience benchmarking the performance of potato crops, I was surprised that there aren't any similar applications out there (as far as I can tell)."),
      ui.h3("Limitations"),
      ui.markdown("Before we start, it is important to note that there are many limitations to the approach taken to model daily energy demand and this should be considered more of a proof-of-concept for something that could be improved upon with access to more data. The data used only covers 2021 and there all sorts of confounding factors which can't be accounted for e.g. electric heating, electric cars, solar panels, alternative heating sources."),
      ui.h3("Motivations"),
      ui.markdown("Provide context relative to others, show multiple years data in a single view, not just show a myriad of bar charts, for gas use consider the start of the year as when heating is switched on"),
      ui.h3("Modelling gas use by floor area and occupants"),
      ui.markdown("Reading through the report, this figure showing gas use throughout the year depending on floor area really stood out to me and it looked as if it should be possible to use it derive a model to predict daily energy use depending on floor area."),
      # ui.img(src = "serl_fig_21.png"), #should work, but doesn't
      ui.output_image("serl_fig_21", height = "500px"),
      ui.markdown("There are a few challenges to deal with though - the floor areas are grouped, the data is provided as the median per day for each month and the pattern of usage over the year isn't easy to describe mathematically. I thought it would be easier to model if the data was rearranged to begin in August, with the daily median values converted to monthly totals and the monthly values converted to cumulative values."),
      ui.tags.pre(
        ui.tags.code(code_one, {"class": "language-python"})
      ),
      output_widget("cum_fig"),
      ui.markdown("This looked promising as now the data for each class of floor area looks like it can be described well by a logistic curve. I was curious how it would look if all the values for each class of floor area were divided by the total as it would be simplest if the pattern through the year was independent of floor area."),
      ui.tags.pre(
        ui.tags.code(code_two, {"class": "language-python"})
      ),
      output_widget("cum_norm_fig"),
      ui.markdown("Because there are such small differences in the normalised cumulative values, we'll go ahead and just fit one curve to all the data. The curve fitting function needs some help to find initial values and we also need to restrain `a` to be greater than zero or else we could end up predicting days with negative energy consumption."),
      ui.tags.pre(
        ui.tags.code(code_three, {"class": "language-python"})
      ),
      output_widget("cum_norm_fig_b"),
      ui.markdown("That looks reasonable and has a high *R<sup>2<sup/>* but the fit for the first few months is pretty poor (This is a nice example of why [*R<sup>2<sup/>* sucks](https://data.library.virginia.edu/is-r-squared-useless/) for evaulating models). There are a couple of tweaks that can be made to improve the fit. First of all, resetting the month_dum to start in July rather than August as this might affect the feasibility of fitting the curve and second using a generalised logistic curve instead which has an extra parameter."),
      ui.tags.pre(
        ui.tags.code(code_four, {"class": "language-python"})
      ),
      output_widget("cum_norm_fig_c"),
      ui.markdown("I'm pretty happy with this fit now, but to be able to convert these values back to actual gas usage, we need to look at the relationship between floor area and total gas usage. Helpfully, the data includes the actual mean floor area for each class as well as the class and so we'll use that to fit a power model"),
      output_widget("total_fig"),
      ui.markdown("Now we can use both models to produce estimates of the monthly totals and compare then with the actual values:"),
      output_widget("model_compare_fig"),
      ui.markdown("Whilst by no means perfect, the fit is satisfactory, but a challenge remains to account for how many occupants there are in the household. Ideally we would have the data available for every household so that we could build a model, but in the data we\"ve looked at so far we only have the median consumption for each category of floor area and the mean occupants in each category of floor area. In another figure though, there is data on the median usage depending on the number of occupants and the mean floor area for each category of occupancy. As we might expect, the two are inter-related - households with a larger floor area tend to have more occupants "),
      output_widget("occupancy_fig")
    ]

@module.server
def methods_server(input, output, session):
  
  with open("method_plots.pkl", "rb") as f:
    method_plots = pickle.load(f)
  
  
#   for key, val in method_plots.items():
#     # Define the function as a string, applying the decorator
#     function_code = f"""
# @render_plotly
# def {key}():
#   return method_plots['{key}']
# """
#     # Execute the generated function code in the global scope
#     exec(function_code, globals())

  @render_plotly
  def cum_fig():
    return method_plots["cum_fig"]

  @render_plotly
  def cum_norm_fig():
    return method_plots["cum_norm_fig"]

  @render_plotly
  def cum_norm_fig_b():
    return method_plots["cum_norm_fig_b"]

  @render_plotly
  def cum_norm_fig_c():
    return method_plots["cum_norm_fig_c"]
  
  @render_plotly
  def total_fig():
    return method_plots["total_fig"]
  
  @render_plotly
  def model_compare_fig():
    return method_plots["model_compare_fig"]
  
  @render_plotly
  def occupancy_fig():
    return method_plots["occupancy_fig"]
  
  @render.image
  def serl_fig_21():
    from shiny.types import ImgData
    from pathlib import Path
    dir = Path(__file__).resolve().parent
    img: ImgData = {"src": "serl_fig_21.png"}
    return img

  
