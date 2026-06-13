/// App-wide constants and configuration values.
library;

/// Base URL for the FastAPI backend.
/// Android emulator uses 10.0.2.2 to reach host's localhost.
/// For physical device testing, replace with your LAN IP (e.g., 192.168.1.x).
const String kBaseUrl = 'http://192.168.0.103:8000/api/v1';

/// Mapbox public access token — free tier (50k tile requests/month).
/// Get yours at mapbox.com → Account → Tokens.
/// Replace this with your own token before running the app.
const String kMapboxAccessToken =
    'YOUR_MAPBOX_PUBLIC_TOKEN';

/// Mapbox satellite tile URL template for flutter_map TileLayer.
const String kMapboxSatelliteUrl =
    'https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/256/{z}/{x}/{y}@2x?access_token=$kMapboxAccessToken';

/// SharedPreferences key for the JWT access token.
const String kTokenKey = 'access_token';

/// SharedPreferences key for the JWT refresh token.
const String kRefreshTokenKey = 'refresh_token';

/// Anomaly threshold — matches backend's _ANOMALY_THRESHOLD = 0.55
const double kAnomalyThreshold = 0.55;

/// Crop types matching the backend's CropType enum.
const List<String> kCropTypes = [
  'WHEAT',
  'CORN',
  'SUNFLOWER',
  'SOYBEAN',
  'RAPESEED',
  'BARLEY',
  'POTATO',
  'SUGAR_BEET',
  'VINEYARD',
  'ORCHARD',
  'MEADOW',
  'OTHER',
  'UNKNOWN',
];
