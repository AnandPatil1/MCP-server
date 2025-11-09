from dotenv import load_dotenv
load_dotenv()


# maps_client.py
import os
import httpx
from typing import Any

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")


async def find_nearby_place(origin: str, place_type: str, radius_m: int = 5000) -> dict[str, Any] | None:
    """Find a nearby place of a specific type.
    
    Args:
        origin: Starting location
        place_type: Type of place to find (e.g., "gym", "park", "restaurant")
        radius_m: Search radius in meters (default: 5000m = 5km)
    
    Returns:
        Dictionary with place info (name, address, location) or None if not found
    """
    if not GOOGLE_MAPS_API_KEY:
        return None
    
    # Get coordinates of origin
    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
    geocode_params = {
        "address": origin,
        "key": GOOGLE_MAPS_API_KEY,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(geocode_url, params=geocode_params, timeout=10.0)
            resp.raise_for_status()
            geocode_data = resp.json()
            
            if geocode_data.get("status") != "OK" or not geocode_data.get("results"):
                return None
            
            location = geocode_data["results"][0]["geometry"]["location"]
            lat = location["lat"]
            lng = location["lng"]
            
            # Use Places API to find nearby place
            places_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            places_params = {
                "location": f"{lat},{lng}",
                "radius": radius_m,
                "type": place_type,
                "key": GOOGLE_MAPS_API_KEY,
            }
            
            resp = await client.get(places_url, params=places_params, timeout=10.0)
            resp.raise_for_status()
            places_data = resp.json()
            
            if places_data.get("status") == "OK" and places_data.get("results"):
                place = places_data["results"][0]
                place_location = place.get("geometry", {}).get("location", {})
                
                return {
                    "name": place.get("name", ""),
                    "address": place.get("vicinity") or place.get("formatted_address", ""),
                    "location": f"{place_location.get('lat', '')},{place_location.get('lng', '')}",
                    "place_id": place.get("place_id", ""),
                }
        except Exception:
            pass
    
    return None


async def find_nearby_waypoint(origin: str, target_distance_km: float, mode: str = "walking") -> str | None:
    """Find a nearby waypoint to create a loop route of approximately target_distance_km.
    Uses Places API to find nearby points of interest."""
    if not GOOGLE_MAPS_API_KEY:
        return None
    
    # First, get coordinates of origin using Geocoding API
    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
    geocode_params = {
        "address": origin,
        "key": GOOGLE_MAPS_API_KEY,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(geocode_url, params=geocode_params, timeout=10.0)
            resp.raise_for_status()
            geocode_data = resp.json()
            
            if geocode_data.get("status") != "OK" or not geocode_data.get("results"):
                return None
            
            location = geocode_data["results"][0]["geometry"]["location"]
            lat = location["lat"]
            lng = location["lng"]
            
            # Use Places API to find nearby points of interest
            # Note: Places API type parameter should be a single type, not pipe-separated
            # We'll try multiple types and pick the best result
            places_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            place_types = ["park", "point_of_interest", "establishment"]
            radius = max(500, int(target_distance_km * 1000 * 0.6))  # At least 500m, or 60% of target
            
            for place_type in place_types:
                places_params = {
                    "location": f"{lat},{lng}",
                    "radius": radius,
                    "type": place_type,
                    "key": GOOGLE_MAPS_API_KEY,
                }
                
                resp = await client.get(places_url, params=places_params, timeout=10.0)
                resp.raise_for_status()
                places_data = resp.json()
                
                if places_data.get("status") == "OK" and places_data.get("results"):
                    # Return the first nearby place as a waypoint
                    place = places_data["results"][0]
                    # Prefer formatted_address or vicinity, fallback to name
                    waypoint_name = place.get("vicinity") or place.get("formatted_address") or place.get("name")
                    if waypoint_name:
                        return waypoint_name
            
        except (httpx.HTTPError, httpx.TimeoutException, KeyError, IndexError) as e:
            # Log specific error types but don't expose to user
            pass
        except Exception as e:
            # Catch-all for unexpected errors
            pass
    
    return None


async def get_directions(
    origin: str, 
    destination: str | None = None, 
    mode: str = "walking",
    waypoints: list[str] | None = None
) -> dict[str, Any]:
    """Get directions from Google Maps API.
    
    Args:
        origin: Starting location
        destination: Ending location. If None, creates a loop route back to origin.
        mode: Transportation mode
        waypoints: Optional list of waypoints to visit
    """
    if not GOOGLE_MAPS_API_KEY:
        return {"error": "GOOGLE_MAPS_API_KEY not set"}

    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "mode": mode,
        "key": GOOGLE_MAPS_API_KEY,
    }
    
    # If no destination, create a loop back to origin using waypoints
    if destination is None:
        params["destination"] = origin
        # Try to find a nearby waypoint to create a meaningful loop
        if not waypoints:
            # For now, we'll create a simple loop by using origin as both start and end
            # The API will optimize this, but it may return a very short route
            # A better implementation would find a nearby waypoint first
            pass
        if waypoints:
            params["waypoints"] = "|".join(waypoints)
    else:
        params["destination"] = destination
        if waypoints:
            params["waypoints"] = "|".join(waypoints)
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            return {"error": "Request timed out. Please try again."}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP error {e.response.status_code}: {e.response.text[:100]}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    if data.get("status") != "OK":
        return {"error": data.get("status", "UNKNOWN_ERROR"), "raw": data}

    # Calculate total distance and duration across all legs
    route = data["routes"][0]
    total_distance_m = 0
    total_duration_s = 0
    legs = route["legs"]
    all_steps = []
    
    # Extract steps from all legs
    for leg in legs:
        total_distance_m += leg["distance"]["value"]
        total_duration_s += leg["duration"]["value"]
        
        # Extract steps from this leg
        if "steps" in leg:
            for step in leg["steps"]:
                all_steps.append({
                    "instruction": step.get("html_instructions", ""),
                    "distance": step.get("distance", {}).get("text", ""),
                    "distance_m": step.get("distance", {}).get("value", 0),  # Distance in meters
                    "duration": step.get("duration", {}).get("text", ""),
                    "maneuver": step.get("maneuver", ""),
                })
    
    # Use API's formatted text, or combine if multiple legs
    if len(legs) == 1:
        distance_text = legs[0]["distance"]["text"]
        duration_text = legs[0]["duration"]["text"]
    else:
        # For multiple legs, show total
        if total_distance_m < 1000:
            distance_text = f"{total_distance_m} m"
        else:
            distance_text = f"{total_distance_m / 1000:.2f} km"
        
        hours = total_duration_s // 3600
        minutes = (total_duration_s % 3600) // 60
        if hours > 0:
            duration_text = f"{hours}h {minutes}m"
        else:
            duration_text = f"{minutes}m"
    
    return {
        "origin": legs[0].get("start_address"),
        "destination": legs[-1].get("end_address"),
        "distance_m": total_distance_m,
        "distance_text": distance_text,
        "duration_s": total_duration_s,
        "duration_text": duration_text,
        "mode": mode,
        "is_loop": destination is None,
        "legs": len(legs),
        "steps": all_steps,  # Detailed route steps
    }
