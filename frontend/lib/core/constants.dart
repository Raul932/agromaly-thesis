/// App-wide constants and configuration values.
library;

/// Base URL for the FastAPI backend.
/// Android emulator uses 10.0.2.2 to reach host's localhost.
/// For physical device testing, replace with your LAN IP (e.g., 192.168.1.x).
const String kBaseUrl = 'http://192.168.0.106:8000/api/v1';

/// SharedPreferences key for the JWT access token.
const String kTokenKey = 'access_token';

/// Anomaly threshold — matches backend's _ANOMALY_THRESHOLD = 0.55
const double kAnomalyThreshold = 0.55;

/// Crop types matching the backend's CropType enum.
const List<String> kCropTypes = [
  'wheat',
  'corn',
  'sunflower',
  'soybean',
  'rapeseed',
  'barley',
  'potato',
  'sugar_beet',
  'vineyard',
  'orchard',
  'other',
  'unknown',
];
