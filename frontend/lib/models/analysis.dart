/// Analysis model matching the backend's AnalysisResponse schema.
///
/// Returned by GET /api/v1/parcels/{id}/analysis
class Analysis {
  final String parcelId;
  final String parcelName;
  final String status; // "ANOMALY_DETECTED" | "HEALTHY" | "INSUFFICIENT_DATA"
  final double anomalyScore;
  final double mseScore;
  final double zScore;
  final double? ndviCurrent;
  final double ndviMean;
  final double ndviStd;
  final double ndviTrend;
  final int recordsAnalyzed;
  final double cloudGapRatio;
  final String recommendation;

  Analysis({
    required this.parcelId,
    required this.parcelName,
    required this.status,
    required this.anomalyScore,
    required this.mseScore,
    required this.zScore,
    this.ndviCurrent,
    required this.ndviMean,
    required this.ndviStd,
    required this.ndviTrend,
    required this.recordsAnalyzed,
    required this.cloudGapRatio,
    required this.recommendation,
  });

  factory Analysis.fromJson(Map<String, dynamic> json) {
    return Analysis(
      parcelId: json['parcel_id'] as String,
      parcelName: json['parcel_name'] as String,
      status: json['status'] as String,
      anomalyScore: (json['anomaly_score'] as num).toDouble(),
      mseScore: (json['mse_score'] as num).toDouble(),
      zScore: (json['z_score'] as num).toDouble(),
      ndviCurrent: json['ndvi_current'] != null
          ? (json['ndvi_current'] as num).toDouble()
          : null,
      ndviMean: (json['ndvi_mean'] as num).toDouble(),
      ndviStd: (json['ndvi_std'] as num).toDouble(),
      ndviTrend: (json['ndvi_trend'] as num).toDouble(),
      recordsAnalyzed: json['records_analyzed'] as int,
      cloudGapRatio: (json['cloud_gap_ratio'] as num).toDouble(),
      recommendation: json['recommendation'] as String,
    );
  }

  bool get isAnomaly => status == 'ANOMALY_DETECTED';
  bool get isHealthy => status == 'HEALTHY';
  bool get isInsufficient => status == 'INSUFFICIENT_DATA';
}
