from dotenv import load_dotenv
load_dotenv()

# main.py - MCP Server for Google Maps routes
import os
import re
import html
from mcp.server.fastmcp import FastMCP
from maps_client import get_directions, find_nearby_waypoint, find_nearby_place

# Initialize FastMCP server
mcp = FastMCP("maps-routes")

# Constants
VALID_MODES = {"walking", "bicycling", "driving", "transit"}
# Calorie burn rates based on research (for average 155-lb person):
# Walking: ~85 cal/mile = ~53 cal/km
# Bicycling: ~37 cal/mile = ~23 cal/km
DEFAULT_KCAL_PER_KM = {
    "walking": 53.0,  # ~85 calories per mile for average person
    "bicycling": 23.0,  # ~37 calories per mile for average person
    "driving": 0.0,  # No calories burned driving
    "transit": 0.0,  # No calories burned on transit
}
MAX_CALORIES = 10000  # Reasonable upper limit
MIN_CALORIES = 10  # Reasonable lower limit
MAX_WALKING_CALORIES = 1000  # Suggest gym if target exceeds this (about 19km/12mi walk)


def detect_intent(query: str) -> str:
    """Detect the intent from a user query."""
    q = query.lower()
    if "burn" in q and "calorie" in q:
        return "fitness_route"
    if "route" in q or "directions" in q or "how to get" in q:
        return "directions"
    # add more later (travel_time, place_details, etc.)
    return "unknown"


def extract_calories(query: str) -> int | None:
    """Extract calorie amount from query. Looks for 'burn 300 calories'."""
    m = re.search(r"burn\s+(\d+)", query.lower())
    if m:
        return int(m.group(1))
    return None


def calories_to_km(calories: int, mode: str = "walking") -> float:
    """Convert calories to kilometers based on transportation mode.
    
    Args:
        calories: Number of calories to burn
        mode: Transportation mode (affects calories per km)
    
    Returns:
        Distance in kilometers needed to burn the calories
    """
    kcal_per_km = DEFAULT_KCAL_PER_KM.get(mode, DEFAULT_KCAL_PER_KM["walking"])
    if kcal_per_km == 0:
        return 0.0  # Can't burn calories with this mode
    return calories / kcal_per_km


def validate_mode(mode: str) -> str:
    """Validate and normalize transportation mode."""
    mode_lower = mode.lower()
    if mode_lower not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {', '.join(VALID_MODES)}")
    return mode_lower


def validate_calories(calories: int) -> int:
    """Validate calorie amount is within reasonable bounds."""
    if calories < MIN_CALORIES:
        raise ValueError(f"Calories must be at least {MIN_CALORIES}")
    if calories > MAX_CALORIES:
        raise ValueError(f"Calories must be at most {MAX_CALORIES}")
    return calories


def normalize_location(location: str) -> str:
    """Normalize and validate location string.
    
    Handles various formats:
    - "Place Name, City, State" (e.g., "Lincoln Park, Chicago, IL")
    - "City, State" (e.g., "Chicago, IL")
    - Street addresses (e.g., "123 Main St, Chicago, IL")
    - Coordinates (e.g., "41.8781, -87.6298")
    
    Args:
        location: Location string in any format
    
    Returns:
        Normalized location string (trimmed)
    
    Raises:
        ValueError: If location is empty or invalid
    """
    if not location or not location.strip():
        raise ValueError("Location cannot be empty")
    
    # Trim whitespace
    normalized = location.strip()
    
    # Basic validation - should have at least some content
    if len(normalized) < 2:
        raise ValueError("Location must be at least 2 characters")
    
    # Google Maps API can handle:
    # - Place names: "Lincoln Park, Chicago, IL"
    # - Street addresses: "123 Main St, Chicago, IL"
    # - City, State: "Chicago, IL"
    # - Coordinates: "41.8781, -87.6298"
    # - Plus codes, etc.
    
    # Just return normalized - Google Maps API will handle the parsing
    return normalized


def calculate_calories_from_distance(distance_m: float, mode: str) -> float:
    """Calculate calories burned from distance in meters.
    
    Args:
        distance_m: Distance in meters
        mode: Transportation mode
    
    Returns:
        Calories burned (rounded to 1 decimal place)
    """
    kcal_per_km = DEFAULT_KCAL_PER_KM.get(mode, DEFAULT_KCAL_PER_KM["walking"])
    if kcal_per_km == 0:
        return 0.0
    distance_km = distance_m / 1000
    return round(distance_km * kcal_per_km, 1)


