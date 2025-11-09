# MCP Server: Google Maps + Fitness Routes

## Purpose

This MCP server turns natural-language route and activity queries into live Google Maps calls and returns structured context for an AI assistant. It can:

* turn “route to burn 300 calories” into a distance estimate
* fetch walking directions from Google Maps
* optionally find nearby places to use as waypoints

The goal is to make the AI’s answer location-aware and goal-aware (calories → distance → real route).

## Data Sources / APIs

* Google Maps Geocoding API
* Google Maps Directions API
* Google Maps Places API (Nearby Search)

These are used to resolve text locations to coordinates, get real route distance/duration, and optionally find nearby places.

## Requirements

* Python 3.10+
* A Google Maps Platform API key with the above APIs enabled
* Packages from `requirements.txt`

## Environment Variables

Create a `.env` file in the project root (This file can be pasted by copying .env.example):

```text
GOOGLE_MAPS_API_KEY=YOUR_KEY_HERE
DEFAULT_ORIGIN=Memorial Student Center, College Station, TX
DEFAULT_DESTINATION=Century Tree, College Station, TX
```

Notes:

* `DEFAULT_ORIGIN` is used when the query does not specify a start.
* You can change these to locations relevant to you.

## Installation and Run

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

This starts the MCP server that exposes the tools defined in `main.py`.

## How It Works

1. The server receives a query/tool call.
2. It detects intent, for example: a fitness route request.
3. It converts calories → approximate distance (documented assumption).
4. It calls Google Maps (geocoding, directions, places) to build a real route.
5. It returns a context package that an AI can use directly.

## Example Prompts

* **Route to burn 300 calories.**
* **Give me a walking route from the Memorial Student Center that burns 400 calories.**
* **Plan a walking loop near the Memorial Student Center so I end where I start.**
* **Find a nearby gym from Texas A&M, College Station.**
* **I have 30 minutes to walk right now, starting at the Memorial Student Center.**

## More Prompts

* **Route to burn 500 calories from Texas A&M, College Station.**
* **I need a 4 km walk starting near the Memorial Student Center.**
* **Make the route cycling instead of walking, from the Memorial Student Center to the Century Tree.**
* **Give me walking directions from the Memorial Student Center to the Century Tree.**
* **Find a nearby park I can walk to in College Station.**
* **Give me a route I can finish in under an hour, starting at the Memorial Student Center.**
* **Give me a route to the closest coffee shop from Texas A&M, College Station.**
* **What’s the best walking route to campus landmarks from Texas A&M, College Station.**

## Assumptions (Documented)

* Calorie burn is approximated with a fixed value in code (e.g. 50 kcal/km for walking). This is to keep the MCP logic simple and predictable.
* When the user does not provide origin/destination, the server falls back to the defaults from `.env`.
* Google Maps API must be enabled in the Google Cloud project for the calls to succeed.

## Running in an MCP-Capable Client

* Register this server under the name shown in `main.py` (for example `"maps-routes"`).
* Point the client to run `python main.py`.
* Then issue one of the example prompts above from the client so it forwards to this MCP server.

## Using with Claude Desktop

If you want Claude Desktop to call this MCP server, add a new file (or update) called `claude_desktop_config.json` if it doesn't exist to register the server, for example:

```json
{
  "mcpServers": {
    "maps-routes": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\fitness-routes",
        "run",
        "main.py"
      ]
    }
  }
}
```

## Troubleshooting

* If the response contains `"error": "REQUEST_DENIED"` or similar, check:

  * API key is present
  * Billing is enabled
  * Directions/Geocoding/Places are enabled
* If the response is empty, ensure `.env` is loaded and the server was started in the same environment.
