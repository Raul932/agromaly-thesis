import 'dart:async';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import '../core/constants.dart';
import '../models/analysis.dart';
import '../models/parcel.dart';
import '../models/forecast.dart';
import '../services/alert_service.dart';
import '../services/analysis_service.dart';
import '../services/parcel_service.dart';
import '../services/weather_service.dart';
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
  final ParcelApiService _parcelService = ParcelApiService();

  Analysis? _analysis;
  bool _isSyncing = false;
  bool _isLoading = true;
  String? _error;

  // AI Insight state (RAG recommendation, auto-loaded on anomaly)
  String? _aiInsight;
  bool _aiInsightLoading = false;
  String? _aiInsightError;

  // 7-day forecast state
  Forecast? _forecast;
  bool _forecastLoading = true;

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
    _loadForecast();
  }

  Future<void> _loadForecast() async {
    setState(() => _forecastLoading = true);
    try {
      final forecast = await WeatherService.getForecast(widget.parcel.id);
      if (mounted) {
        setState(() {
          _forecast = forecast;
          _forecastLoading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _forecastLoading = false);
    }
  }

  Future<void> _openWeeklyAdvice() async {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _WeeklyAdviceSheet(parcelId: widget.parcel.id),
    );
  }

  @override
  void dispose() {
    _flashController.dispose();
    super.dispose();
  }

  Future<void> _syncParcel() async {
    if (_isSyncing) return;
    setState(() => _isSyncing = true);
    try {
      final result = await _parcelService.syncParcel(widget.parcel.id);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(result.message),
            backgroundColor: result.recentlySynced
                ? const Color(0xFF2D6A4F)
                : const Color(0xFF52B788),
            duration: const Duration(seconds: 4),
          ),
        );
        // Sync now runs synchronously on the server — reload analysis immediately.
        if (!result.recentlySynced) {
          await _loadAnalysis();
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(e.toString().replaceFirst('Exception: ', '')),
            backgroundColor: Colors.redAccent,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSyncing = false);
    }
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
          _loadAiInsight();
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

  Future<void> _loadAiInsight() async {
    if (!mounted) return;
    setState(() {
      _aiInsightLoading = true;
      _aiInsightError = null;
      _aiInsight = null;
    });

    try {
      // Check for an existing RAG recommendation in the most recent alerts
      final alerts = await AlertService.getParcelAlerts(
        widget.parcel.id,
        limit: 5,
      );
      final existing = alerts.where(
        (a) => a.aiRecommendation != null && a.aiRecommendation!.isNotEmpty,
      ).toList();

      if (existing.isNotEmpty) {
        if (mounted) {
          setState(() {
            _aiInsight = existing.first.aiRecommendation;
            _aiInsightLoading = false;
          });
        }
        return;
      }

      // No cached recommendation — generate on demand
      final rec =
          await AlertService.generateAiRecommendation(widget.parcel.id);
      if (mounted) {
        setState(() {
          _aiInsight = rec;
          _aiInsightLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _aiInsightError = e.toString().replaceFirst('Exception: ', '');
          _aiInsightLoading = false;
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
            tooltip: 'Actualizează date satelit',
            icon: _isSyncing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      color: Color(0xFF52B788),
                      strokeWidth: 2.5,
                    ),
                  )
                : const Icon(Icons.satellite_alt, color: Colors.white70),
            onPressed: _isSyncing ? null : _syncParcel,
          ),
          IconButton(
            tooltip: 'Refresh analysis',
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

          // 5. Recent Weather Card
          if (a.weatherContext != null) ...[
            _buildWeatherCard(a),
            const SizedBox(height: 20),
          ],

          // 5b. 7-Day Forecast Card
          _buildForecastCard(),
          const SizedBox(height: 20),

          // 6. Recommendation Card
          _buildRecommendationCard(a),
          const SizedBox(height: 16),

          // 7. AI Insight Card — auto-loads RAG recommendation on anomaly
          if (a.isAnomaly) ...[
            _buildAiInsightCard(),
            const SizedBox(height: 16),
          ],

          // 7. Ask AI Agronomist button
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.chat_bubble_outline, size: 18),
              label: const Text('Întreabă Agronomul AI'),
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
      badgeText = 'CÂMPUL TĂU NECESITĂ ATENȚIE';
    } else if (isInsufficient) {
      badgeColor = const Color(0xFFE9C46A);
      badgeIcon = Icons.satellite_alt;
      badgeText = 'DATE ÎN CURS DE COLECTARE';
    } else {
      badgeColor = const Color(0xFF40916C);
      badgeIcon = Icons.check_circle;
      badgeText = 'CÂMPUL TĂU ESTE SĂNĂTOS';
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
          Flexible(
            child: Text(
              badgeText,
              style: TextStyle(
                color: badgeColor,
                fontSize: 18,
                fontWeight: FontWeight.w800,
                letterSpacing: 1.2,
              ),
              softWrap: true,
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

  // --- RISK LEVEL GAUGE ---
  Widget _buildAnomalyGauge(Analysis a) {
    final score = a.anomalyScore;
    final threshold = kAnomalyThreshold;

    Color gaugeColor;
    String riskLabel;
    if (score >= 0.8) {
      gaugeColor = const Color(0xFFE76F51);
      riskLabel = 'Risc Ridicat';
    } else if (score >= threshold) {
      gaugeColor = const Color(0xFFE9C46A);
      riskLabel = 'Risc Mediu';
    } else if (score >= 0.3) {
      gaugeColor = const Color(0xFF52B788);
      riskLabel = 'Risc Scăzut';
    } else {
      gaugeColor = const Color(0xFF40916C);
      riskLabel = 'Fără Risc';
    }

    return _card(
      title: 'Nivel de Risc',
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
                    riskLabel,
                    style: TextStyle(
                      color: gaugeColor.withValues(alpha: 0.85),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
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
                'Prag: ',
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

  // --- FIELD HEALTH SUMMARY (farmer-friendly) ---
  Widget _buildMetricsGrid(Analysis a) {
    // Vegetation level label from NDVI
    String vegLevel;
    Color vegColor;
    IconData vegIcon;
    final ndvi = a.ndviCurrent ?? a.ndviMean;
    if (ndvi >= 0.6) {
      vegLevel = 'Excelent';
      vegColor = const Color(0xFF40916C);
      vegIcon = Icons.local_florist;
    } else if (ndvi >= 0.4) {
      vegLevel = 'Bun';
      vegColor = const Color(0xFF52B788);
      vegIcon = Icons.eco;
    } else if (ndvi >= 0.2) {
      vegLevel = 'Acceptabil';
      vegColor = const Color(0xFFE9C46A);
      vegIcon = Icons.grass;
    } else {
      vegLevel = 'Slab';
      vegColor = const Color(0xFFE76F51);
      vegIcon = Icons.warning_amber_rounded;
    }

    // Trend label
    String trendLabel;
    Color trendColor;
    IconData trendIcon;
    if (a.ndviTrend > 0.005) {
      trendLabel = 'Creștere';
      trendColor = const Color(0xFF52B788);
      trendIcon = Icons.trending_up;
    } else if (a.ndviTrend < -0.008) {
      trendLabel = 'Declin';
      trendColor = const Color(0xFFE76F51);
      trendIcon = Icons.trending_down;
    } else {
      trendLabel = 'Stabil';
      trendColor = const Color(0xFF6C757D);
      trendIcon = Icons.trending_flat;
    }

    // Last check label
    String lastCheck = 'Nicidată';
    if (widget.parcel.lastNdviAt != null) {
      try {
        final dt = DateTime.parse(widget.parcel.lastNdviAt!).toLocal();
        final diff = DateTime.now().difference(dt);
        if (diff.inDays == 0) {
          lastCheck = 'Azi';
        } else if (diff.inDays == 1) {
          lastCheck = 'Ieri';
        } else {
          lastCheck = 'acum ${diff.inDays} zile';
        }
      } catch (_) {}
    }

    // Data quality
    final dataQualityPct = ((1.0 - a.cloudGapRatio) * 100).round();
    final dataColor = dataQualityPct >= 70
        ? const Color(0xFF52B788)
        : dataQualityPct >= 40
            ? const Color(0xFFE9C46A)
            : const Color(0xFFE76F51);

    return Column(
      children: [
        _card(
          title: 'Sumar Sănătate Câmp',
          icon: Icons.agriculture,
          child: Column(
            children: [
              Row(
                children: [
                  Expanded(
                      child: _summaryTile(
                          'Acoperire Vegetație', vegLevel, vegIcon, vegColor)),
                  const SizedBox(width: 12),
                  Expanded(
                      child: _summaryTile(
                          'Tendință Recentă', trendLabel, trendIcon, trendColor)),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                      child: _summaryTile('Ultima Verificare Satelit', lastCheck,
                          Icons.satellite_alt, const Color(0xFF52B788))),
                  const SizedBox(width: 12),
                  Expanded(
                      child: _summaryTile(
                          'Imagini Disponibile',
                          '${a.recordsAnalyzed} treceri',
                          Icons.photo_library_outlined,
                          const Color(0xFF6C757D))),
                ],
              ),
              const SizedBox(height: 12),
              _dataQualityBar(dataQualityPct, dataColor),
            ],
          ),
        ),
        const SizedBox(height: 12),
        // Technical details — collapsed by default
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: Container(
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.03),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
            ),
            child: ExpansionTile(
              tilePadding:
                  const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              title: Row(
                children: [
                  const Icon(Icons.science_outlined,
                      color: Colors.white38, size: 18),
                  const SizedBox(width: 8),
                  Text(
                    'Detalii Tehnice',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.5),
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
              iconColor: Colors.white38,
              collapsedIconColor: Colors.white24,
              children: [
                Row(
                  children: [
                    Expanded(
                        child: _metricTile('Anomaly Score',
                            a.mseScore.toStringAsFixed(4), Icons.calculate,
                            const Color(0xFF52B788))),
                    const SizedBox(width: 10),
                    Expanded(
                        child: _metricTile(
                            'Z-Score',
                            a.zScore.toStringAsFixed(2),
                            Icons.trending_down,
                            a.zScore < -1.5
                                ? const Color(0xFFE76F51)
                                : const Color(0xFF52B788))),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                        child: _metricTile(
                            'NDVI Current',
                            a.ndviCurrent?.toStringAsFixed(3) ?? 'N/A',
                            Icons.satellite_alt,
                            const Color(0xFF52B788))),
                    const SizedBox(width: 10),
                    Expanded(
                        child: _metricTile('NDVI Mean',
                            a.ndviMean.toStringAsFixed(3),
                            Icons.stacked_line_chart,
                            const Color(0xFF6C757D))),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                        child: _metricTile(
                            'NDVI Trend',
                            '${a.ndviTrend >= 0 ? '+' : ''}${a.ndviTrend.toStringAsFixed(4)}',
                            a.ndviTrend >= 0
                                ? Icons.trending_up
                                : Icons.trending_down,
                            a.ndviTrend >= 0
                                ? const Color(0xFF52B788)
                                : const Color(0xFFE76F51))),
                    const SizedBox(width: 10),
                    Expanded(
                        child: _metricTile(
                            'Cloud Gap',
                            '${(a.cloudGapRatio * 100).toStringAsFixed(1)}%',
                            Icons.cloud_outlined,
                            a.cloudGapRatio > 0.3
                                ? const Color(0xFFE9C46A)
                                : const Color(0xFF52B788))),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _summaryTile(
      String label, String value, IconData icon, Color color) {
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
                child: Text(label,
                    style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.5),
                        fontSize: 11),
                    overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(value,
              style: TextStyle(
                  color: color,
                  fontSize: 16,
                  fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }

  Widget _dataQualityBar(int pct, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('Data Quality',
                style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.5),
                    fontSize: 12)),
            Text('$pct% clear-sky images',
                style: TextStyle(
                    color: color,
                    fontSize: 12,
                    fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: pct / 100.0,
            backgroundColor: Colors.white.withValues(alpha: 0.08),
            color: color,
            minHeight: 6,
          ),
        ),
      ],
    );
  }

  Widget _metricTile(String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 14),
              const SizedBox(width: 5),
              Expanded(
                child: Text(label,
                    style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.45),
                        fontSize: 10),
                    overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
          const SizedBox(height: 5),
          Text(value,
              style: TextStyle(
                  color: color, fontSize: 16, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }

  // --- NDVI CHART ---
  Widget _buildNdviChart(Analysis a) {
    // Synthetic NDVI trend: interpolate from historical baseline to current value.
    // The start point is mean+0.5*std (representative of "normal" conditions);
    // the end point is the actual current NDVI reading.
    final spots = <FlSpot>[];
    const numPoints = 10;
    final start = a.ndviMean + a.ndviStd * 0.5;
    final end = a.ndviCurrent ?? a.ndviMean;

    for (int i = 0; i < numPoints; i++) {
      final t = i / (numPoints - 1);
      final value = start + (end - start) * t;
      spots.add(FlSpot(i.toDouble(), value.clamp(0.0, 1.0)));
    }

    return _card(
      title: 'Vegetation Over Time',
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

  // --- AI INSIGHT CARD (RAG-generated, anomaly only) ---
  Widget _buildAiInsightCard() {
    const accentColor = Color(0xFF52B788);

    final cardDecoration = BoxDecoration(
      color: Colors.white.withValues(alpha: 0.04),
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: accentColor.withValues(alpha: 0.2)),
    );

    // Loading state
    if (_aiInsightLoading) {
      return Container(
        padding: const EdgeInsets.all(20),
        decoration: cardDecoration,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.auto_awesome, color: accentColor, size: 20),
                const SizedBox(width: 8),
                const Text(
                  'Recomandare AI',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            const Center(
              child: Column(
                children: [
                  CircularProgressIndicator(
                      color: accentColor, strokeWidth: 2.5),
                  SizedBox(height: 12),
                  Text(
                    'Generating AI recommendation...',
                    style: TextStyle(color: Colors.white54, fontSize: 13),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],
        ),
      );
    }

    // Error state
    if (_aiInsightError != null) {
      return Container(
        padding: const EdgeInsets.all(20),
        decoration: cardDecoration,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.auto_awesome, color: accentColor, size: 20),
                const SizedBox(width: 8),
                const Text(
                  'Recomandare AI',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              _aiInsightError!,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: _loadAiInsight,
              icon: const Icon(Icons.refresh, size: 16, color: accentColor),
              label: const Text(
                'Retry',
                style: TextStyle(color: accentColor, fontSize: 13),
              ),
            ),
          ],
        ),
      );
    }

    // Not yet loaded / hidden
    if (_aiInsight == null) return const SizedBox.shrink();

    // Success state
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            accentColor.withValues(alpha: 0.09),
            const Color(0xFF0D1B2A),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: accentColor.withValues(alpha: 0.28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_awesome, color: accentColor, size: 20),
              const SizedBox(width: 8),
              const Text(
                'Recomandare AI',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const Spacer(),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: accentColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Text(
                  'GPT-4o',
                  style: TextStyle(
                    color: accentColor,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            _aiInsight!,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.82),
              fontSize: 14,
              height: 1.65,
            ),
          ),
        ],
      ),
    );
  }

  // --- WEATHER CARD ---
  Widget _buildWeatherCard(Analysis a) {
    final w = a.weatherContext!;
    final cause = w['cause_hint'] as String? ?? 'normal';
    final precip = (w['total_precip_mm'] as num?)?.toDouble();
    final dryDays = w['dry_spell_days'] as int?;
    final hotDays = w['hot_days'] as int?;
    final frostDays = w['frost_days'] as int?;
    final heavyRainDays = w['heavy_rain_days'] as int?;
    final period = w['period_days'] as int? ?? 14;

    String emoji;
    String title;
    String subtitle;
    Color color;

    switch (cause) {
      case 'drought':
        emoji = '☀️';
        title = 'Perioadă secetoasă';
        subtitle = [
          if (dryDays != null && dryDays > 0) '$dryDays zile consecutive fără ploaie',
          if (precip != null) 'total ${precip.toStringAsFixed(0)}mm în $period zile',
        ].join(' · ');
        color = const Color(0xFFE9C46A);
        break;
      case 'heat_stress':
        emoji = '🌡️';
        title = 'Căldură excesivă';
        subtitle = [
          if (hotDays != null && hotDays > 0) '$hotDays zile peste 33°C',
          if (precip != null) '${precip.toStringAsFixed(0)}mm ploaie',
        ].join(' · ');
        color = const Color(0xFFE76F51);
        break;
      case 'frost':
        emoji = '❄️';
        title = 'Risc de îngheț';
        subtitle = [
          if (frostDays != null && frostDays > 0) '$frostDays zile sub 2°C',
          'în ultimele $period zile',
        ].join(' · ');
        color = const Color(0xFF90E0EF);
        break;
      case 'heavy_rain':
        emoji = '🌧️';
        title = 'Precipitații abundente';
        subtitle = [
          if (heavyRainDays != null && heavyRainDays > 0)
            '$heavyRainDays zile cu ploaie torențială (>20mm/zi)',
          if (precip != null) 'total ${precip.toStringAsFixed(0)}mm',
        ].join(' · ');
        color = const Color(0xFF52B788);
        break;
      default:
        emoji = '🌤️';
        title = 'Vreme favorabilă';
        subtitle = precip != null
            ? '${precip.toStringAsFixed(0)}mm precipitații în ultimele $period zile'
            : 'Condiții normale în ultimele $period zile';
        color = const Color(0xFF52B788);
    }

    return _card(
      title: 'Vreme Recentă',
      icon: Icons.wb_sunny_outlined,
      child: Row(
        children: [
          Text(emoji, style: const TextStyle(fontSize: 36)),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    color: color,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (subtitle.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.6),
                      fontSize: 12,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
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
                'Ce trebuie să faci?',
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

  // --- 7-DAY FORECAST CARD ---
  Widget _buildForecastCard() {
    if (_forecastLoading) {
      return _card(
        title: 'Prognoză 7 zile',
        icon: Icons.wb_sunny_outlined,
        child: const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Center(
            child: SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Color(0xFF52B788)),
            ),
          ),
        ),
      );
    }

    final forecast = _forecast;
    if (forecast == null || forecast.days.isEmpty) {
      return _card(
        title: 'Prognoză 7 zile',
        icon: Icons.wb_sunny_outlined,
        child: Text(
          'Prognoza meteo nu este disponibilă momentan.',
          style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5), fontSize: 13),
        ),
      );
    }

    return _card(
      title: 'Prognoză 7 zile',
      icon: Icons.wb_sunny_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: forecast.days
                  .map((d) => _forecastDayTile(d))
                  .toList(),
            ),
          ),
          if (forecast.warnings.isNotEmpty) ...[
            const SizedBox(height: 14),
            ...forecast.warnings.map(
              (w) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.warning_amber_rounded,
                        color: Color(0xFFE9C46A), size: 16),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        w,
                        style: const TextStyle(
                            color: Color(0xFFE9C46A), fontSize: 12.5),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.auto_awesome, size: 17),
              label: const Text('Sfat AI pentru această săptămână'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF4CC9F0),
                side: const BorderSide(color: Color(0xFF4CC9F0), width: 1.2),
                padding: const EdgeInsets.symmetric(vertical: 12),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                textStyle: const TextStyle(
                    fontSize: 13.5, fontWeight: FontWeight.w600),
              ),
              onPressed: _openWeeklyAdvice,
            ),
          ),
        ],
      ),
    );
  }

  Widget _forecastDayTile(ForecastDay d) {
    return Container(
      width: 64,
      margin: const EdgeInsets.only(right: 8),
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.07)),
      ),
      child: Column(
        children: [
          Text(
            d.weekday,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.6),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Text(d.emoji, style: const TextStyle(fontSize: 20)),
          const SizedBox(height: 6),
          Text(
            '${d.tempMax.round()}°',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
          Text(
            '${d.tempMin.round()}°',
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.4),
              fontSize: 11,
            ),
          ),
          if (d.precipitationMm > 0) ...[
            const SizedBox(height: 4),
            Text(
              '${d.precipitationMm.toStringAsFixed(d.precipitationMm < 1 ? 1 : 0)}mm',
              style: const TextStyle(
                color: Color(0xFF4CC9F0),
                fontSize: 10,
              ),
            ),
          ],
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

/// Bottom sheet that fetches and shows AI weekly field-operations advice.
class _WeeklyAdviceSheet extends StatefulWidget {
  final String parcelId;

  const _WeeklyAdviceSheet({required this.parcelId});

  @override
  State<_WeeklyAdviceSheet> createState() => _WeeklyAdviceSheetState();
}

class _WeeklyAdviceSheetState extends State<_WeeklyAdviceSheet> {
  String? _advice;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final advice = await WeatherService.getWeeklyAdvice(widget.parcelId);
      if (mounted) {
        setState(() {
          _advice = advice;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString().replaceFirst('Exception: ', '');
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.4,
      maxChildSize: 0.92,
      expand: false,
      builder: (_, scrollController) {
        return SafeArea(
          top: false,
          child: Container(
          decoration: const BoxDecoration(
            color: Color(0xFF0D1B2A),
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            children: [
              Center(
                child: Container(
                  margin: const EdgeInsets.only(top: 12, bottom: 8),
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.white24,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 4, 20, 12),
                child: Row(
                  children: [
                    Icon(Icons.auto_awesome, color: Color(0xFF4CC9F0), size: 22),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Sfat AI pentru această săptămână',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const Divider(color: Colors.white12, height: 1),
              Expanded(
                child: _buildContent(scrollController),
              ),
            ],
          ),
          ),
        );
      },
    );
  }

  Widget _buildContent(ScrollController scrollController) {
    if (_loading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: Color(0xFF4CC9F0)),
            SizedBox(height: 16),
            Text(
              'Agronomul AI analizează prognoza...',
              style: TextStyle(color: Colors.white54, fontSize: 13),
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
              const Icon(Icons.cloud_off, color: Colors.white38, size: 48),
              const SizedBox(height: 16),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white54, fontSize: 14),
              ),
              const SizedBox(height: 20),
              OutlinedButton(
                onPressed: _load,
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Color(0xFF4CC9F0)),
                ),
                child: const Text('Reîncearcă',
                    style: TextStyle(color: Color(0xFF4CC9F0))),
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      controller: scrollController,
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          _advice ?? '',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 14,
            height: 1.6,
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}
