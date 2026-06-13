import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../models/upload_session.dart';
import '../services/upload_service.dart';

/// Import Boundaries Screen — Link-based Cross-Device Upload Flow.
///
/// Allows farmers to import APIA .gpx parcel boundary files from their PC.
///
/// State machine:
///   [idle]    → tap "Get Upload Link"
///   [loading] (creating session)
///   [link]    → show copyable URL + poll for status
///   [preview] → show detected parcels, confirm or discard
///   [saving]  → POST /confirm
///   [done]    → success + navigate
///   [error]   → error banner + retry
class ImportBoundariesScreen extends StatefulWidget {
  const ImportBoundariesScreen({super.key});

  @override
  State<ImportBoundariesScreen> createState() => _ImportBoundariesScreenState();
}

enum _UploadState { idle, loading, link, preview, saving, done, error }

class _ImportBoundariesScreenState extends State<ImportBoundariesScreen> {
  final _uploadService = UploadService();

  _UploadState _state = _UploadState.idle;
  String? _errorMessage;

  UploadSession? _session;
  List<GpxParcelPreview> _previews = [];
  int _createdCount = 0;

  // Polling
  Timer? _pollTimer;
  static const _pollInterval = Duration(seconds: 3);

  // Countdown
  Timer? _countdownTimer;
  int _secondsRemaining = 900; // 15 min

