# MCP Server
### Sqlite
github mcp sqlite server:https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite
### Init Sqlite
init database
```shell
sqlite3 /Users/hening/hening/study/AICG/mcp/test.db
```


```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT,
    price REAL
);
INSERT INTO products (id, name, price) VALUES (1, 'Laptop', 999.99);
INSERT INTO products (id, name, price) VALUES (2, 'Smartphone', 599.50);
INSERT INTO products (id, name, price) VALUES (3, 'Headphones', 79.95);
INSERT INTO products (id, name, price) VALUES (4, 'Mouse', 29.99);
INSERT INTO products (id, name, price) VALUES (5, 'Keyboard', 49.90);
INSERT INTO products (id, name, price) VALUES (6, 'Monitor', 199.75);
INSERT INTO products (id, name, price) VALUES (7, 'USB Cable', 9.99);
INSERT INTO products (id, name, price) VALUES (8, 'Charger', 24.50);
INSERT INTO products (id, name, price) VALUES (9, 'Tablet', 349.00);
INSERT INTO products (id, name, price) VALUES (10, 'Webcam', 59.95);
INSERT INTO products (id, name, price) VALUES (11, 'Speaker', 89.99);
INSERT INTO products (id, name, price) VALUES (12, 'External Hard Drive', 129.90);
INSERT INTO products (id, name, price) VALUES (13, 'Mouse Pad', 5.99);
INSERT INTO products (id, name, price) VALUES (14, 'Printer', 149.50);
INSERT INTO products (id, name, price) VALUES (15, 'Router', 79.00);
INSERT INTO products (id, name, price) VALUES (16, 'Smart Watch', 199.95);
INSERT INTO products (id, name, price) VALUES (17, 'Backpack', 39.99);
INSERT INTO products (id, name, price) VALUES (18, 'Desk Lamp', 34.75);
INSERT INTO products (id, name, price) VALUES (19, 'Gaming Chair', 249.99);
INSERT INTO products (id, name, price) VALUES (20, 'SSD Drive', 89.50);
```
![image.png](https://r2.hecodex.me/obsidian/20250313225438911.png)

### weather
**weather.py**
```python
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("weather")

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"


async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get('event', 'Unknown')}
Area: {props.get('areaDesc', 'Unknown')}
Severity: {props.get('severity', 'Unknown')}
Description: {props.get('description', 'No description available')}
Instructions: {props.get('instruction', 'No specific instructions provided')}
"""


@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period['name']}:
Temperature: {period['temperature']}°{period['temperatureUnit']}
Wind: {period['windSpeed']} {period['windDirection']}
Forecast: {period['detailedForecast']}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')%
```

# Cursor Setting
## Add MCP Server
![image.png](https://r2.hecodex.me/obsidian/20250313224616870.png)
### Server1
Type：`commmand`
**Command**：`uvx mcp-server-sqlite --db-path /Users/hening/hening/study/AICG/mcp/test.db`

### Server2
Type:`command`
**Command**:`uv run /Users/hening/hening/study/AICG/mcp/servers/src/weather/weather.py`

## MCP Servers
![image.png](https://r2.hecodex.me/obsidian/20250313224511846.png)

# Test MCP Servers
Question:`请帮我分析产品表有多少数据？`
![image.png](https://r2.hecodex.me/obsidian/20250313225637174.png)

![image.png](https://r2.hecodex.me/obsidian/20250313225715559.png)
