import requests
from src.config import config
from src.logger import logger

def query_ollama(messages, model=None, temperature=0.2):
    """
    Sends a list of messages to the local Ollama API via OpenAI-compatible endpoint.
    messages: list of dicts with 'role' and 'content' keys
    model: string model name, overrides config model if provided
    """
    active_model = model or config.model
    headers = {
        "Content-Type": "application/json"
    }
    
    # We can inject API key if provided, though Ollama doesn't require it by default
    if config.api_key and config.api_key != "ollama":
        headers["Authorization"] = f"Bearer {config.api_key}"
        
    payload = {
        "model": active_model,
        "messages": messages,
        "temperature": temperature
    }
    
    logger.info("System", f"Sending request to Ollama endpoint: {config.api_url} (Model: {active_model})")
    
    try:
        response = requests.post(
            config.api_url,
            json=payload,
            headers=headers,
            timeout=120 # Give enough time for larger models / slow hardware to generate responses
        )
        
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                return content.strip()
            else:
                logger.error("System", f"Unexpected response format from Ollama: {data}")
                return "Error: Unexpected response format from Ollama."
        else:
            logger.error("System", f"Ollama HTTP error {response.status_code}: {response.text}")
            return f"Error: Ollama returned status code {response.status_code}."
            
    except requests.exceptions.Timeout:
        logger.error("System", "Ollama request timed out.")
        return "Error: Request to Ollama timed out. The local model is taking too long to respond."
    except requests.exceptions.ConnectionError:
        logger.error("System", f"Failed to connect to Ollama at {config.api_url}")
        return "Error: Could not connect to Ollama. Please ensure Ollama is running ('ollama serve') and accessible."
    except Exception as e:
        logger.error("System", f"Unhandled exception querying Ollama: {str(e)}")
        return f"Error: Failed to query local model: {str(e)}"

def unload_model(model_name=None):
    """
    Tells Ollama to unload the model from memory immediately.
    """
    import urllib.parse
    active_model = model_name or config.model
    try:
        parsed = urllib.parse.urlparse(config.api_url)
        unload_url = f"{parsed.scheme}://{parsed.netloc}/api/generate"
        payload = {
            "model": active_model,
            "keep_alive": 0
        }
        response = requests.post(unload_url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.info("System", f"Successfully unloaded model '{active_model}' from memory.")
            return True
    except Exception as e:
        logger.warning("System", f"Could not unload model '{active_model}': {e}")
    return False