def format_route_steps(steps: list[dict], mode: str = "walking") -> str:
    """Format route steps into a readable turn-by-turn directions with calories.
    
    Args:
        steps: List of step dictionaries from Google Maps API
        mode: Transportation mode for calorie calculation
    
    Returns:
        Formatted string with step-by-step directions including calories
    """
    if not steps:
        return "No detailed route steps available."
    
    formatted_steps = []
    for i, step in enumerate(steps, 1):
        # Clean HTML from instructions
        instruction = step.get("instruction", "")
        # Remove HTML tags
        instruction = re.sub(r'<[^>]+>', '', instruction)
        # Decode HTML entities
        instruction = html.unescape(instruction)
        
        distance = step.get("distance", "")
        distance_m = step.get("distance_m", 0)
        duration = step.get("duration", "")
        maneuver = step.get("maneuver", "")
        
        # Calculate calories for this step
        step_calories = calculate_calories_from_distance(distance_m, mode)
        
        step_text = f"{i}. {instruction}"
        if distance:
            step_text += f" ({distance}"
            if duration:
                step_text += f", {duration}"
            # Add calories if mode burns calories
            if step_calories > 0:
                step_text += f", ~{step_calories} kcal"
            step_text += ")"
        
        formatted_steps.append(step_text)
    
    return "\n".join(formatted_steps)


