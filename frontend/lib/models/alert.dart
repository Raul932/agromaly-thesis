import 'package:flutter/foundation.dart';

@immutable
class Alert {
  final String id;
  final String parcelId;
  final String parcelName;
  final String alertType;
  final String severity;
  final String title;
  final String description;
  final String? aiRecommendation;
  final bool isRead;
  final DateTime createdAt;
  final DateTime? readAt;
  final double? triggeredValue;
  final double? thresholdValue;

  const Alert({
    required this.id,
    required this.parcelId,
    required this.parcelName,
    required this.alertType,
    required this.severity,
    required this.title,
    required this.description,
    this.aiRecommendation,
    required this.isRead,
    required this.createdAt,
    this.readAt,
    this.triggeredValue,
    this.thresholdValue,
  });

  factory Alert.fromJson(Map<String, dynamic> json) {
    return Alert(
      id: json['id'] as String,
      parcelId: json['parcel_id'] as String,
      parcelName: json['parcel_name'] as String,
      alertType: json['alert_type'] as String,
      severity: json['severity'] as String,
      title: json['title'] as String,
      description: json['description'] as String,
      aiRecommendation: json['ai_recommendation'] as String?,
      isRead: json['is_read'] as bool,
      createdAt: DateTime.parse(json['created_at'] as String),
      readAt: json['read_at'] != null
          ? DateTime.parse(json['read_at'] as String)
          : null,
      triggeredValue: (json['triggered_value'] as num?)?.toDouble(),
      thresholdValue: (json['threshold_value'] as num?)?.toDouble(),
    );
  }

  bool get isCritical => severity == 'critical' || severity == 'high';
  bool get hasRecommendation => aiRecommendation != null && aiRecommendation!.isNotEmpty;
}
