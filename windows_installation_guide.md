
### 💻 Windows installation

To install it on windows you need to use WSL (Windows Subsystem for Linux)

Open a new Powershell terminal and install WSL:
```bash
wsl --install
```
> [!NOTE]
> This install Ubuntu by default so
> do this to install Debian instead:
>
> ```bash
> wsl --install -d Debian
> ```

Open Debian and run:
```bash
sudo apt update
```

Install Curl:
```bash
sudo apt install curl -y
```

Install Zstd:
```bash
sudo apt-get install zstd
```

Install Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Install a Ollama LLM:
```bash
ollama pull granite4.1:3b
```

Install Git:
```bash
sudo apt install git -y
```

Clone the Repository and Navigate to the Directory:
```bash
git clone https://github.com/FLOPJ77/DragonMaid.git
cd DragonMaid
```

Install the Python Environment Setup:
```bash
sudo apt install python3 -y
sudo apt install python3.13-venv
```

Create a Virtual Environment:
```bash
python3 -m venv myenv
```

Activate the Virtual Environment:
```bash
source myenv/bin/activate
```

Run the Application:
```bash
./myenv/bin/python src/main.py
```



>[!NOTE]
>to deactivate virtual environment when done use the command:
>```bash
>deactivate
>```
>
>To stop WSL run this command in powershell:
>```bash
>wsl --shutdown
>```

