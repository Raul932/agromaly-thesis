import 'package:flutter/material.dart';
import '../services/chat_service.dart';
import '../services/chat_history_store.dart';

/// Global AI Agronomist — a full-screen conversational assistant
/// powered by the backend's RAG pipeline (POST /api/v1/chat/ask).
///
/// If the RAG endpoint is not yet deployed, the screen gracefully
/// displays an "AI backend not connected" message while keeping
/// the UI fully functional for demo / thesis purposes.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen>
    with SingleTickerProviderStateMixin {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatMessage> _messages = [];
  final List<Map<String, String>> _history = [];
  bool _isSending = false;

  // Suggested starter questions
  static const _starters = [
    'De ce s-au îngălbenit frunzele de grâu?',
    'Cum tratez porumbul afectat de secetă?',
    'Care e schema optimă de fertilizare la floarea-soarelui?',
    'Când e cel mai bun moment să aplic tratamentele?',
  ];

  static const _greeting =
      'Salut! Sunt Agronomul tău AI din platforma Agromaly. '
      'Te pot ajuta cu sănătatea culturilor, combaterea dăunătorilor, irigare, '
      'fertilizare și cele mai bune practici agricole.\n\n'
      'Cu ce te pot ajuta astăzi?';

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    final saved = await ChatHistoryStore.load(ChatHistoryStore.globalKey);
    if (!mounted) return;
    setState(() {
      _messages.clear();
      _history.clear();
      if (saved.isEmpty) {
        _messages.add(_ChatMessage(
          text: _greeting,
          isUser: false,
          timestamp: DateTime.now(),
        ));
      } else {
        for (final m in saved) {
          final msg = _ChatMessage.fromJson(m);
          _messages.add(msg);
          // Rebuild RAG history from non-error turns
          if (!msg.isOffline) {
            _history.add({
              'role': msg.isUser ? 'user' : 'assistant',
              'content': msg.text,
            });
          }
        }
      }
    });
    _scrollToBottom();
  }

  Future<void> _persist() async {
    await ChatHistoryStore.save(
      ChatHistoryStore.globalKey,
      _messages.map((m) => m.toJson()).toList(),
    );
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _sendMessage(String text) async {
    if (text.trim().isEmpty || _isSending) return;

    final userMsg = _ChatMessage(
      text: text.trim(),
      isUser: true,
      timestamp: DateTime.now(),
    );

    setState(() {
      _messages.add(userMsg);
      _isSending = true;
      _inputController.clear();
    });

    _scrollToBottom();

    try {
      final answer = await ChatService.askGlobal(
        text.trim(),
        List.from(_history),
      );

      _history.add({'role': 'user', 'content': text.trim()});
      _history.add({'role': 'assistant', 'content': answer});

      setState(() {
        _messages.add(_ChatMessage(
          text: answer,
          isUser: false,
          timestamp: DateTime.now(),
        ));
        _isSending = false;
      });
      _persist();
    } catch (e) {
      setState(() {
        _messages.add(_ChatMessage(
          text: 'Nu am putut contacta serviciul AI. '
              '${e.toString().replaceFirst("Exception: ", "")}',
          isUser: false,
          timestamp: DateTime.now(),
          isOffline: true,
        ));
        _isSending = false;
      });
      _persist();
    }

    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
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
            Icon(Icons.smart_toy, color: Color(0xFF52B788), size: 22),
            SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Agronom AI',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Text(
                  'Consultant agricol inteligent',
                  style: TextStyle(
                    color: Colors.white38,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline, color: Colors.white38),
            tooltip: 'Șterge conversația',
            onPressed: () {
              setState(() {
                _messages.clear();
                _history.clear();
                _messages.add(_ChatMessage(
                  text: 'Conversație ștearsă. Cu ce te pot ajuta?',
                  isUser: false,
                  timestamp: DateTime.now(),
                ));
              });
              ChatHistoryStore.clear(ChatHistoryStore.globalKey);
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // Chat messages
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              itemCount: _messages.length + (_isSending ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == _messages.length) {
                  return _typingIndicator();
                }
                return _chatBubble(_messages[index]);
              },
            ),
          ),

          // Starter suggestions (only when fresh)
          if (_messages.length == 1) _starterSuggestions(),

          // Input row
          _inputBar(),
        ],
      ),
    );
  }

  Widget _chatBubble(_ChatMessage msg) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment:
            msg.isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!msg.isUser) ...[
            Container(
              width: 32,
              height: 32,
              margin: const EdgeInsets.only(right: 8, bottom: 2),
              decoration: BoxDecoration(
                color: const Color(0xFF52B788).withValues(alpha: 0.2),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.smart_toy,
                color: Color(0xFF52B788),
                size: 17,
              ),
            ),
          ],
          Flexible(
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: msg.isUser
                    ? const Color(0xFF52B788).withValues(alpha: 0.85)
                    : Colors.white.withValues(alpha: 0.06),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(18),
                  topRight: const Radius.circular(18),
                  bottomLeft: msg.isUser
                      ? const Radius.circular(18)
                      : const Radius.circular(4),
                  bottomRight: msg.isUser
                      ? const Radius.circular(4)
                      : const Radius.circular(18),
                ),
                border: msg.isUser
                    ? null
                    : Border.all(
                        color: msg.isOffline
                            ? const Color(0xFFE9C46A).withValues(alpha: 0.2)
                            : Colors.white.withValues(alpha: 0.08),
                      ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    msg.text,
                    style: TextStyle(
                      color: msg.isUser ? Colors.white : Colors.white70,
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatTime(msg.timestamp),
                    style: TextStyle(
                      color: msg.isUser
                          ? Colors.white.withValues(alpha: 0.5)
                          : Colors.white24,
                      fontSize: 10,
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (msg.isUser) const SizedBox(width: 8),
        ],
      ),
    );
  }

  Widget _typingIndicator() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            margin: const EdgeInsets.only(right: 8),
            decoration: BoxDecoration(
              color: const Color(0xFF52B788).withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.smart_toy,
                color: Color(0xFF52B788), size: 17),
          ),
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(18),
              border:
                  Border.all(color: Colors.white.withValues(alpha: 0.08)),
            ),
            child: const SizedBox(
              width: 36,
              height: 16,
              child: _TypingDots(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _starterSuggestions() {
    return Container(
      height: 44,
      margin: const EdgeInsets.only(bottom: 8),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: _starters.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) => ActionChip(
          label: Text(
            _starters[i],
            style: const TextStyle(
              color: Color(0xFF52B788),
              fontSize: 12,
            ),
          ),
          backgroundColor: const Color(0xFF52B788).withValues(alpha: 0.1),
          side: BorderSide(
            color: const Color(0xFF52B788).withValues(alpha: 0.3),
          ),
          onPressed: () => _sendMessage(_starters[i]),
        ),
      ),
    );
  }

  Widget _inputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 16),
      decoration: BoxDecoration(
        color: const Color(0xFF0D1B2A),
        border: Border(
          top: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _inputController,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'Întreabă Agronomul AI...',
                hintStyle:
                    const TextStyle(color: Colors.white38, fontSize: 14),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.05),
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide.none,
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide(
                    color: const Color(0xFF52B788).withValues(alpha: 0.5),
                  ),
                ),
              ),
              onSubmitted: _sendMessage,
              textInputAction: TextInputAction.send,
              maxLines: null,
            ),
          ),
          const SizedBox(width: 8),
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            child: FloatingActionButton.small(
              heroTag: 'chat_send',
              backgroundColor: _isSending
                  ? Colors.white12
                  : const Color(0xFF52B788),
              elevation: 0,
              onPressed: _isSending
                  ? null
                  : () => _sendMessage(_inputController.text),
              child: _isSending
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white38,
                      ),
                    )
                  : const Icon(Icons.send_rounded,
                      color: Colors.white, size: 18),
            ),
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}

