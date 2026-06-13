import 'package:flutter/material.dart';
import '../models/alert.dart';
import '../services/alert_service.dart';

/// Centru Alerte AI — afișează alertele de anomalie generate de AI.
class AlertsHubScreen extends StatefulWidget {
  const AlertsHubScreen({super.key});

  @override
  State<AlertsHubScreen> createState() => _AlertsHubScreenState();
}

class _AlertsHubScreenState extends State<AlertsHubScreen> {
  List<Alert> _alerts = [];
  bool _isLoading = true;
  bool _isScanning = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadAlerts();
  }

  Future<void> _loadAlerts() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final alerts = await AlertService.getAlerts();
      if (mounted) {
        setState(() {
          _alerts = alerts;
          _isLoading = false;
        });
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

  Future<void> _markAllRead() async {
    await AlertService.markAllAsRead();
    _loadAlerts();
  }

  Future<void> _scanAllParcels() async {
    setState(() => _isScanning = true);
    try {
      final result = await AlertService.scanAllParcels();
      if (mounted) {
        final analyzed = result['parcels_analyzed'] ?? 0;
        final found = result['anomalies_found'] ?? 0;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              '$analyzed câmp${analyzed == 1 ? '' : 'uri'} analizat${analyzed == 1 ? '' : 'e'}, '
              '$found anomali${found == 1 ? 'e' : 'i'} detectat${found == 1 ? 'ă' : 'e'}.',
            ),
            backgroundColor:
                found > 0 ? const Color(0xFFE76F51) : const Color(0xFF2D6A4F),
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(e.toString().replaceFirst('Exception: ', '')),
            backgroundColor: const Color(0xFFE76F51),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isScanning = false);
        _loadAlerts();
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
        title: const Row(
          children: [
            Icon(Icons.notifications_active, color: Color(0xFFE76F51), size: 22),
            SizedBox(width: 10),
            Text(
              'Centru Alerte AI',
              style: TextStyle(
                color: Colors.white,
                fontSize: 17,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        actions: [
          if (_alerts.any((a) => !a.isRead))
            TextButton(
              onPressed: _markAllRead,
              child: const Text(
                'Marchează toate citite',
                style: TextStyle(color: Color(0xFF52B788), fontSize: 13),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white54),
            onPressed: _isScanning ? null : _loadAlerts,
            tooltip: 'Actualizează alertele',
          ),
        ],
      ),
      body: Column(
        children: [
          if (_isScanning)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              color: const Color(0xFF1A2F45),
              child: const Row(
                children: [
                  SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Color(0xFF52B788),
                    ),
                  ),
                  SizedBox(width: 10),
                  Text(
                    'Se analizează câmpurile...',
                    style: TextStyle(color: Color(0xFF52B788), fontSize: 13),
                  ),
                ],
              ),
            ),
          Expanded(child: _buildBody()),
        ],
      ),
      floatingActionButton: _isScanning
          ? null
          : FloatingActionButton.extended(
              onPressed: _scanAllParcels,
              backgroundColor: const Color(0xFF1B4332),
              icon: const Icon(Icons.radar, color: Color(0xFF52B788)),
              label: const Text(
                'Scanează acum',
                style: TextStyle(
                  color: Color(0xFF52B788),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: Color(0xFFE76F51)),
            SizedBox(height: 16),
            Text(
              'Se încarcă alertele...',
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
              const Icon(Icons.cloud_off, color: Colors.white38, size: 52),
              const SizedBox(height: 16),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white54, fontSize: 14),
              ),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: _loadAlerts,
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Color(0xFFE76F51)),
                ),
                child: const Text('Reîncearcă',
                    style: TextStyle(color: Color(0xFFE76F51))),
              ),
            ],
          ),
        ),
      );
    }

    if (_alerts.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: const Color(0xFF40916C).withValues(alpha: 0.15),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.check_circle_outline,
                color: Color(0xFF40916C),
                size: 44,
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              'Totul în regulă!',
              style: TextStyle(
                color: Colors.white,
                fontSize: 20,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Nicio anomalie detectată de sistemul AI.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.45),
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 32),
            OutlinedButton.icon(
              onPressed: _isScanning ? null : _scanAllParcels,
              icon: const Icon(Icons.radar, size: 18),
              label: const Text('Scanează câmpurile acum'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF52B788),
                side: const BorderSide(color: Color(0xFF52B788)),
                padding:
                    const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
              ),
            ),
          ],
        ),
      );
    }

    final unreadCount = _alerts.where((a) => !a.isRead).length;
    return Column(
      children: [
        if (unreadCount > 0)
          Container(
            margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFFE76F51).withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: const Color(0xFFE76F51).withValues(alpha: 0.3),
              ),
            ),
            child: Row(
              children: [
                const Icon(Icons.warning_amber_rounded,
                    color: Color(0xFFE76F51), size: 22),
                const SizedBox(width: 10),
                Text(
                  '$unreadCount alertă${unreadCount == 1 ? '' : 'e'} necitită${unreadCount == 1 ? '' : 'e'}',
                  style: const TextStyle(
                    color: Color(0xFFE76F51),
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
              ],
            ),
          ),
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 100),
            itemCount: _alerts.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (ctx, i) => _AlertCard(
              alert: _alerts[i],
              onRead: () async {
                await AlertService.markAsRead(_alerts[i].id);
                _loadAlerts();
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _AlertCard extends StatefulWidget {
  final Alert alert;
  final VoidCallback onRead;

  const _AlertCard({required this.alert, required this.onRead});

  @override
  State<_AlertCard> createState() => _AlertCardState();
}

class _AlertCardState extends State<_AlertCard> {
  bool _expanded = false;

  Color get _severityColor {
    switch (widget.alert.severity) {
      case 'critical':
      case 'high':
        return const Color(0xFFE76F51);
      case 'medium':
        return const Color(0xFFE9C46A);
      default:
        return const Color(0xFF52B788);
    }
  }

  String _severityLabel(String severity) {
    switch (severity) {
      case 'critical':
        return 'CRITIC';
      case 'high':
        return 'RIDICAT';
      case 'medium':
        return 'MEDIU';
      case 'low':
        return 'SCĂZUT';
      default:
        return severity.toUpperCase();
    }
  }

  @override
  Widget build(BuildContext context) {
    final alert = widget.alert;
    final color = _severityColor;

    return GestureDetector(
      onTap: () {
        setState(() => _expanded = !_expanded);
        if (!alert.isRead) widget.onRead();
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: color.withValues(alpha: alert.isRead ? 0.04 : 0.08),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: color.withValues(alpha: alert.isRead ? 0.15 : 0.35),
            width: alert.isRead ? 1.0 : 1.4,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                // Unread dot
                if (!alert.isRead)
                  Container(
                    width: 8,
                    height: 8,
                    margin: const EdgeInsets.only(right: 8),
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                    ),
                  ),
                // Severity chip
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _severityLabel(alert.severity),
                    style: TextStyle(
                      color: color,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.8,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    alert.parcelName,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.5),
                      fontSize: 12,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 4),
                Text(
                  _formatDate(alert.createdAt),
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.35),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              alert.title,
              style: TextStyle(
                color: alert.isRead ? Colors.white70 : Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              alert.description,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 12,
                height: 1.4,
              ),
              maxLines: _expanded ? null : 2,
              overflow:
                  _expanded ? TextOverflow.visible : TextOverflow.ellipsis,
            ),
            if (_expanded && alert.hasRecommendation) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF52B788).withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: const Color(0xFF52B788).withValues(alpha: 0.2),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.auto_awesome,
                            color: Color(0xFF52B788), size: 14),
                        SizedBox(width: 6),
                        Text(
                          'Recomandare AI',
                          style: TextStyle(
                            color: Color(0xFF52B788),
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      alert.aiRecommendation!,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.8),
                        fontSize: 13,
                        height: 1.6,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (!_expanded)
              Align(
                alignment: Alignment.centerRight,
                child: Icon(
                  Icons.keyboard_arrow_down,
                  color: Colors.white.withValues(alpha: 0.3),
                  size: 18,
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _formatDate(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 60) return 'acum ${diff.inMinutes} min';
    if (diff.inHours < 24) return 'acum ${diff.inHours}h';
    return 'acum ${diff.inDays}z';
  }
}
