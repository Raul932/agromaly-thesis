/// One day in a parcel's weather forecast.
class ForecastDay {
  final String date;
  final String weekday;
  final double tempMax;
  final double tempMin;
  final double precipitationMm;
  final double windSpeedKmh;
  final int? weatherCode;

  const ForecastDay({
    required this.date,
    required this.weekday,
    required this.tempMax,
    required this.tempMin,
    required this.precipitationMm,
    required this.windSpeedKmh,
    this.weatherCode,
  });

  factory ForecastDay.fromJson(Map<String, dynamic> json) => ForecastDay(
        date: json['date'] as String? ?? '',
        weekday: json['weekday'] as String? ?? '',
        tempMax: (json['temp_max_c'] as num?)?.toDouble() ?? 0,
        tempMin: (json['temp_min_c'] as num?)?.toDouble() ?? 0,
        precipitationMm: (json['precipitation_mm'] as num?)?.toDouble() ?? 0,
        windSpeedKmh: (json['wind_speed_kmh'] as num?)?.toDouble() ?? 0,
        weatherCode: (json['weather_code'] as num?)?.toInt(),
      );

  /// Emoji for the WMO weather interpretation code.
  String get emoji {
    final c = weatherCode ?? 0;
    if (c == 0) return '☀️';
    if (c <= 2) return '🌤️';
    if (c == 3) return '☁️';
    if (c == 45 || c == 48) return '🌫️';
    if (c >= 51 && c <= 57) return '🌦️';
    if (c >= 61 && c <= 67) return '🌧️';
    if (c >= 71 && c <= 77) return '❄️';
    if (c >= 80 && c <= 82) return '🌧️';
    if (c >= 85 && c <= 86) return '🌨️';
    if (c >= 95) return '⛈️';
    return '🌤️';
  }
}

/// A parcel's 7-day forecast plus plain-language Romanian warnings.
class Forecast {
  final List<ForecastDay> days;
  final List<String> warnings;

  const Forecast({required this.days, required this.warnings});

  factory Forecast.fromJson(Map<String, dynamic> json) => Forecast(
        days: ((json['days'] as List<dynamic>?) ?? [])
            .map((e) => ForecastDay.fromJson(e as Map<String, dynamic>))
            .toList(),
        warnings: ((json['warnings'] as List<dynamic>?) ?? [])
            .map((e) => e as String)
            .toList(),
      );
}
