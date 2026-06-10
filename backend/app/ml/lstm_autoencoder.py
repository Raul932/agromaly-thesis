"""
LSTM Autoencoder for Agricultural Anomaly Detection
=====================================================
PyTorch model definition and inference wrapper for the Agromaly thesis.

Architecture (Thesis Chapter 4):
    The LSTM Autoencoder learns to reconstruct "normal" NDVI time-series
    patterns. At inference time, sequences that cannot be accurately
    reconstructed (high MSE) are classified as anomalous.

    Feature ablation showed that weather data degraded AUC by ~8.8%,
    so the production model is trained exclusively on Sentinel-2 NDVI
    (input_size=1). The architecture supports any number of features.

    Encoder:
        LSTM(input_size=N_FEATURES, hidden_size=H, num_layers=L)
        → take last hidden state
        → Linear(H, latent_dim)

    Decoder:
        RepeatVector(window_size)
        LSTM(input_size=latent_dim, hidden_size=H, num_layers=L)
        → Linear(H, N_FEATURES)  # reconstruct all features per timestep

    Loss:  MSE (Mean Squared Error) on reconstruction
    Input: (batch, window_size, n_features)
    Output: (batch, window_size, n_features)  — reconstructed sequence

Model Files (all required for inference):
    - ``lstm_autoencoder.pt``  — trained model state_dict
    - ``scaler_params.json``   — MinMaxScaler min/max per feature
    - ``model_config.json``    — architecture hyperparameters

Usage::

    from app.ml.lstm_autoencoder import AnomalyDetector

    detector = AnomalyDetector.load("data/models")
    score, is_anomaly = detector.predict(ndvi_series, weather_matrix)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Default feature set (must match training notebook)
DEFAULT_FEATURES = ["ndvi", "temp_max", "temp_min", "humidity", "precipitation"]
N_FEATURES = len(DEFAULT_FEATURES)


# ===========================================================================
# Model Architecture
# ===========================================================================

class Encoder(nn.Module):
    """LSTM Encoder: compresses a time-series window into a latent vector.

    Args:
        input_size:  Number of input features per timestep.
        hidden_size: LSTM hidden state dimensionality.
        num_layers:  Number of stacked LSTM layers.
        latent_dim:  Dimensionality of the compressed latent representation.
        dropout:     Dropout between LSTM layers (only if num_layers > 1).
    """

    def __init__(
        self,
        input_size: int = N_FEATURES,
        hidden_size: int = 64,
        num_layers: int = 2,
        latent_dim: int = 16,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc_latent = nn.Linear(hidden_size, latent_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Encode input sequence to latent representation.

        Args:
            x: (batch, window_size, input_size)

        Returns:
            Latent vector: (batch, latent_dim)
        """
        # LSTM output: (batch, seq_len, hidden_size)
        _, (hidden, _) = self.lstm(x)
        # Take the last layer's hidden state: (batch, hidden_size)
        last_hidden = hidden[-1]
        # Project to latent space
        latent = self.fc_latent(last_hidden)
        return latent


