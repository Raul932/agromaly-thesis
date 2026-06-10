"""
LSTM Autoencoder — NDVI-Only Training Script
=============================================
Trains the production LSTM Autoencoder exclusively on Sentinel-2 NDVI
time-series (input_size=1, no weather features).

Motivation (from feature ablation experiment in lstm_anomaly_detection.ipynb):
    - NDVI-only AUC:      0.708
    - NDVI + Weather AUC: 0.619  (−8.8 pp degradation)
    Adding weather data introduces irrelevant variance that confuses the
    autoencoder and increases false positives.

Threshold strategy:
    99th percentile of reconstruction MSE on normal training windows,
    OR mean + 3×std — whichever is stricter. This replaces the 95th-
    percentile threshold used in the original model that caused 276 false
    positives (Precision=53%, Recall=95%).

Outputs (overwrite backend/data/models/):
    - lstm_autoencoder.pt   model weights
    - scaler_params.json    MinMax scaler (NDVI only)
    - model_config.json     hyperparameters + threshold

Run with the agromaly conda env:
    conda run -n agromaly python notebooks/train_ndvi_only.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

# ---------------------------------------------------------------------------
# Path setup — import model classes from the backend package
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ml.lstm_autoencoder import FeatureScaler, LSTMAutoencoder

# ---------------------------------------------------------------------------
# Hyperparameters
# ---------------------------------------------------------------------------
WINDOW_SIZE = 30    # NDVI observations per window (~150 days at 5-day revisit)
INPUT_SIZE  = 1     # NDVI only
HIDDEN_SIZE = 64
NUM_LAYERS  = 2
LATENT_DIM  = 16
DROPOUT     = 0.1
BATCH_SIZE  = 32
LR          = 1e-3
EPOCHS      = 200
PATIENCE    = 20    # Early stopping
SEED        = 42

DATA_PATH  = BACKEND_DIR / "data" / "training" / "ndvi_gpx_real.parquet"
MODEL_DIR  = BACKEND_DIR / "data" / "models"

torch.manual_seed(SEED)
np.random.seed(SEED)

print("=" * 65)
print("  LSTM Autoencoder — NDVI-Only Training")
print("=" * 65)
print(f"  Data:        {DATA_PATH}")
print(f"  Model dir:   {MODEL_DIR}")
print(f"  Window size: {WINDOW_SIZE}")
print(f"  Input size:  {INPUT_SIZE} (NDVI only)")
print()

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
df = pd.read_parquet(DATA_PATH)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["parcel_id", "date"]).reset_index(drop=True)

parcels = sorted(df["parcel_id"].unique())
print(f"[Data] {len(df)} records across {len(parcels)} parcels")
print(f"[Data] Date range: {df['date'].min().date()} to {df['date'].max().date()}")
print(f"[Data] Records per parcel: {df.groupby('parcel_id').size().mean():.1f} (mean)")

# ---------------------------------------------------------------------------
# 2. Anomaly labeling (used only for evaluation — NOT used during training)
#    Strategy: compare each NDVI to a per-parcel rolling baseline and a
#    month-level seasonal expectation (Romania mixed-crop phenology).
# ---------------------------------------------------------------------------
SEASONAL_NDVI = {
    1: 0.27, 2: 0.31, 3: 0.48, 4: 0.64, 5: 0.71, 6: 0.74,
    7: 0.67, 8: 0.54, 9: 0.44, 10: 0.38, 11: 0.32, 12: 0.26,
}
SEASONAL_STD = 0.14   # conservative ±1σ for Romanian crop NDVI


def compute_anomaly_flags(subdf: pd.DataFrame) -> np.ndarray:
    """
    Label records where NDVI deviates unexpectedly from:
      (a) the parcel's own 10-step rolling mean (z < -2.5), OR
      (b) the month-level seasonal expectation (z < -2.5).
    Returns a boolean array aligned to subdf.
    """
    ndvi   = subdf["ndvi_mean"].values.astype(float)
    months = subdf["date"].dt.month.values

    s = pd.Series(ndvi)
    roll_mean = s.rolling(10, min_periods=3, center=True).mean().to_numpy()
    roll_std  = (s.rolling(10, min_periods=3, center=True).std()
                  .fillna(0.05).clip(lower=0.02).to_numpy())

    seasonal_expected = np.array([SEASONAL_NDVI[m] for m in months], dtype=float)

    z_rolling  = (ndvi - roll_mean) / roll_std
    z_seasonal = (ndvi - seasonal_expected) / SEASONAL_STD

    return (z_rolling < -2.5) | (z_seasonal < -2.5)


# Apply per parcel without losing the parcel_id column
flags = np.zeros(len(df), dtype=bool)
for pid, idx in df.groupby("parcel_id").groups.items():
    flags[idx] = compute_anomaly_flags(df.loc[idx])
df["is_anomaly"] = flags
anomaly_rate = df["is_anomaly"].mean()
print(f"\n[Labels] Anomaly rate: {anomaly_rate:.1%}  "
      f"({df['is_anomaly'].sum()} / {len(df)} records)")

# ---------------------------------------------------------------------------
# 3. Parcel-level train / val / test split  (14 / 3 / 3)
# ---------------------------------------------------------------------------
rng = np.random.default_rng(SEED)
shuffled = rng.permutation(parcels)
N_TRAIN, N_VAL, N_TEST = 14, 3, 3

train_parcels = set(shuffled[:N_TRAIN])
val_parcels   = set(shuffled[N_TRAIN:N_TRAIN + N_VAL])
test_parcels  = set(shuffled[N_TRAIN + N_VAL:])

print(f"\n[Split] Train ({N_TRAIN}): {sorted(train_parcels)}")
print(f"[Split] Val   ({N_VAL}):   {sorted(val_parcels)}")
print(f"[Split] Test  ({N_TEST}):  {sorted(test_parcels)}")

# ---------------------------------------------------------------------------
# 4. Sliding-window construction
# ---------------------------------------------------------------------------

def build_windows(
    df_subset: pd.DataFrame,
    window_size: int = WINDOW_SIZE,
) -> tuple[np.ndarray, np.ndarray]:
    """
    For each parcel in df_subset, create overlapping windows of length
    window_size from the NDVI time series.

    Returns:
        X: (N, window_size)  float32  NDVI windows
        y: (N,)              int32    1 if any step in window is anomalous
    """
    windows, labels = [], []
    for _pid, group in df_subset.groupby("parcel_id"):
        group = group.sort_values("date")
        ndvi    = group["ndvi_mean"].values.astype(np.float32)
        anomaly = group["is_anomaly"].values

        if len(ndvi) < window_size:
            continue

        for i in range(len(ndvi) - window_size + 1):
            windows.append(ndvi[i : i + window_size])
            # A window is anomalous when its LAST observation is anomalous.
            # This makes the label meaningful: "does the sequence end in anomaly?"
            labels.append(int(anomaly[i + window_size - 1]))

    return (
        np.array(windows, dtype=np.float32),
        np.array(labels,  dtype=np.int32),
    )


X_train, y_train = build_windows(df[df["parcel_id"].isin(train_parcels)])
X_val,   y_val   = build_windows(df[df["parcel_id"].isin(val_parcels)])
X_test,  y_test  = build_windows(df[df["parcel_id"].isin(test_parcels)])

print(f"\n[Windows] Train: {X_train.shape}  anomaly={y_train.mean():.1%}")
print(f"[Windows] Val:   {X_val.shape}   anomaly={y_val.mean():.1%}")
print(f"[Windows] Test:  {X_test.shape}   anomaly={y_test.mean():.1%}")

# ---------------------------------------------------------------------------
# 5. MinMax normalisation  (fit on TRAIN normal windows only)
# ---------------------------------------------------------------------------
train_normal_mask = y_train == 0
ndvi_min = float(X_train[train_normal_mask].min())
ndvi_max = float(X_train[train_normal_mask].max())
print(f"\n[Scaler] NDVI range (train normal): [{ndvi_min:.4f}, {ndvi_max:.4f}]")


def normalize(X: np.ndarray) -> np.ndarray:
    return (X - ndvi_min) / max(ndvi_max - ndvi_min, 1e-6)


X_train_n = normalize(X_train)
X_val_n   = normalize(X_val)
X_test_n  = normalize(X_test)

# ---------------------------------------------------------------------------
# 6. Tensors  — shape (N, window_size, 1)
# ---------------------------------------------------------------------------

def to_tensor(X: np.ndarray) -> torch.Tensor:
    return torch.FloatTensor(X).unsqueeze(-1)   # (N, W) → (N, W, 1)


T_train_all    = to_tensor(X_train_n)
T_train_normal = T_train_all[train_normal_mask]  # Train ONLY on normal windows
T_val          = to_tensor(X_val_n)
T_test         = to_tensor(X_test_n)

print(f"\n[Dataset] Training on {len(T_train_normal)} normal windows "
      f"(excluded {(~train_normal_mask).sum()} anomaly windows)")

train_loader = DataLoader(
    TensorDataset(T_train_normal), batch_size=BATCH_SIZE, shuffle=True,
)
val_loader = DataLoader(
    TensorDataset(T_val), batch_size=BATCH_SIZE, shuffle=False,
)

# ---------------------------------------------------------------------------
# 7. Model instantiation
# ---------------------------------------------------------------------------
model = LSTMAutoencoder(
    input_size=INPUT_SIZE,
    hidden_size=HIDDEN_SIZE,
    num_layers=NUM_LAYERS,
    latent_dim=LATENT_DIM,
    window_size=WINDOW_SIZE,
    dropout=DROPOUT,
)
n_params = sum(p.numel() for p in model.parameters())
print(f"\n[Model] LSTMAutoencoder — {n_params:,} parameters")
print(f"        input_size={INPUT_SIZE}, hidden={HIDDEN_SIZE}, "
      f"layers={NUM_LAYERS}, latent={LATENT_DIM}, window={WINDOW_SIZE}")

optimizer = torch.optim.Adam(model.parameters(), lr=LR)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
    optimizer, patience=8, factor=0.5,
)
criterion = nn.MSELoss()

# ---------------------------------------------------------------------------
# 8. Training loop
# ---------------------------------------------------------------------------
print(f"\n[Train] Starting — max {EPOCHS} epochs, early-stop patience={PATIENCE}")
print("-" * 55)

best_val_loss     = float("inf")
best_state        = None
patience_counter  = 0
train_loss_hist: list[float] = []
val_loss_hist:   list[float] = []

for epoch in range(1, EPOCHS + 1):
    # --- Train ---
    model.train()
    batch_losses: list[float] = []
    for (batch,) in train_loader:
        optimizer.zero_grad()
        recon = model(batch)
        loss  = criterion(recon, batch)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        batch_losses.append(loss.item())

    train_loss = float(np.mean(batch_losses))
    train_loss_hist.append(train_loss)

    # --- Validate ---
    model.eval()
    val_losses: list[float] = []
    with torch.no_grad():
        for (batch,) in val_loader:
            recon = model(batch)
            val_losses.append(criterion(recon, batch).item())

    val_loss = float(np.mean(val_losses))
    val_loss_hist.append(val_loss)
    scheduler.step(val_loss)

    # --- Early stopping ---
    if val_loss < best_val_loss:
        best_val_loss    = val_loss
        best_state       = {k: v.clone() for k, v in model.state_dict().items()}
        patience_counter = 0
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"  Early stop at epoch {epoch}  "
                  f"(no improvement for {PATIENCE} epochs)")
            break

    if epoch % 20 == 0 or epoch == 1:
        print(f"  Epoch {epoch:3d}/{EPOCHS} | "
              f"train={train_loss:.6f} | val={val_loss:.6f} | "
              f"best={best_val_loss:.6f}")

print("-" * 55)
print(f"[Train] Best val loss: {best_val_loss:.8f}")

# Restore best weights
model.load_state_dict(best_state)
model.eval()

# ---------------------------------------------------------------------------
# 9. Anomaly threshold  — 99th percentile OR mean+3σ on NORMAL train windows
# ---------------------------------------------------------------------------
with torch.no_grad():
    recon_normal = model(T_train_normal)
    mse_normal   = ((T_train_normal - recon_normal) ** 2).mean(dim=(1, 2)).numpy()

threshold_p99       = float(np.percentile(mse_normal, 99))
threshold_mean3std  = float(mse_normal.mean() + 3.0 * mse_normal.std())
threshold           = max(threshold_p99, threshold_mean3std)

print(f"\n[Threshold] Normal-window MSE distribution:")
print(f"  mean:           {mse_normal.mean():.8f}")
print(f"  std:            {mse_normal.std():.8f}")
print(f"  95th pct:       {np.percentile(mse_normal, 95):.8f}")
print(f"  99th pct:       {threshold_p99:.8f}")
print(f"  mean + 3×std:   {threshold_mean3std:.8f}")
print(f"  SELECTED:       {threshold:.8f}  (stricter of p99 / mean+3*std)")

# ---------------------------------------------------------------------------
# 10. Evaluation on test set
# ---------------------------------------------------------------------------
with torch.no_grad():
    recon_test = model(T_test)
    mse_test   = ((T_test - recon_test) ** 2).mean(dim=(1, 2)).numpy()

y_pred = (mse_test > threshold).astype(int)

tp = int(((y_pred == 1) & (y_test == 1)).sum())
fp = int(((y_pred == 1) & (y_test == 0)).sum())
fn = int(((y_pred == 0) & (y_test == 1)).sum())
tn = int(((y_pred == 0) & (y_test == 0)).sum())

precision = tp / max(tp + fp, 1)
recall    = tp / max(tp + fn, 1)
f1        = 2 * precision * recall / max(precision + recall, 1e-9)

auc = 0.0
if len(np.unique(y_test)) > 1:
    auc = float(roc_auc_score(y_test, mse_test))

print(f"\n[Eval] Test set — {len(y_test)} windows")
print(f"  Confusion:  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
print(f"  Precision:  {precision:.3f}   (was 0.530 with old model)")
print(f"  Recall:     {recall:.3f}   (was 0.950 with old model)")
print(f"  F1:         {f1:.4f}")
print(f"  ROC AUC:    {auc:.4f}   (was 0.619 with weather features)")

# ---------------------------------------------------------------------------
# 11. Save artifacts
# ---------------------------------------------------------------------------
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 11a. Model weights
model_path = MODEL_DIR / "lstm_autoencoder.pt"
torch.save(model.state_dict(), model_path)

# 11b. Scaler (NDVI only — one feature)
scaler = FeatureScaler(
    feature_names=["ndvi_mean"],
    min_vals=np.array([ndvi_min], dtype=np.float32),
    max_vals=np.array([ndvi_max], dtype=np.float32),
)
scaler_path = MODEL_DIR / "scaler_params.json"
scaler.to_json(str(scaler_path))

# 11c. Config
config = {
    "input_size":             INPUT_SIZE,
    "hidden_size":            HIDDEN_SIZE,
    "num_layers":             NUM_LAYERS,
    "latent_dim":             LATENT_DIM,
    "window_size":            WINDOW_SIZE,
    "dropout":                0.0,
    "anomaly_threshold":      threshold,
    "threshold_strategy":     "max(p99, mean+3std) on normal training windows",
    "feature_names":          ["ndvi_mean"],
    "training_date":          datetime.now().isoformat(),
    "training_parcels":       len(parcels),
    "parcel_split":           {"train": N_TRAIN, "val": N_VAL, "test": N_TEST},
    "data_source":            "real_apia_gpx",
    "roc_auc":                round(auc, 6),
    "best_f1":                round(f1, 6),
    "precision":              round(precision, 4),
    "recall":                 round(recall, 4),
    "false_positives":        fp,
    "best_val_loss":          round(best_val_loss, 10),
    "mse_normal_p99":         round(threshold_p99, 10),
    "mse_normal_mean3std":    round(threshold_mean3std, 10),
    "epochs_trained":         len(train_loss_hist),
}

config_path = MODEL_DIR / "model_config.json"
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

model_kb = model_path.stat().st_size // 1024
print(f"\n[Save] Artifacts written to {MODEL_DIR}")
print(f"  lstm_autoencoder.pt  ({model_kb} KB)")
print(f"  scaler_params.json")
print(f"  model_config.json")
print("\n[Done]")
