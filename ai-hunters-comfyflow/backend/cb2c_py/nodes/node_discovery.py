import os
import requests


# Default API address for a local ComfyUI instance
DEFAULT_COMFYUI_SERVER_ADDRESS = "localhost:8188"
COMFYUI_API_URL = "http://" + os.getenv(
    "COMFYUI_SERVER_ADDRESS", DEFAULT_COMFYUI_SERVER_ADDRESS
)


def fetch_node_definitions(api_url: str = COMFYUI_API_URL):
    """
    Fetches the complete list of node definitions from the ComfyUI API.

    This includes built-in nodes and any installed custom nodes.
    The data is returned as a dictionary from the API's JSON response.
    """
    print(f"Fetching node definitions from {api_url}...")
    try:
        response = requests.get(f"{api_url}/object_info")
        response.raise_for_status()  # Raise an exception for HTTP errors
        print("Successfully fetched node definitions.")
        return response.json()
    except requests.exceptions.RequestException:
        print(f"Error: Could not connect to the ComfyUI API at {api_url}.")
        print("Please ensure ComfyUI is running and the API is accessible.")
        return None


if __name__ == "__main__":
    # Example of how to use the fetcher
    definitions = fetch_node_definitions()
    if definitions:
        # Print the name of the first node found as a test
        first_node_name = next(iter(definitions))
        print(f"Successfully retrieved data. First node found: '{first_node_name}'")
        print(f"Total nodes found: {len(definitions)}")
