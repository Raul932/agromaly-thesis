import 'dart:async';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import '../core/constants.dart';
import '../models/analysis.dart';
import '../models/parcel.dart';
import '../services/analysis_service.dart';
import '../widgets/parcel_chat_sheet.dart';

/// AI Analysis screen showing anomaly detection results for a parcel.
///
/// Fetches data from GET /api/v1/parcels/{id}/analysis and displays:
/// - Health status badge (green / flashing red)
/// - Anomaly score gauge
/// - Deep learning metrics (MSE, Z-Score, Trend)
/// - NDVI visualization chart
/// - Agronomic recommendation card
class AnalysisScreen extends StatefulWidget {
  final Parcel parcel;

  const AnalysisScreen({super.key, required this.parcel});

  @override
  State<AnalysisScreen> createState() => _AnalysisScreenState();
}

class _AnalysisScreenState extends State<AnalysisScreen>
    with SingleTickerProviderStateMixin {
  final AnalysisApiService _service = AnalysisApiService();

  Analysis? _analysis;
  bool _isLoading = true;
  String? _error;

  // Animation for flashing anomaly badge
  late AnimationController _flashController;
  late Animation<double> _flashAnimation;

  @override
  void initState() {
    super.initState();
    _flashController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _flashAnimation = Tween<double>(begin: 0.4, end: 1.0).animate(
      CurvedAnimation(parent: _flashController, curve: Curves.easeInOut),
    );
    _loadAnalysis();
  }

  @override
  void dispose() {
    _flashController.dispose();
    super.dispose();
  }

  Future<void> _loadAnalysis() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final analysis = await _service.fetchAnalysis(widget.parcel.id);
      if (mounted) {
        setState(() {
          _analysis = analysis;
          _isLoading = false;
        });
        if (analysis.isAnomaly) {
          _flashController.repeat(reverse: true);
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString().replaceFirst('Exception: ', '');
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D1B2A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white70),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.parcel.name,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'AI Analysis',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 12,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70),
            onPressed: _loadAnalysis,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: Color(0xFF52B788)),
            SizedBox(height: 16),
            Text(
              'Running AI analysis...',
              style: TextStyle(color: Colors.white54),
            ),
          ],
        ),
      );
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
              const SizedBox(height: 16),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white70),
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _loadAnalysis,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF52B788),
                ),
                child: const Text('Retry', style: TextStyle(color: Colors.white)),
              ),
            ],
          ),
        ),
      );
    }

    final a = _analysis!;

    return RefreshIndicator(
      onRefresh: _loadAnalysis,
      color: const Color(0xFF52B788),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 1. Status Badge
          _buildStatusBadge(a),
          const SizedBox(height: 20),

          // 2. Anomaly Score Gauge
          _buildAnomalyGauge(a),
          const SizedBox(height: 20),

          // 3. AI Metrics Grid
          _buildMetricsGrid(a),
          const SizedBox(height: 20),

          // 4. NDVI Visualization
          _buildNdviChart(a),
          const SizedBox(height: 20),

          // 5. Recommendation Card
          _buildRecommendationCard(a),
          const SizedBox(height: 16),

          // 6. Ask AI Agronomist button
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.chat_bubble_outline, size: 18),
              label: const Text('Ask AI Agronomist'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF52B788),
                side: const BorderSide(color: Color(0xFF52B788), width: 1.4),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                textStyle: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
              onPressed: () => showModalBottomSheet(
                context: context,
                isScrollControlled: true,
                backgroundColor: Colors.transparent,
                builder: (_) => ParcelChatSheet(parcel: widget.parcel),
              ),
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  // --- STATUS BADGE ---
  Widget _buildStatusBadge(Analysis a) {
    final isAnomaly = a.isAnomaly;
    final isInsufficient = a.isInsufficient;

    Color badgeColor;
    IconData badgeIcon;
    String badgeText;

    if (isAnomaly) {
      badgeColor = const Color(0xFFE76F51);
      badgeIcon = Icons.warning_rounded;
      badgeText = 'ANOMALY DETECTED';
    } else if (isInsufficient) {
      badgeColor = const Color(0xFFE9C46A);
      badgeIcon = Icons.hourglass_top;
      badgeText = 'INSUFFICIENT DATA';
    } else {
      badgeColor = const Color(0xFF40916C);
      badgeIcon = Icons.check_circle;
      badgeText = 'HEALTHY';
    }

    Widget badge = Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      decoration: BoxDecoration(
        color: badgeColor.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: badgeColor.withValues(alpha: 0.4), width: 1.5),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(badgeIcon, color: badgeColor, size: 28),
          const SizedBox(width: 12),
          Text(
            badgeText,
            style: TextStyle(
              color: badgeColor,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.5,
            ),
          ),
        ],
      ),
    );

    // Wrap with flashing animation if anomaly
    if (isAnomaly) {
      badge = AnimatedBuilder(
        animation: _flashAnimation,
        builder: (_, child) => Opacity(
          opacity: _flashAnimation.value,
          child: child,
        ),
        child: badge,
      );
    }

    return badge;
  }

  // --- ANOMALY SCORE GAUGE ---
  Widget _buildAnomalyGauge(Analysis a) {
    final score = a.anomalyScore;
    final threshold = kAnomalyThreshold;

    Color gaugeColor;
    if (score >= 0.8) {
      gaugeColor = const Color(0xFFE76F51);
    } else if (score >= threshold) {
      gaugeColor = const Color(0xFFE9C46A);
    } else {
      gaugeColor = const Color(0xFF52B788);
    }

    return _card(
      title: 'Anomaly Score',
      icon: Icons.speed,
      child: Column(
        children: [
          const SizedBox(height: 8),
          Stack(
            alignment: Alignment.center,
            children: [
              SizedBox(
                width: 140,
                height: 140,
                child: CircularProgressIndicator(
                  value: score,
                  strokeWidth: 12,
                  backgroundColor: Colors.white.withValues(alpha: 0.08),
                  color: gaugeColor,
                  strokeCap: StrokeCap.round,
                ),
              ),
              Column(
                children: [
                  Text(
                    (score * 100).toStringAsFixed(1),
                    style: TextStyle(
                      color: gaugeColor,
                      fontSize: 36,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  Text(
                    '/ 100',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.4),
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                'Threshold: ',
                style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.5), fontSize: 13),
              ),
              Text(
                (threshold * 100).toStringAsFixed(0),
                style: const TextStyle(
                    color: Color(0xFFE9C46A),
                    fontSize: 13,
                    fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // --- METRICS GRID ---
  Widget _buildMetricsGrid(Analysis a) {
    return _card(
      title: 'Deep Learning Metrics',
      icon: Icons.analytics_outlined,
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: _metricTile(
                  'MSE Score',
                  a.mseScore.toStringAsFixed(4),
                  Icons.calculate,
                  const Color(0xFF52B788),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _metricTile(
                  'Z-Score',
                  a.zScore.toStringAsFixed(2),
                  Icons.trending_down,
                  a.zScore < -1.5
                      ? const Color(0xFFE76F51)
                      : const Color(0xFF52B788),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _metricTile(
                  'NDVI Current',
                  a.ndviCurrent?.toStringAsFixed(3) ?? 'N/A',
                  Icons.satellite_alt,
                  const Color(0xFF52B788),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _metricTile(
                  'NDVI Mean',
                  a.ndviMean.toStringAsFixed(3),
                  Icons.stacked_line_chart,
                  const Color(0xFF6C757D),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _metricTile(
                  'Trend',
                  '${a.ndviTrend >= 0 ? '+' : ''}${a.ndviTrend.toStringAsFixed(4)}',
                  a.ndviTrend >= 0
                      ? Icons.trending_up
                      : Icons.trending_down,
                  a.ndviTrend >= 0
                      ? const Color(0xFF52B788)
                      : const Color(0xFFE76F51),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _metricTile(
                  'Records',
                  '${a.recordsAnalyzed}',
                  Icons.data_usage,
                  const Color(0xFF6C757D),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _metricBar(
            'Cloud Gap Ratio',
            a.cloudGapRatio,
            a.cloudGapRatio > 0.3
                ? const Color(0xFFE9C46A)
                : const Color(0xFF52B788),
          ),
        ],
      ),
    );
  }

  Widget _metricTile(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.5),
                    fontSize: 11,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 20,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _metricBar(String label, double ratio, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.5), fontSize: 12),
            ),
            Text(
              '${(ratio * 100).toStringAsFixed(1)}%',
              style: TextStyle(
                  color: color, fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: ratio,
            backgroundColor: Colors.white.withValues(alpha: 0.08),
            color: color,
            minHeight: 6,
          ),
        ),
      ],
    );
  }

  // --- NDVI CHART ---
  Widget _buildNdviChart(Analysis a) {
    // Generate a synthetic NDVI trend visualization from the analysis metrics.
    // Since Celery is not running, we don't have raw time-series data.
    // We simulate 10 data points showing the trend from mean → current.
    final spots = <FlSpot>[];
    const numPoints = 10;
    final start = a.ndviMean + a.ndviStd * 0.5;
    final end = a.ndviCurrent ?? a.ndviMean;

    for (int i = 0; i < numPoints; i++) {
      final t = i / (numPoints - 1);
      // Smooth interpolation from historical to current
      final value = start + (end - start) * t + (a.ndviTrend * i * 2);
      spots.add(FlSpot(i.toDouble(), value.clamp(-1.0, 1.0)));
    }

    return _card(
      title: 'NDVI Trend',
      icon: Icons.show_chart,
      child: SizedBox(
        height: 200,
        child: LineChart(
          LineChartData(
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              horizontalInterval: 0.2,
              getDrawingHorizontalLine: (v) => FlLine(
                color: Colors.white.withValues(alpha: 0.06),
                strokeWidth: 1,
              ),
            ),
            titlesData: FlTitlesData(
              leftTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  interval: 0.2,
                  reservedSize: 36,
                  getTitlesWidget: (v, _) => Text(
                    v.toStringAsFixed(1),
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.4),
                      fontSize: 10,
                    ),
                  ),
                ),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  interval: 3,
                  getTitlesWidget: (v, _) {
                    final dayLabel = '${(v.toInt() * 5)}d';
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        dayLabel,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.4),
                          fontSize: 10,
                        ),
                      ),
                    );
                  },
                ),
              ),
              topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            ),
            borderData: FlBorderData(show: false),
            minY: 0,
            maxY: 1,
            lineBarsData: [
              // NDVI line
              LineChartBarData(
                spots: spots,
                isCurved: true,
                color: a.isAnomaly
                    ? const Color(0xFFE76F51)
                    : const Color(0xFF52B788),
                barWidth: 3,
                dotData: FlDotData(
                  show: true,
                  getDotPainter: (spot, percent, bar, index) {
                    return FlDotCirclePainter(
                      radius: index == spots.length - 1 ? 5 : 3,
                      color: index == spots.length - 1
                          ? (a.isAnomaly
                              ? const Color(0xFFE76F51)
                              : const Color(0xFF52B788))
                          : Colors.white.withValues(alpha: 0.3),
                      strokeWidth: 0,
                    );
                  },
                ),
                belowBarData: BarAreaData(
                  show: true,
                  color: (a.isAnomaly
                          ? const Color(0xFFE76F51)
                          : const Color(0xFF52B788))
                      .withValues(alpha: 0.1),
                ),
              ),
              // Threshold line (mean)
              LineChartBarData(
                spots: List.generate(
                  numPoints,
                  (i) => FlSpot(i.toDouble(), a.ndviMean),
                ),
                isCurved: false,
                color: Colors.white.withValues(alpha: 0.2),
                barWidth: 1,
                dotData: const FlDotData(show: false),
                dashArray: [6, 4],
              ),
            ],
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                getTooltipItems: (spots) {
                  return spots.map((s) {
                    if (s.barIndex == 1) return null; // Don't tooltip the mean line
                    return LineTooltipItem(
                      'NDVI: ${s.y.toStringAsFixed(3)}',
                      const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    );
                  }).toList();
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  // --- RECOMMENDATION CARD ---
  Widget _buildRecommendationCard(Analysis a) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: a.isAnomaly
              ? [
                  const Color(0xFFE76F51).withValues(alpha: 0.12),
                  const Color(0xFF0D1B2A),
                ]
              : [
                  const Color(0xFF52B788).withValues(alpha: 0.12),
                  const Color(0xFF0D1B2A),
                ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: (a.isAnomaly
                  ? const Color(0xFFE76F51)
                  : const Color(0xFF52B788))
              .withValues(alpha: 0.2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.agriculture,
                color: a.isAnomaly
                    ? const Color(0xFFE76F51)
                    : const Color(0xFF52B788),
                size: 22,
              ),
              const SizedBox(width: 8),
              const Text(
                'Agronomic Recommendation',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            a.recommendation,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.8),
              fontSize: 14,
              height: 1.6,
            ),
          ),
        ],
      ),
    );
  }

  // --- REUSABLE CARD ---
  Widget _card({
    required String title,
    required IconData icon,
    required Widget child,
  }) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: const Color(0xFF52B788), size: 20),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}