async def validate_location_with_api(location: str) -> tuple[bool, str]:
    """Validate location by attempting to geocode it.
    
    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is empty string
    """
    try:
        from maps_client import GOOGLE_MAPS_API_KEY
        if not GOOGLE_MAPS_API_KEY:
            return True, ""  # Can't validate without API key, assume valid
        
        import httpx
        geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
        geocode_params = {
            "address": location,
            "key": GOOGLE_MAPS_API_KEY,
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(geocode_url, params=geocode_params, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") == "OK" and data.get("results"):
                return True, ""
            elif data.get("status") == "ZERO_RESULTS":
                return False, f"Location '{location}' not found. Please check spelling or use a more specific address."
            elif data.get("status") == "INVALID_REQUEST":
                return False, f"Invalid location format: '{location}'"
            else:
                return False, f"Geocoding error: {data.get('status', 'UNKNOWN')}"
    except Exception:
        # If validation fails, don't block - let Google Maps API handle it
        return True, ""


@mcp.tool()
async def get_fitness_route(
    origin: str,
    target_calories: int,
    destination: str | None = None,
    mode: str = "walking"
) -> str:
    """Get a route that will help burn a specific number of calories.
    
    If no destination is provided, creates a loop route starting and ending at origin.
    
    Args:
        origin: Starting location (e.g., "Chicago, IL", "Lincoln Park, Chicago, IL", 
                "123 Main St, Chicago, IL", or "current location")
        target_calories: Number of calories to burn
        destination: Optional ending location. If None, creates a loop route back to origin.
                     Supports same formats as origin.
        mode: Transportation mode (walking, bicycling, driving, transit). Default: walking
    """
    # Validate inputs
    try:
        mode = validate_mode(mode)
        target_calories = validate_calories(target_calories)
        origin = normalize_location(origin)
        if destination:
            destination = normalize_location(destination)
    except ValueError as e:
        return f"Error: {str(e)}"
    
    # Optionally validate locations with API (non-blocking)
    origin_valid, origin_error = await validate_location_with_api(origin)
    if not origin_valid:
        return f"Error: {origin_error}"
    
    if destination:
        dest_valid, dest_error = await validate_location_with_api(destination)
        if not dest_valid:
            return f"Error: {dest_error}"
    
    # Check if mode can burn calories
    kcal_per_km = DEFAULT_KCAL_PER_KM.get(mode, DEFAULT_KCAL_PER_KM["walking"])
    if kcal_per_km == 0:
        return f"Error: Mode '{mode}' does not burn calories. Use 'walking' or 'bicycling' for fitness routes."
    
    # If calories are too high for walking, suggest gym
    if target_calories > MAX_WALKING_CALORIES and mode == "walking":
        gym = await find_nearby_place(origin, "gym", radius_m=10000)  # Search within 10km
        if gym:
            response = f"""Target Calories: {target_calories} kcal

⚠️ Note: Burning {target_calories} calories through walking alone would require approximately {calories_to_km(target_calories, mode):.1f} km (~{calories_to_km(target_calories, mode) * 0.621371:.1f} miles), which is quite a long walk!

💪 Gym Suggestion:
Instead, consider working out at a nearby gym:

Name: {gym['name']}
Address: {gym['address']}

You can burn {target_calories} calories much more efficiently at a gym through:
- Cardio exercises (running, cycling, rowing)
- Strength training
- High-intensity interval training (HIIT)

Would you like me to find a route to this gym instead?"""
            return response
        else:
            response = f"""Target Calories: {target_calories} kcal

⚠️ Note: Burning {target_calories} calories through walking alone would require approximately {calories_to_km(target_calories, mode):.1f} km (~{calories_to_km(target_calories, mode) * 0.621371:.1f} miles), which is quite a long walk!

💡 Suggestion: Consider finding a nearby gym for a more efficient workout. I couldn't find a gym nearby, but you might want to search for one manually.

I can still provide the walking route if you'd like, but it will be a very long distance."""
            # Continue with the route anyway
    
    # Calculate needed distance
    needed_km = calories_to_km(target_calories, mode)
    
    # If no destination, find a waypoint to create a loop route
    waypoints = None
    if destination is None:
        # Try to find a nearby waypoint that will create a route close to target distance
        waypoint = await find_nearby_waypoint(origin, needed_km / 2, mode)
        if waypoint:
            waypoints = [waypoint]
    
    # Get directions (will create loop if destination is None)
    directions = await get_directions(origin, destination, mode=mode, waypoints=waypoints)
    
    if "error" in directions:
        return f"Error getting directions: {directions['error']}"
    
    # Format response
    route_distance_km = directions["distance_m"] / 1000
    is_loop = directions.get("is_loop", False) or destination is None
    
    # Calculate total calories burned for this route
    total_calories_burned = calculate_calories_from_distance(directions["distance_m"], mode)
    
    response = f"""Fitness Route Information:
    
Target Calories: {target_calories} kcal
Needed Distance: {needed_km:.2f} km (at ~{kcal_per_km:.0f} kcal/km for {mode})

Route Details:
Origin: {directions['origin']}
"""
    
    if is_loop:
        response += f"Route Type: Loop (returns to start)\n"
    else:
        response += f"Destination: {directions['destination']}\n"
    
    response += f"Distance: {directions['distance_text']} ({route_distance_km:.2f} km)\n"
    response += f"Duration: {directions['duration_text']}\n"
    response += f"Mode: {directions['mode']}\n"
    if total_calories_burned > 0:
        response += f"Total Calories Burned: ~{total_calories_burned:.1f} kcal\n"
    response += "\n"
    
    # Compare actual route distance to needed distance
    if route_distance_km < needed_km:
        additional_km = needed_km - route_distance_km
        response += f"Note: This route is {additional_km:.2f} km shorter than needed. "
        if is_loop:
            response += f"You may want to extend the loop or make multiple loops to burn {target_calories} calories."
        else:
            response += f"You may need to extend the route or make multiple trips to burn {target_calories} calories."
    elif route_distance_km >= needed_km:
        response += f"Great! This route should help you burn approximately {target_calories} calories."
    
    # Add detailed route steps
    steps = directions.get("steps", [])
    if steps:
        response += "\n\n--- Detailed Route Steps ---\n\n"
        response += format_route_steps(steps, mode)
    
    return response


@mcp.tool()
async def get_route(
    origin: str,
    destination: str | None = None,
    mode: str = "driving"
) -> str:
    """Get directions between two locations.
    
    If no destination is provided, creates a loop route starting and ending at origin.
    
    Args:
        origin: Starting location (e.g., "Chicago, IL", "Lincoln Park, Chicago, IL",
                "123 Main St, Chicago, IL", or "current location")
        destination: Optional ending location. If None, creates a loop route back to origin.
                     Supports same formats as origin.
        mode: Transportation mode (walking, bicycling, driving, transit). Default: driving
    """
    # Validate inputs
    try:
        mode = validate_mode(mode)
        origin = normalize_location(origin)
        if destination:
            destination = normalize_location(destination)
    except ValueError as e:
        return f"Error: {str(e)}"
    
    # Optionally validate locations with API (non-blocking)
    origin_valid, origin_error = await validate_location_with_api(origin)
    if not origin_valid:
        return f"Error: {origin_error}"
    
    if destination:
        dest_valid, dest_error = await validate_location_with_api(destination)
        if not dest_valid:
            return f"Error: {dest_error}"
    
    # If no destination, find a waypoint to create a meaningful loop
    waypoints = None
    if destination is None:
        # Find a nearby waypoint for a loop route (use ~2km as default target)
        waypoint = await find_nearby_waypoint(origin, 2.0, mode)
        if waypoint:
            waypoints = [waypoint]
    
    directions = await get_directions(origin, destination, mode=mode, waypoints=waypoints)
    
    if "error" in directions:
        return f"Error getting directions: {directions['error']}"
    
    is_loop = directions.get("is_loop", False) or destination is None
    
    response = f"""Route Information:

Origin: {directions['origin']}
"""
    
    if is_loop:
        response += f"Route Type: Loop (returns to start)\n"
    else:
        response += f"Destination: {directions['destination']}\n"
    
    response += f"Distance: {directions['distance_text']}\n"
    response += f"Duration: {directions['duration_text']}\n"
    response += f"Mode: {directions['mode']}"
    
    # Calculate and add total calories burned (if mode burns calories)
    total_calories_burned = calculate_calories_from_distance(directions["distance_m"], mode)
    if total_calories_burned > 0:
        response += f"\nTotal Calories Burned: ~{total_calories_burned:.1f} kcal"
    
    # Add detailed route steps
    steps = directions.get("steps", [])
    if steps:
        response += "\n\n--- Detailed Route Steps ---\n\n"
        response += format_route_steps(steps, mode)
    
    return response


@mcp.tool()
async def find_nearest(origin: str, place_type: str, radius_km: float = 5.0) -> str:
    """Find the nearest place of a specific type from a location.
    
    Args:
        origin: Starting location (e.g., "Chicago, IL" or "123 Main St, Chicago, IL")
        place_type: Type of place to find (e.g., "gym", "park", "restaurant", "hospital", "gas_station")
        radius_km: Search radius in kilometers (default: 5.0 km)
    
    Returns:
        Information about the nearest place found
    """
    try:
        origin = normalize_location(origin)
    except ValueError as e:
        return f"Error: {str(e)}"
    
    # Validate location with API
    origin_valid, origin_error = await validate_location_with_api(origin)
    if not origin_valid:
        return f"Error: {origin_error}"
    
    # Find nearby place
    radius_m = int(radius_km * 1000)
    place = await find_nearby_place(origin, place_type, radius_m)
    
    if not place:
        return f"No {place_type} found within {radius_km} km of {origin}. Try increasing the search radius or checking a different location."
    
    response = f"""Nearest {place_type.title()}:

Name: {place['name']}
Address: {place['address']}

Would you like directions to this location?"""
    
    return response


@mcp.tool()
async def query_route(query: str) -> str:
    """Process a natural language query about routes or directions.
    
    This tool can detect intents like fitness routes (burn calories) or regular directions.
    
    Args:
        query: Natural language query (e.g., "burn 300 calories from Chicago to Lincoln Park")
    """
    intent = detect_intent(query)

    if intent == "fitness_route":
        target_cal = extract_calories(query)
        if not target_cal:
            return "Error: Could not find calorie amount in query. Please include something like 'burn 300 calories'."
        
        # Use default origin (can be set to "current location" in .env)
        origin = os.getenv("DEFAULT_ORIGIN", "Chicago, IL")
        # For fitness routes without destination, create a loop
        destination = None  # Will create a loop route
        
        return await get_fitness_route(origin, target_cal, destination=None, mode="walking")
    
    elif intent == "directions":
        # Use default origin
        origin = os.getenv("DEFAULT_ORIGIN", "Chicago, IL")
        # For directions without destination, create a loop
        destination = None  # Will create a loop route
        
        return await get_route(origin, destination=None, mode="driving")
    
    else:
        return f"Could not understand query intent. Detected: {intent}. Please be more specific about what you need."


def main():
    """Initialize and run the MCP server."""
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()