class Decoder(nn.Module):
    """LSTM Decoder: reconstructs a time-series window from a latent vector.

    Args:
        latent_dim:  Input dimensionality (from encoder).
        hidden_size: LSTM hidden state dimensionality.
        num_layers:  Number of stacked LSTM layers.
        output_size: Number of output features per timestep.
        window_size: Length of the output sequence.
        dropout:     Dropout between LSTM layers.
    """

    def __init__(
        self,
        latent_dim: int = 16,
        hidden_size: int = 64,
        num_layers: int = 2,
        output_size: int = N_FEATURES,
        window_size: int = 30,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.window_size = window_size
        self.latent_dim = latent_dim
        self.lstm = nn.LSTM(
            input_size=latent_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc_out = nn.Linear(hidden_size, output_size)

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        """Decode latent vector back to a time-series sequence.

        Args:
            latent: (batch, latent_dim)

        Returns:
            Reconstructed sequence: (batch, window_size, output_size)
        """
        # Repeat latent vector across the time dimension
        # (batch, latent_dim) → (batch, window_size, latent_dim)
        repeated = latent.unsqueeze(1).repeat(1, self.window_size, 1)
        # LSTM decode
        lstm_out, _ = self.lstm(repeated)
        # Project each timestep to output features
        reconstruction = self.fc_out(lstm_out)
        return reconstruction


class LSTMAutoencoder(nn.Module):
    """Complete LSTM Autoencoder for multivariate time-series anomaly detection.

    Combines Encoder + Decoder into a single end-to-end model.
    The reconstruction error (MSE) of a sequence is the anomaly score.

    Args:
        input_size:  Number of features per timestep.
        hidden_size: LSTM hidden state size.
        num_layers:  Number of stacked LSTM layers.
        latent_dim:  Bottleneck dimensionality.
        window_size: Length of input/output sequences.
        dropout:     LSTM dropout rate.
    """

    def __init__(
        self,
        input_size: int = N_FEATURES,
        hidden_size: int = 64,
        num_layers: int = 2,
        latent_dim: int = 16,
        window_size: int = 30,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.latent_dim = latent_dim
        self.window_size = window_size

        self.encoder = Encoder(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            latent_dim=latent_dim,
            dropout=dropout,
        )
        self.decoder = Decoder(
            latent_dim=latent_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            output_size=input_size,
            window_size=window_size,
            dropout=dropout,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass: encode then decode.

        Args:
            x: (batch, window_size, input_size)

        Returns:
            Reconstruction: (batch, window_size, input_size)
        """
        latent = self.encoder(x)
        reconstruction = self.decoder(latent)
        return reconstruction

    def compute_reconstruction_error(self, x: torch.Tensor) -> torch.Tensor:
        """Compute per-sample MSE reconstruction error.

        Args:
            x: (batch, window_size, input_size)

        Returns:
            MSE per sample: (batch,)
        """
        with torch.no_grad():
            reconstruction = self.forward(x)
            # MSE per sample: mean over (window_size × input_size)
            mse = torch.mean((x - reconstruction) ** 2, dim=(1, 2))
        return mse


# ===========================================================================
# Scaler (matches sklearn MinMaxScaler but pure NumPy for portability)
# ===========================================================================

@dataclass
class FeatureScaler:
    """MinMaxScaler that normalizes features to [0, 1].

    Serializable to/from JSON for portability across notebook → backend.
    """

    feature_names: List[str]
    min_vals: np.ndarray   # shape: (n_features,)
    max_vals: np.ndarray   # shape: (n_features,)

    def transform(self, data: np.ndarray) -> np.ndarray:
        """Scale data to [0, 1].

        Args:
            data: (n_samples, n_features) or (seq_len, n_features)

        Returns:
            Scaled array, same shape.
        """
        range_vals = self.max_vals - self.min_vals
        # Avoid division by zero for constant features
        range_vals = np.where(range_vals == 0, 1.0, range_vals)
        return (data - self.min_vals) / range_vals

    def inverse_transform(self, data: np.ndarray) -> np.ndarray:
        """Reverse the scaling."""
        range_vals = self.max_vals - self.min_vals
        range_vals = np.where(range_vals == 0, 1.0, range_vals)
        return data * range_vals + self.min_vals

    def to_json(self, path: str) -> None:
        """Save scaler parameters to a JSON file."""
        payload = {
            "feature_names": self.feature_names,
            "min_vals": self.min_vals.tolist(),
            "max_vals": self.max_vals.tolist(),
        }
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info("Scaler saved to %s", path)

    @classmethod
    def from_json(cls, path: str) -> "FeatureScaler":
        """Load scaler parameters from a JSON file."""
        with open(path, "r") as f:
            payload = json.load(f)
        return cls(
            feature_names=payload["feature_names"],
            min_vals=np.array(payload["min_vals"], dtype=np.float32),
            max_vals=np.array(payload["max_vals"], dtype=np.float32),
        )


# ===========================================================================
# Inference Wrapper (used by the FastAPI backend)
# ===========================================================================

class AnomalyDetector:
    """High-level inference wrapper that loads a trained LSTM Autoencoder
    and exposes a simple ``predict()`` API.

    This is the class used by ``AnalysisService`` in the backend.

    Usage::

        detector = AnomalyDetector.load("/app/data/models")
        score, is_anomaly = detector.predict(ndvi_values, weather_matrix)
    """

    def __init__(
        self,
        model: LSTMAutoencoder,
        scaler: FeatureScaler,
        threshold: float,
        config: dict,
    ) -> None:
        self.model = model
        self.scaler = scaler
        self.threshold = threshold
        self.config = config
        self.model.eval()  # Set to evaluation mode

    @classmethod
    def load(cls, model_dir: str) -> "AnomalyDetector":
        """Load a trained model from disk.

        Expected files in ``model_dir``:
            - lstm_autoencoder.pt   — model state dict
            - scaler_params.json    — scaler min/max values
            - model_config.json     — hyperparameters + threshold

        Args:
            model_dir: Path to the directory containing model files.

        Returns:
            Ready-to-use AnomalyDetector instance.

        Raises:
            FileNotFoundError: If any required file is missing.
        """
        model_dir = Path(model_dir)
        model_path = model_dir / "lstm_autoencoder.pt"
        scaler_path = model_dir / "scaler_params.json"
        config_path = model_dir / "model_config.json"

        # Check all files exist
        for path in [model_path, scaler_path, config_path]:
            if not path.exists():
                raise FileNotFoundError(
                    f"Required model file not found: {path}. "
                    "Run the training notebook first."
                )

        # Load config
        with open(config_path, "r") as f:
            config = json.load(f)

        # Build model with saved hyperparameters
        model = LSTMAutoencoder(
            input_size=config.get("input_size", N_FEATURES),
            hidden_size=config.get("hidden_size", 64),
            num_layers=config.get("num_layers", 2),
            latent_dim=config.get("latent_dim", 16),
            window_size=config.get("window_size", 30),
            dropout=config.get("dropout", 0.0),  # No dropout at inference
        )

        # Load weights
        device = torch.device("cpu")  # Inference on CPU (no GPU needed)
        state_dict = torch.load(model_path, map_location=device, weights_only=True)
        model.load_state_dict(state_dict)
        model.eval()

        # Load scaler
        scaler = FeatureScaler.from_json(str(scaler_path))

        # Threshold from ROC analysis (set during training)
        threshold = config.get("anomaly_threshold", 0.01)

        logger.info(
            "LSTM Autoencoder loaded: %s (hidden=%d, latent=%d, window=%d, threshold=%.6f)",
            model_path, config.get("hidden_size", 64),
            config.get("latent_dim", 16),
            config.get("window_size", 30),
            threshold,
        )

        return cls(model=model, scaler=scaler, threshold=threshold, config=config)

    def predict(
        self,
        ndvi_values: List[float],
        weather_matrix: Optional[np.ndarray] = None,
    ) -> Tuple[float, bool, np.ndarray]:
        """Run anomaly detection on an NDVI time series.

        Args:
            ndvi_values:    List of NDVI values (length >= window_size).
                            If longer, only the last ``window_size`` values are used.
            weather_matrix: Ignored when the model has input_size=1 (NDVI-only).
                            For legacy multi-feature models, pass aligned weather data.

        Returns:
            Tuple of:
                - anomaly_score (float): MSE reconstruction error
                - is_anomaly (bool): True if score > threshold
                - per_feature_error (np.ndarray): MSE per feature for interpretability
        """
        window_size = self.config.get("window_size", 30)
        n_features = self.config.get("input_size", N_FEATURES)

        # Validate input length
        if len(ndvi_values) < window_size:
            logger.warning(
                "Input too short (%d < %d) — padding with mean",
                len(ndvi_values), window_size,
            )
            mean_val = np.mean(ndvi_values) if ndvi_values else 0.5
            ndvi_values = [mean_val] * (window_size - len(ndvi_values)) + list(ndvi_values)

        # Take last window_size values
        ndvi_arr = np.array(ndvi_values[-window_size:], dtype=np.float32)

        # Build feature matrix
        if n_features == 1:
            # NDVI-only model (production): shape (window_size, 1)
            features = ndvi_arr.reshape(window_size, 1)
        elif weather_matrix is not None and weather_matrix.shape[0] >= window_size:
            # Legacy multi-feature model with real weather data
            weather_slice = weather_matrix[-window_size:]
            n_weather = n_features - 1
            if weather_slice.shape[1] >= n_weather:
                weather_slice = weather_slice[:, :n_weather]
            else:
                pad = np.zeros((window_size, n_weather - weather_slice.shape[1]), dtype=np.float32)
                weather_slice = np.concatenate([weather_slice, pad], axis=1)
            features = np.column_stack([ndvi_arr, weather_slice])
        else:
            # Legacy multi-feature model in NDVI-only fallback: pad weather with 0.5
            weather_pad = np.full((window_size, n_features - 1), 0.5, dtype=np.float32)
            features = np.column_stack([ndvi_arr, weather_pad])

        # Normalize with the trained scaler
        features_scaled = self.scaler.transform(features)

        # Convert to PyTorch tensor: (1, window_size, n_features)
        tensor = torch.FloatTensor(features_scaled).unsqueeze(0)

        # Forward pass
        with torch.no_grad():
            reconstruction = self.model(tensor)
            error = (tensor - reconstruction) ** 2

            # Overall anomaly score: mean MSE across all features and timesteps
            anomaly_score = float(error.mean())

            # Per-feature error for interpretability
            per_feature_error = error.squeeze(0).mean(dim=0).numpy()  # (n_features,)

            is_anomaly = anomaly_score > self.threshold

        return anomaly_score, is_anomaly, per_feature_error

    @property
    def window_size(self) -> int:
        return self.config.get("window_size", 30)

    @property
    def feature_names(self) -> List[str]:
        return self.scaler.feature_names


# ===========================================================================
# Singleton loader (one model per process)
# ===========================================================================

_detector_instance: Optional[AnomalyDetector] = None


def get_anomaly_detector(model_dir: Optional[str] = None) -> Optional[AnomalyDetector]:
    """Get or lazily load the global AnomalyDetector singleton.

    The model directory is resolved in order:
      1. ``model_dir`` argument (if provided).
      2. ``settings.ML_MODEL_DIR`` config value.
      3. Fallback: ``/app/data/models`` (Docker default).

    Returns None if model files don't exist (graceful degradation to Z-score fallback).
    """
    global _detector_instance

    if _detector_instance is not None:
        return _detector_instance

    if model_dir is None:
        try:
            from app.core.config import settings
            model_dir = settings.ML_MODEL_DIR
        except Exception:
            model_dir = "/app/data/models"

    try:
        _detector_instance = AnomalyDetector.load(model_dir)
        return _detector_instance
    except FileNotFoundError as exc:
        logger.warning("LSTM model not found — will use Z-score fallback: %s", exc)
        return None
    except Exception as exc:
        logger.error("Failed to load LSTM model: %s", exc, exc_info=True)
        return None
