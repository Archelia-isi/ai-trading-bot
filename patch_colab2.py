import json

with open("titano_shock_therapy.ipynb", "r") as f:
    notebook = json.load(f)

# Rimuovi l'installazione vecchia e inseriamo drive mount all'inizio
# Cell 1: !pip install...
# Aggiungiamo Cell 2 nuova: drive mount
new_drive_cell = {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "from google.colab import drive\n",
    "drive.mount('/content/drive')\n",
    "print(\"Google Drive collegato con successo!\")"
   ]
}

# Inseriamo come seconda cella (index 2)
notebook["cells"].insert(2, new_drive_cell)

# Aggiorniamo l'ultima cella per non rimontare il drive e usare i percorsi giusti
last_cell = notebook["cells"][-1]
new_source_last = [
    "env = DummyVecEnv([lambda: AdvancedPortfolioEnv(data_frames)])\n",
    "\n",
    "# Percorsi Google Drive\n",
    "model_load_path = \"/content/drive/MyDrive/Titano_V6_Universale.zip\"\n",
    "model_save_path = \"/content/drive/MyDrive/Titano_V6_DayTrader.zip\"\n",
    "\n",
    "print(f\"Cerco il modello in: {model_load_path}\")\n",
    "if os.path.exists(model_load_path):\n",
    "    print(\"Caricamento modello esistente in corso...\")\n",
    "    custom_objects = {\"learning_rate\": 0.0003, \"lr_schedule\": lambda _: 0.0003, \"clip_range\": lambda _: 0.2}\n",
    "    model = PPO.load(model_load_path, env=env, custom_objects=custom_objects)\n",
    "else:\n",
    "    print(\"ATTENZIONE: File 'Titano_V6_Universale.zip' non trovato su Google Drive!\")\n",
    "    print(\"Partiremo da zero con una nuova rete neurale vuota.\")\n",
    "    model = PPO(\"MlpPolicy\", env, verbose=0)\n",
    "\n",
    "callback = LiveMetricsCallback(env)\n",
    "print(\"\\nInizio Shock Therapy da 100 Milioni di Step...\")\n",
    "model.learn(total_timesteps=100_000_000, callback=callback, reset_num_timesteps=False)\n",
    "print(\"Addestramento Completato!\")\n",
    "\n",
    "model.save(model_save_path)\n",
    "print(f\"Nuovo modello salvato AL SICURO su Google Drive: {model_save_path}\")\n"
]
last_cell["source"] = new_source_last

with open("titano_shock_therapy.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)

