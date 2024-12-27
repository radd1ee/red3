import requests
import json
from flask import Flask, render_template, request, jsonify
import plotly.graph_objects as go
import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
from datetime import datetime
import folium
from folium.plugins import MarkerCluster
from API import API_KEY

LOCATIONS_FILE = "static/locations.json"

def load_locations():
    try:
        with open(LOCATIONS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_locations(locations):
    with open(LOCATIONS_FILE, "w", encoding="utf-8") as file:
        json.dump(locations, file, ensure_ascii=False, indent=4)

locations = load_locations()

def get_weather_data(latitude, longitude):
    try:
        location_url = "http://dataservice.accuweather.com/locations/v1/cities/geoposition/search"
        location_params = {
            "apikey": API_KEY,
            "q": f"{latitude},{longitude}",
            "language": "ru-ru"
        }
        response = requests.get(location_url, params=location_params)
        response.raise_for_status()
        location_data = response.json()
        location_key = location_data["Key"]

        forecast_url = f"http://dataservice.accuweather.com/forecasts/v1/daily/5day/{location_key}"
        forecast_params = {
            "apikey": API_KEY,
            "language": "ru-ru",
            "details": True,
            "metric": True
        }
        response = requests.get(forecast_url, params=forecast_params)
        response.raise_for_status()
        forecast_data = response.json()

        dates = []
        temperatures = []
        humidities = []
        wind_speeds = []
        precip_probs = []

        for day in forecast_data["DailyForecasts"]:
            dates.append(datetime.fromtimestamp(day["EpochDate"]).strftime('%Y-%m-%d'))
            temperatures.append(round((day["Temperature"]["Minimum"]["Value"] + day["Temperature"]["Maximum"]["Value"]) / 2, 1))
            wind_speeds.append(day["Day"]["Wind"]["Speed"]["Value"])
            precip_probs.append(day["Day"]["PrecipitationProbability"])
            humidities.append(round((day["Day"]["RelativeHumidity"]["Minimum"] + day["Day"]["RelativeHumidity"]["Maximum"]) / 2))

        return {
            "Dates": dates,
            "Temperatures": temperatures,
            "Humidities": humidities,
            "Wind_speeds": wind_speeds,
            "Precip_probs": precip_probs
        }
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None
    except KeyError as e:
        print(f"Ошибка обработки данных JSON: {e}")
        return None

def check_bad_weather(temperature, wind_speed, precipitation_probability):
    str_to_return = "Good"
    if temperature < 0 or temperature > 35 or wind_speed > 50 or precipitation_probability > 70:
        str_to_return = "Bad"
        if temperature < 0:
            str_to_return += ", слишком холодно"
        if temperature > 35:
            str_to_return += ", слишком жарко"
        if wind_speed > 50:
            str_to_return += ", слишком сильный ветер"
        if precipitation_probability > 70:
            str_to_return += ", слишком высокая вероятность осадков"
    return str_to_return

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    weather_condition = []
    error_message = None
    overall_condition = "Можно отправляться!"

    if request.method == 'POST':
        try:
            start_location = str(request.form['start_location']).lower().title()
            stops = request.form['stops'].split(',') if request.form['stops'] else []
            end_location = str(request.form['end_location']).lower().title()
            days = int(request.form['days'])

            locations_to_check = [start_location] + [stop.strip().lower().title() for stop in stops] + [end_location]
            for location in locations_to_check:
                coords = get_coordinates(location)
                if coords is None:
                    raise ValueError(f"Не удалось найти координаты для '{location}'.")

                forecast_data = get_weather_data(coords[0], coords[1])
                if not forecast_data:
                    raise ValueError(f"Ошибка получения данных о погоде для '{location}'.")

                forecast_summary = f"Температура: {forecast_data['Temperatures'][:days]} °C, " \
                                   f"Влажность: {forecast_data['Humidities'][:days]} %, " \
                                   f"Ветер: {forecast_data['Wind_speeds'][:days]} км/ч, " \
                                   f"Осадки: {forecast_data['Precip_probs'][:days]} %."
                weather_condition.append({
                    "location": location,
                    "condition": forecast_summary
                })

                for i in range(days):
                    if forecast_data['Temperatures'][i] < 0 or forecast_data['Temperatures'][i] > 35 or forecast_data['Wind_speeds'][i] > 50 or forecast_data['Precip_probs'][i] > 70:
                        overall_condition = "Сейчас не время для путешествий!"
                        break

        except (KeyError, ValueError, requests.exceptions.RequestException) as e:
            error_message = f"Ошибка: {e}"

    return render_template('index.html', weather_condition=weather_condition, error_message=error_message, overall_condition=overall_condition)

@app.route('/add_city', methods=['GET', 'POST'])
def add_city():
    error_message = None
    success_message = None

    if request.method == 'POST':
        city_name = request.form['city_name']
        latitude = request.form['latitude']
        longitude = request.form['longitude']

        if city_name and latitude and longitude:
            try:
                latitude = float(latitude)
                longitude = float(longitude)

                # Сохранение города в словарь
                locations[city_name] = [latitude, longitude]
                save_locations(locations)
                success_message = f"Город {city_name} успешно добавлен!"
            except ValueError:
                error_message = "Ошибка: широта и долгота должны быть числовыми."
        else:
            error_message = "Ошибка: все поля должны быть заполнены."

    return render_template('add_city.html', locations=locations, error_message=error_message, success_message=success_message)

def get_coordinates(location_name):
    return locations.get(location_name)

app_dash = dash.Dash(__name__, server=app, url_base_pathname='/dashboard/')
app_dash.layout = html.Div([
    html.H1("Прогноз погоды на маршруте"),
    dcc.Dropdown(
        id='city-dropdown',
        options=[{'label': city, 'value': city} for city in locations.keys()],
        multi=True,
        placeholder="Выберите точки маршрута"
    ),
    dcc.Graph(id='weather-graph'),
    dcc.RadioItems(
        id='parameter-selector',
        options=[
            {'label': 'Температура (°C)', 'value': 'Temperatures'},
            {'label': 'Влажность (%)', 'value': 'Humidities'},
            {'label': 'Скорость ветра (км/ч)', 'value': 'Wind_speeds'},
            {'label': 'Вероятность осадков (%)', 'value': 'Precip_probs'}
        ],
        value='Temperatures',
        inline=True
    ),
    dcc.RangeSlider(
        id='time-slider',
        min=1,
        max=5,
        step=1,
        marks={i: f"{i} дн." for i in range(1, 6)},
        value=[1, 5]
    ),
    html.A(html.Button('Вернуться на главную'), href='/')
])

@app_dash.callback(
    Output('weather-graph', 'figure'),
    [Input('city-dropdown', 'value'),
     Input('parameter-selector', 'value'),
     Input('time-slider', 'value')]
)
def update_graph(selected_cities, parameter, time_range):
    if not selected_cities or not parameter:
        return go.Figure()

    start, end = time_range
    figure = go.Figure()
    for city in selected_cities:
        latitude, longitude = locations[city]
        forecast_data = get_weather_data(latitude, longitude)
        if not forecast_data:
            continue

        figure.add_trace(go.Scatter(
            x=forecast_data['Dates'][start - 1:end],
            y=forecast_data[parameter][start - 1:end],
            mode='lines+markers',
            name=city,
            text=[
                f"{parameter}: {value}" for value in forecast_data[parameter][start - 1:end]
            ],
            hoverinfo="text"
        ))

        figure.update_layout(
            title="Прогноз погоды для маршрута",
            xaxis_title="Дата",
            yaxis_title=parameter,
            legend_title="Города",
            hovermode="closest"
        )

    return figure

@app.route('/map', methods=['POST'])
def show_map():
    try:
        # Получаем данные из формы
        start_location = str(request.form['start_location']).lower().title()
        stops = request.form['stops'].split(',') if request.form['stops'] else []
        end_location = str(request.form['end_location']).lower().title()

        locations_to_check = [start_location] + [str(stop.strip()).lower().title() for stop in stops] + [end_location]

        map_center = locations.get(start_location) or [0, 0]
        route_map = folium.Map(location=map_center, zoom_start=6)
        marker_cluster = MarkerCluster().add_to(route_map)

        for location in locations_to_check:
            coords = get_coordinates(location)
            if coords is None:
                raise ValueError(f"Сначала посмотри прогноз для этого маршрута")

            forecast_data = get_weather_data(coords[0], coords[1])
            if not forecast_data:
                raise ValueError(f"Ошибка получения данных о погоде для '{location}'.")

            popup_content = (
                f"<b>{location}</b><br>"
                f"Температура: {forecast_data['Temperatures'][0]} °C<br>"
                f"Влажность: {forecast_data['Humidities'][0]} %<br>"
                f"Ветер: {forecast_data['Wind_speeds'][0]} км/ч<br>"
                f"Осадки: {forecast_data['Precip_probs'][0]} %"
            )
            folium.Marker(
                location=coords,
                popup=folium.Popup(popup_content, max_width=300),
                tooltip=f"Погода в {location}"
            ).add_to(marker_cluster)

        route_map.save('templates/map.html')
        return render_template('map.html')
    except Exception as e:
        return f"Ошибка: {e}"

if __name__ == '__main__':
    app.run(debug=True)