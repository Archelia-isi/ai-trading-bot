import gymnasium as gym
from gymnasium import spaces
import torch
import torch.nn as nn
from stable_baselines3 import PPO
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
import numpy as np

# Copio la classe custom usata nell'addestramento
class MultiAssetFeatureExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, features_dim: int = 1024):
        super().__init__(observation_space, features_dim)
        n_input_channels = observation_space.shape[1]
        
        self.cnn = nn.Sequential(
            nn.Conv1d(n_input_channels, 128, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(128, 256, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(256, 512, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv1d(512, 1024, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        
        with torch.no_grad():
            dummy_input = torch.zeros(1, n_input_channels, observation_space.shape[0])
            n_flatten = self.cnn(dummy_input).shape[1]
            
        self.linear = nn.Sequential(
            nn.Linear(n_flatten, 1024),
            nn.ReLU(),
            nn.Linear(1024, features_dim),
            nn.ReLU()
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        observations = observations.permute(0, 2, 1) 
        x = self.cnn(observations)
        return self.linear(x)

if __name__ == "__main__":
    print("Loading model...")
    # Register the class in the local namespace for stable-baselines
    import __main__
    setattr(__main__, 'MultiAssetFeatureExtractor', MultiAssetFeatureExtractor)
    
    try:
        model = PPO.load("models/Titano_V4_OcchiAperti.zip", custom_objects={'MultiAssetFeatureExtractor': MultiAssetFeatureExtractor})
        print("Model loaded successfully!")
        
        # Test inference
        dummy_obs = np.zeros((30, 34), dtype=np.float32)
        action, _ = model.predict(dummy_obs, deterministic=True)
        print("Predicted actions:", action)
    except Exception as e:
        print("Error loading model:", e)