/// Animated three-dot typing indicator.
class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) {
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(3, (i) {
            final phase = ((_ctrl.value * 3) - i).clamp(0.0, 1.0);
            final opacity = (phase < 0.5 ? phase * 2 : (1 - phase) * 2)
                .clamp(0.3, 1.0);
            return Container(
              margin: const EdgeInsets.symmetric(horizontal: 2),
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                color: const Color(0xFF52B788).withValues(alpha: opacity),
                shape: BoxShape.circle,
              ),
            );
          }),
        );
      },
    );
  }
}

class _ChatMessage {
  final String text;
  final bool isUser;
  final DateTime timestamp;
  final bool isOffline;

  const _ChatMessage({
    required this.text,
    required this.isUser,
    required this.timestamp,
    this.isOffline = false,
  });

  Map<String, dynamic> toJson() => {
        'text': text,
        'isUser': isUser,
        'timestamp': timestamp.toIso8601String(),
        'isOffline': isOffline,
      };

  factory _ChatMessage.fromJson(Map<String, dynamic> json) => _ChatMessage(
        text: json['text'] as String? ?? '',
        isUser: json['isUser'] as bool? ?? false,
        timestamp: DateTime.tryParse(json['timestamp'] as String? ?? '') ??
            DateTime.now(),
        isOffline: json['isOffline'] as bool? ?? false,
      );
}
