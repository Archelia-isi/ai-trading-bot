import json

with open("titano_shock_therapy.ipynb", "r") as f:
    notebook = json.load(f)

# Modifichiamo l'import per aggiungere SubprocVecEnv
import_cell = notebook["cells"][2]
new_imports = [
    "import yfinance as yf\n",
    "import pandas as pd\n",
    "import numpy as np\n",
    "import gymnasium as gym\n",
    "from gymnasium import spaces\n",
    "from stable_baselines3 import PPO\n",
    "from stable_baselines3.common.callbacks import BaseCallback\n",
    "from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv\n", # Aggiunto Subproc
    "import time\n",
    "import os\n"
]
import_cell["source"] = new_imports


# Modifichiamo l'ultima cella per usare il parallelismo massiccio e batch size giganti
last_cell = notebook["cells"][-1]
new_source_last = [
    "# Configurazione per A100 GPU: Parallelismo Estremo\n",
    "NUM_ENVS = 16 # Lancia 16 copie dell'ambiente in parallelo per saturare la CPU\n",
    "\n",
    "def make_env():\n",
    "    return lambda: AdvancedPortfolioEnv(data_frames)\n",
    "\n",
    "env = SubprocVecEnv([make_env() for _ in range(NUM_ENVS)])\n",
    "\n",
    "# Percorsi Google Drive\n",
    "model_load_path = \"/content/drive/MyDrive/Titano_V6_Universale.zip\"\n",
    "model_save_path = \"/content/drive/MyDrive/Titano_V6_DayTrader.zip\"\n",
    "\n",
    "print(f\"Cerco il modello in: {model_load_path}\")\n",
    "if os.path.exists(model_load_path):\n",
    "    print(\"Caricamento modello esistente in corso...\")\n",
    "    # Aggiorniamo i parametri per sfruttare la A100: Batch giganti!\n",
    "    custom_objects = {\n",
    "        \"learning_rate\": 0.0003, \n",
    "        \"lr_schedule\": lambda _: 0.0003, \n",
    "        \"clip_range\": lambda _: 0.2,\n",
    "        \"n_steps\": 8192,           # Rollout lungo\n",
    "        \"batch_size\": 4096         # Sfruttiamo gli 80GB di VRAM della A100!\n",
    "    }\n",
    "    model = PPO.load(model_load_path, env=env, custom_objects=custom_objects)\n",
    "else:\n",
    "    print(\"ATTENZIONE: File 'Titano_V6_Universale.zip' non trovato su Google Drive!\")\n",
    "    print(\"Partiremo da zero con una nuova rete neurale vuota, ottimizzata per A100.\")\n",
    "    model = PPO(\"MlpPolicy\", env, n_steps=8192, batch_size=4096, verbose=0)\n",
    "\n",
    "callback = LiveMetricsCallback(env)\n",
    "print(\"\\nInizio Shock Therapy da 100 Milioni di Step (A100 Ottimizzata)...\")\n",
    "model.learn(total_timesteps=100_000_000, callback=callback, reset_num_timesteps=False)\n",
    "print(\"Addestramento Completato!\")\n",
    "\n",
    "model.save(model_save_path)\n",
    "print(f\"Nuovo modello salvato AL SICURO su Google Drive: {model_save_path}\")\n"
]
last_cell["source"] = new_source_last

with open("titano_shock_therapy.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)

