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
    #
    # --- START OF CHANGES ---
    #
    if not location or not location.strip():
        return jsonify({"error": "Location is required"}), 400

    team_id = session.get('team_id')
    team = db.session.get(Team, team_id) if team_id else None
    default_location = team.default_practice_location if team else None

    parsed_location = location.strip()
    # Handle shorthand like "D1", "d2", etc.
    if re.match(r'^[Dd]\d+$', parsed_location):
        if default_location:
            parsed_location = default_location
        else:
            # If there's no default location set, we can't resolve the shorthand.
            return jsonify({"error": "Shorthand location used, but no default practice location is set in Team Settings."}), 400
    elif "grand park" in parsed_location.lower():
        parsed_location = "Grand Park Sports Campus"
    #
    # --- END OF CHANGES ---
    #

    forecast_date_str = request.args.get('date')

    try:
        # Step 1: Geocode the location to get latitude and longitude
        geocoding_url = f"https://geocoding-api.open-meteo.com/v1/search?name={parsed_location}&count=1"
        geo_response = requests.get(geocoding_url, timeout=10) # Added timeout
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

        weather_url = f"https://api.open-meteo.com/v1/forecast"
        weather_response = requests.get(weather_url, params=params, timeout=10) # Added timeout
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        # Step 3: Simplify the data for the frontend
        if forecast_date_str:
            daily_weather = weather_data.get("daily", {})
            simplified_data = {
                "current_temp": "N/A",
                "wind": "N/A",
                "condition": "Forecast",
                "high_temp": f"{daily_weather.get('temperature_2m_max', [None])[0]}°F",
                "low_temp": f"{daily_weather.get('temperature_2m_min', [None])[0]}°F",
                "precipitation": f"{daily_weather.get('precipitation_probability_max', [None])[0]}%"
            }
        else:
            current_weather = weather_data.get("current_weather", {})
            daily_weather = weather_data.get("daily", {})
            simplified_data = {
                "current_temp": f"{current_weather.get('temperature')}°F",
                "wind": f"{current_weather.get('windspeed')} mph",
                "condition": "Current",
                "high_temp": f"{daily_weather.get('temperature_2m_max', [None])[0]}°F",
                "low_temp": f"{daily_weather.get('temperature_2m_min', [None])[0]}°F",
                "precipitation": f"{daily_weather.get('precipitation_probability_max', [None])[0]}%"
            }

        return jsonify(simplified_data)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Could not connect to weather service.", "details": str(e)}), 500
    except (IndexError, KeyError) as e:
        return jsonify({"error": "Could not parse weather data.", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500