  @override
  void dispose() {
    _pollTimer?.cancel();
    _countdownTimer?.cancel();
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // State transitions
  // -------------------------------------------------------------------------

  Future<void> _startSession() async {
    setState(() {
      _state = _UploadState.loading;
      _errorMessage = null;
    });

    try {
      final session = await _uploadService.createSession();
      if (!mounted) return;

      final now = DateTime.now();
      _secondsRemaining =
          session.expiresAt.difference(now).inSeconds.clamp(0, 900);

      setState(() {
        _session = session;
        _state = _UploadState.link;
      });

      _startPolling();
      _startCountdown();
    } on UploadException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
        _state = _UploadState.error;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Connection error. Is the server running?';
        _state = _UploadState.error;
      });
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(_pollInterval, (_) => _poll());
  }

  Future<void> _poll() async {
    if (_session == null) return;
    try {
      final status = await _uploadService.pollStatus(_session!.token);
      if (!mounted) return;

      switch (status.status) {
        case UploadSessionStatus.uploaded:
          _stopPolling();
          _stopCountdown();
          setState(() {
            _previews = status.parcels;
            _state = _UploadState.preview;
          });
          break;
        case UploadSessionStatus.expired:
          _stopPolling();
          _stopCountdown();
          setState(() {
            _errorMessage = 'Session expired. Please generate a new upload link.';
            _state = _UploadState.error;
          });
          break;
        case UploadSessionStatus.confirmed:
          break;
        case UploadSessionStatus.pending:
          break;
        default:
          break;
      }
    } catch (_) {
      // Ignore poll errors — keep retrying
    }
  }

  void _stopPolling() => _pollTimer?.cancel();
  void _stopCountdown() => _countdownTimer?.cancel();

  void _startCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {
        if (_secondsRemaining > 0) {
          _secondsRemaining--;
        } else {
          _stopPolling();
          _stopCountdown();
          if (_state == _UploadState.link) {
            _state = _UploadState.error;
            _errorMessage = 'Session expired. Please generate a new upload link.';
          }
        }
      });
    });
  }

  Future<void> _confirm() async {
    if (_session == null) return;
    setState(() => _state = _UploadState.saving);

    try {
      final result = await _uploadService.confirmUpload(_session!.token);
      if (!mounted) return;
      setState(() {
        _createdCount = result.createdParcelIds.length;
        _state = _UploadState.done;
      });
    } on UploadException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
        _state = _UploadState.error;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Connection error during confirmation.';
        _state = _UploadState.error;
      });
    }
  }

  void _reset() {
    _stopPolling();
    _stopCountdown();
    setState(() {
      _state = _UploadState.idle;
      _session = null;
      _previews = [];
      _errorMessage = null;
      _secondsRemaining = 900;
    });
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D1B2A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white70),
          onPressed: () {
            _stopPolling();
            _stopCountdown();
            Navigator.of(context).pop();
          },
        ),
        title: const Row(
          children: [
            Icon(Icons.upload_file, color: Color(0xFF52B788), size: 22),
            SizedBox(width: 10),
            Text(
              'Import from Computer',
              style: TextStyle(
                color: Colors.white,
                fontSize: 17,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        actions: [
          if (_state != _UploadState.idle && _state != _UploadState.loading)
            IconButton(
              icon: const Icon(Icons.refresh, color: Colors.white54),
              tooltip: 'Start over',
              onPressed: _reset,
            ),
        ],
      ),
      body: AnimatedSwitcher(
        duration: const Duration(milliseconds: 350),
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    switch (_state) {
      case _UploadState.idle:
        return _buildIdleView();
      case _UploadState.loading:
        return _buildLoadingView('Creating upload session…');
      case _UploadState.link:
        return _buildLinkView();
      case _UploadState.preview:
        return _buildPreviewView();
      case _UploadState.saving:
        return _buildLoadingView('Saving parcels to your account…');
      case _UploadState.done:
        return _buildDoneView();
      case _UploadState.error:
        return _buildErrorView();
    }
  }

  // -------------------------------------------------------------------------
  // Idle screen
  // -------------------------------------------------------------------------

  Widget _buildIdleView() {
    return ListView(
      key: const ValueKey('idle'),
      padding: const EdgeInsets.all(20),
      children: [
        _card(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFF52B788).withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(Icons.link,
                        color: Color(0xFF52B788), size: 28),
                  ),
                  const SizedBox(width: 14),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Link · Drop · Done',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        SizedBox(height: 2),
                        Text(
                          'Import APIA boundaries from your PC in seconds',
                          style: TextStyle(
                            color: Colors.white54,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              ..._buildSteps(),
            ],
          ),
        ),
        const SizedBox(height: 20),

        _card(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Supported Formats',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 12),
              _formatChip(Icons.track_changes, '.GPX',
                  'GPS Exchange Format — APIA standard export'),
            ],
          ),
        ),
        const SizedBox(height: 28),

        SizedBox(
          height: 56,
          child: ElevatedButton.icon(
            onPressed: _startSession,
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF52B788),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              elevation: 0,
            ),
            icon: const Icon(Icons.link, size: 22),
            label: const Text(
              'Get Upload Link',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
          ),
        ),
      ],
    );
  }

  List<Widget> _buildSteps() {
    final steps = [
      (Icons.touch_app, 'Tap "Get Upload Link" on this screen'),
      (Icons.open_in_browser, 'Copy the link and open it on your PC browser'),
      (Icons.upload_file, 'Drag your .gpx files from APIA downloads'),
      (Icons.check_circle_outline, 'Review & confirm on this screen'),
    ];

    return steps.asMap().entries.map((entry) {
      final i = entry.key;
      final step = entry.value;
      final isLast = i == steps.length - 1;

      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: const Color(0xFF52B788).withValues(alpha: 0.15),
                  shape: BoxShape.circle,
                ),
                child: Icon(step.$1,
                    color: const Color(0xFF52B788), size: 16),
              ),
              if (!isLast)
                Container(
                  width: 1,
                  height: 24,
                  color: const Color(0xFF52B788).withValues(alpha: 0.2),
                ),
            ],
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 16, top: 6),
              child: Text(
                step.$2,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.7),
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
            ),
          ),
        ],
      );
    }).toList();
  }

  // -------------------------------------------------------------------------
  // Loading screen
  // -------------------------------------------------------------------------

  Widget _buildLoadingView(String message) {
    return Center(
      key: const ValueKey('loading'),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(
            color: Color(0xFF52B788),
            strokeWidth: 3,
          ),
          const SizedBox(height: 20),
          Text(
            message,
            style: TextStyle(
                color: Colors.white.withValues(alpha: 0.6), fontSize: 14),
          ),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Link screen
  // -------------------------------------------------------------------------

  Widget _buildLinkView() {
    final session = _session!;
    final mins = _secondsRemaining ~/ 60;
    final secs = _secondsRemaining % 60;
    final timeStr = '$mins:${secs.toString().padLeft(2, '0')}';
    final isUrgent = _secondsRemaining < 120;

    return ListView(
      key: const ValueKey('link'),
      padding: const EdgeInsets.all(20),
      children: [
        // Instruction banner
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: const Color(0xFF52B788).withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: const Color(0xFF52B788).withValues(alpha: 0.25),
            ),
          ),
          child: const Row(
            children: [
              Icon(Icons.info_outline, color: Color(0xFF52B788), size: 18),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Copy this link and open it on your PC browser — then drag your .gpx files',
                  style: TextStyle(
                      color: Colors.white70, fontSize: 13, height: 1.4),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),

        // Link card
        _card(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header
              const Row(
                children: [
                  Icon(Icons.link, color: Color(0xFF52B788), size: 24),
                  SizedBox(width: 10),
                  Text(
                    'Upload Link Ready',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),

              // Copyable URL
              InkWell(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: session.uploadUrl));
                  ScaffoldMessenger.of(context).showSnackBar(
                    _snackBar('Link copied to clipboard'),
                  );
                },
                borderRadius: BorderRadius.circular(12),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFF52B788).withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: const Color(0xFF52B788).withValues(alpha: 0.3),
                    ),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          session.uploadUrl,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontFamily: 'monospace',
                            height: 1.5,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 8),
                        decoration: BoxDecoration(
                          color: const Color(0xFF52B788),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.copy, color: Colors.white, size: 14),
                            SizedBox(width: 5),
                            Text(
                              'Copy',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // Timer
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.timer_outlined,
                    size: 15,
                    color: isUrgent ? Colors.orange : Colors.white38,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    'Expires in $timeStr',
                    style: TextStyle(
                      color: isUrgent ? Colors.orange : Colors.white38,
                      fontSize: 13,
                      fontWeight:
                          isUrgent ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Polling indicator
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 1.5,
                color: Colors.white.withValues(alpha: 0.3),
              ),
            ),
            const SizedBox(width: 10),
            Text(
              'Waiting for files…',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.35),
                fontSize: 13,
              ),
            ),
          ],
        ),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // Preview screen
  // -------------------------------------------------------------------------

  Widget _buildPreviewView() {
    return ListView(
      key: const ValueKey('preview'),
      padding: const EdgeInsets.all(20),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF52B788).withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: const Color(0xFF52B788).withValues(alpha: 0.25),
            ),
          ),
          child: Row(
            children: [
              const Icon(Icons.check_circle,
                  color: Color(0xFF52B788), size: 22),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${_previews.length} parcel${_previews.length != 1 ? 's' : ''} detected',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Review before saving to your account',
                      style: TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        ..._previews.map(_buildParcelPreviewCard),
        const SizedBox(height: 24),

        SizedBox(
          height: 56,
          child: ElevatedButton.icon(
            onPressed: _confirm,
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF52B788),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16),
              ),
              elevation: 0,
            ),
            icon: const Icon(Icons.save_outlined, size: 22),
            label: Text(
              'Save ${_previews.length} parcel${_previews.length != 1 ? 's' : ''} & start monitoring',
              style: const TextStyle(
                  fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
        ),
        const SizedBox(height: 12),

        TextButton(
          onPressed: _reset,
          style: TextButton.styleFrom(foregroundColor: Colors.white38),
          child: const Text('Discard and start over'),
        ),
      ],
    );
  }

  Widget _buildParcelPreviewCard(GpxParcelPreview p) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xFF52B788).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(Icons.map_outlined,
                    color: Color(0xFF52B788), size: 18),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      p.name,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      p.filename,
                      style: const TextStyle(
                          color: Colors.white38, fontSize: 11),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              if (p.areaHa != null)
                _metaChip(Icons.straighten,
                    '${p.areaHa!.toStringAsFixed(2)} ha'),
              if (p.detectedCrop != null && p.detectedCrop!.isNotEmpty)
                _metaChip(Icons.grass, p.detectedCrop!),
              if (p.year != null)
                _metaChip(Icons.calendar_today, p.year!),
              _metaChip(Icons.place,
                  '${p.centreLat.toStringAsFixed(4)}°, ${p.centreLon.toStringAsFixed(4)}°'),
              _metaChip(Icons.timeline, '${p.coordinateCount} vertices'),
            ],
          ),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Done screen
  // -------------------------------------------------------------------------

  Widget _buildDoneView() {
    return Center(
      key: const ValueKey('done'),
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: const Color(0xFF52B788).withValues(alpha: 0.15),
                shape: BoxShape.circle,
                border: Border.all(
                  color: const Color(0xFF52B788).withValues(alpha: 0.4),
                  width: 2,
                ),
              ),
              child: const Icon(Icons.check_rounded,
                  color: Color(0xFF52B788), size: 40),
            ),
            const SizedBox(height: 24),
            Text(
              '$_createdCount parcel${_createdCount != 1 ? 's' : ''} imported!',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 22,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'NDVI satellite monitoring and weather alerts\nhave been activated automatically.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.55),
                fontSize: 14,
                height: 1.6,
              ),
            ),
            const SizedBox(height: 36),
            SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton.icon(
                onPressed: () => Navigator.of(context).pop(true),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF52B788),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  elevation: 0,
                ),
                icon: const Icon(Icons.map_outlined),
                label: const Text(
                  'View on Map',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextButton(
              onPressed: _reset,
              style: TextButton.styleFrom(foregroundColor: Colors.white38),
              child: const Text('Import more files'),
            ),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Error screen
  // -------------------------------------------------------------------------

  Widget _buildErrorView() {
    return Center(
      key: const ValueKey('error'),
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: Colors.red.withValues(alpha: 0.1),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.error_outline,
                  color: Colors.redAccent, size: 36),
            ),
            const SizedBox(height: 20),
            const Text(
              'Something went wrong',
              style: TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              _errorMessage ?? 'Unknown error.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 13,
                height: 1.5,
              ),
            ),
            const SizedBox(height: 28),
            ElevatedButton.icon(
              onPressed: _reset,
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF52B788),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
                elevation: 0,
              ),
              icon: const Icon(Icons.refresh),
              label: const Text('Try Again'),
            ),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Reusable small widgets
  // -------------------------------------------------------------------------

  Widget _card({required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.04),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: child,
    );
  }

  Widget _formatChip(IconData icon, String format, String description) {
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: const Color(0xFF52B788).withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: const Color(0xFF52B788), size: 14),
              const SizedBox(width: 6),
              Text(
                format,
                style: const TextStyle(
                  color: Color(0xFF52B788),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            description,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5),
              fontSize: 12,
            ),
          ),
        ),
      ],
    );
  }

  Widget _metaChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: Colors.white38),
          const SizedBox(width: 5),
          Text(label,
              style: const TextStyle(color: Colors.white54, fontSize: 11)),
        ],
      ),
    );
  }

  SnackBar _snackBar(String message) {
    return SnackBar(
      content: Text(message),
      backgroundColor: const Color(0xFF2D6A4F),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      margin: const EdgeInsets.all(12),
      duration: const Duration(seconds: 2),
    );
  }
}
