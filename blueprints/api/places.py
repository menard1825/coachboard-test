import os
import requests
from flask import jsonify, request
from . import api_bp

@api_bp.route('/places/autocomplete')
def places_autocomplete():
    """
    Provides Google Places API autocomplete suggestions.
    """
    search_input = request.args.get('input', '')
    if not search_input:
        return jsonify([])

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        # This is a server configuration issue, so we log it but don't expose details to the client.
        print("ERROR: GOOGLE_MAPS_API_KEY is not set in the environment.")
        return jsonify([])

    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {
        'input': search_input,
        'key': api_key,
        'types': 'geocode'
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get('status') == 'OK':
            predictions = [prediction['description'] for prediction in data.get('predictions', [])]
            return jsonify(predictions)
        else:
            # Log the error from Google for debugging, but return an empty list to the client.
            print(f"Google Places API Error: {data.get('status')} - {data.get('error_message', '')}")
            return jsonify([])

    except requests.exceptions.RequestException as e:
        print(f"Could not connect to Google Places service: {e}")
        return jsonify([])
    except (KeyError, IndexError) as e:
        print(f"Could not parse Google Places API response: {e}")
        return jsonify([])
