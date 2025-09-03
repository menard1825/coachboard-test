from flask import jsonify, request, session
from . import api_bp
from .decorators import login_required
import requests
from datetime import datetime
import re
from models import Team
from db import db

@api_bp.route('/weather/<location>')
@login_required
def get_weather(location):
    """
    Fetches weather data for a given location using the Open-Meteo API.
    Now accepts an optional 'date' query parameter.
    """
    if not location or not location.strip():
        return jsonify({"error": "Location is required"}), 400

    team_id = session.get('team_id')
    team = db.session.get(Team, team_id) if team_id else None
    default_location = team.default_practice_location if team and team.default_practice_location and team.default_practice_location.strip() else None

    parsed_location = location.strip()
    if re.match(r'^[Dd]\d+$', parsed_location):
        if default_location:
            parsed_location = default_location
        else:
            return jsonify({"error": "Shorthand location used, but no default practice location is set in Team Settings."}), 400
    elif "grand park" in parsed_location.lower():
        parsed_location = "Grand Park"

    forecast_date_str = request.args.get('date')

    try:
        # Step 1: Geocode the location to get latitude and longitude
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {'name': parsed_location, 'count': 1, 'format': 'json'}
        geo_response = requests.get(geocoding_url, params=geo_params, timeout=10)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return jsonify({"error": f"Location '{parsed_location}' not found"}), 404

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        # Step 2: Get weather forecast
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "auto"
        }
        if forecast_date_str:
            params["start_date"] = forecast_date_str
            params["end_date"] = forecast_date_str
        else:
            params["current_weather"] = "true"

        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_response = requests.get(weather_url, params=params, timeout=10)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        #
        # --- START OF CHANGES ---
        #
        # Step 3: More robustly simplify the data for the frontend
        simplified_data = {
            "current_temp": "N/A", "wind": "N/A", "condition": "N/A",
            "high_temp": "N/A", "low_temp": "N/A", "precipitation": "N/A"
        }

        daily_weather = weather_data.get("daily", {})
        if daily_weather:
            high_temps = daily_weather.get('temperature_2m_max', [])
            if high_temps and high_temps[0] is not None:
                simplified_data["high_temp"] = f"{round(high_temps[0])}°F"

            low_temps = daily_weather.get('temperature_2m_min', [])
            if low_temps and low_temps[0] is not None:
                simplified_data["low_temp"] = f"{round(low_temps[0])}°F"

            precip_probs = daily_weather.get('precipitation_probability_max', [])
            if precip_probs and precip_probs[0] is not None:
                simplified_data["precipitation"] = f"{precip_probs[0]}%"

        if forecast_date_str:
            simplified_data["condition"] = "Forecast"
        else:
            current_weather = weather_data.get("current_weather", {})
            if current_weather:
                simplified_data["condition"] = "Current"
                if current_weather.get('temperature') is not None:
                    simplified_data["current_temp"] = f"{round(current_weather.get('temperature'))}°F"
                if current_weather.get('windspeed') is not None:
                    simplified_data["wind"] = f"{round(current_weather.get('windspeed'))} mph"

        return jsonify(simplified_data)
        #
        # --- END OF CHANGES ---
        #

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Could not connect to weather service.", "details": str(e)}), 500
    except (IndexError, KeyError) as e:
        return jsonify({"error": "Could not parse weather data.", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500
