from flask import jsonify
from . import api_bp
from .decorators import login_required
import requests

@api_bp.route('/weather/<location>')
@login_required
def get_weather(location):
    """
    Fetches weather data for a given location using the Open-Meteo API.
    """
    if not location:
        return jsonify({"error": "Location is required"}), 400

    try:
        # Step 1: Geocode the location to get latitude and longitude
        geocoding_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1"
        geo_response = requests.get(geocoding_url)
        geo_response.raise_for_status()  # Raise an exception for bad status codes
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return jsonify({"error": "Location not found"}), 404

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        # Step 2: Get weather forecast for the coordinates
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto"
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current_weather = weather_data.get("current_weather", {})
        daily_weather = weather_data.get("daily", {})

        # Step 3: Simplify the data for the frontend
        simplified_data = {
            "current_temp": f"{current_weather.get('temperature')}°C",
            "wind": f"{current_weather.get('windspeed')} km/h",
            "condition": "N/A",  # Open-Meteo doesn't provide a simple condition string in the free tier
            "high_temp": f"{daily_weather.get('temperature_2m_max', [None])[0]}°C",
            "low_temp": f"{daily_weather.get('temperature_2m_min', [None])[0]}°C",
            "precipitation": f"{daily_weather.get('precipitation_probability_max', [None])[0]}%"
        }

        return jsonify(simplified_data)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Could not connect to weather service.", "details": str(e)}), 500
    except (IndexError, KeyError) as e:
        return jsonify({"error": "Could not parse weather data.", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500
