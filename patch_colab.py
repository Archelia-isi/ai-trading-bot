import json

with open("titano_shock_therapy.ipynb", "r") as f:
    notebook = json.load(f)

# Modifichiamo l'ultima cella per aggiungere Google Drive
last_cell = notebook["cells"][-1]
new_source = [
    "from google.colab import drive\n",
    "drive.mount('/content/drive')\n",
    "\n",
    "env = DummyVecEnv([lambda: AdvancedPortfolioEnv(data_frames)])\n",
    "print(\"ATTENZIONE: Carica il file 'Titano_V6_Universale.zip' da Railway a Colab prima di avviare.\")\n",
    "model_path = \"Titano_V6_Universale.zip\"\n",
    "if os.path.exists(model_path):\n",
    "    print(\"Caricamento modello esistente in corso...\")\n",
    "    custom_objects = {\"learning_rate\": 0.0003, \"lr_schedule\": lambda _: 0.0003, \"clip_range\": lambda _: 0.2}\n",
    "    model = PPO.load(model_path, env=env, custom_objects=custom_objects)\n",
    "else:\n",
    "    print(\"Modello non trovato, partiamo da zero!\")\n",
    "    model = PPO(\"MlpPolicy\", env, verbose=0)\n",
    "callback = LiveMetricsCallback(env)\n",
    "print(\"Inizio Shock Therapy da 100 Milioni di Step...\")\n",
    "model.learn(total_timesteps=100_000_000, callback=callback, reset_num_timesteps=False)\n",
    "print(\"Addestramento Completato!\")\n",
    "\n",
    "# SALVATAGGIO SU GOOGLE DRIVE\n",
    "drive_save_path = \"/content/drive/MyDrive/Titano_V6_DayTrader.zip\"\n",
    "model.save(drive_save_path)\n",
    "print(f\"Nuovo modello salvato AL SICURO su Google Drive: {drive_save_path}\")\n"
]
last_cell["source"] = new_source

with open("titano_shock_therapy.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)

