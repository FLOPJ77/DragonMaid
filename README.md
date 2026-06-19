# DragonMaid

This is DragonMaid version 1, a secure, lightweight personal AI assistant. It provides low-overhead task automation, scheduling, local memory consolidation, and terminal action handling.

Designed for small LLMs, DragonMaid aims to be fast and safe without the resource strain of heavy multi-agent frameworks.



## Installation
### Linux

Create directory and move inside it
```
mkdir dragonmaid
```

Copy and paste the python code
```
# copy and paste the full code
vi dragonmaid.py
```

Update & install venv
```
sudo apt update
sudo apt install python3-venv
```

Setup virtual environment
```
python3 -m venv myenv
```

Activate it
```
source myenv/bin/activate
```

Install the only external library
```
pip install requests
```

Make .env file
```
vi .env
```
Paste this
```
API_KEY=ollama
API_URL=http://localhost:11434/v1/chat/completions
MODEL=granite4.1:8b
TELEGRAM_BOT_TOKEN=1234567890102345678901234567889012345678901234
ALLOWED_USER_ID=1234567890 
ALLOW_HOST_EXECUTION=false
BYPASS_HOST_GATEKEEPER=true

```

Start it
```
python dragonmaid.py
```




## Commands
/help
/model
/model set <modelname>
/status
/history <num>
/dream
